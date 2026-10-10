"""The guided-adoption wizard: derivation, preflight, and the binding anchor."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hdsh.adopt import wizard


def transport(**results: str) -> wizard.Transport:
    """Build an injected transport mapping command lines to outcomes."""
    return {
        command: subprocess.CompletedProcess(command.split(), 0, stdout=stdout, stderr="")
        for command, stdout in results.items()
    }


def failing(command: str) -> wizard.Transport:
    """A transport whose one command fails."""
    return {command: subprocess.CompletedProcess(command.split(), 1, stdout="", stderr="boom")}


class TestResolveHdshRef:
    def test_the_flag_wins(self) -> None:
        resolution = wizard.resolve_hdsh_ref("v0.1.0", None)
        assert (resolution.value, resolution.source) == ("v0.1.0", wizard.FLAG)

    def test_the_latest_release_tag_is_the_default(self) -> None:
        results = transport(
            **{
                "git ls-remote --tags https://github.com/jukanntenn/harness-deepseek-harness": (
                    "a\trefs/tags/v0.1.0\nb\trefs/tags/v0.9.0\n"
                )
            }
        )
        resolution = wizard.resolve_hdsh_ref(None, results)
        assert (resolution.value, resolution.source) == ("v0.9.0", wizard.DEFAULT)

    def test_consumer_origin_tags_are_never_consulted(self) -> None:
        results = transport(**{"git ls-remote --tags origin": "a\trefs/tags/v9.9.9\n"})
        with pytest.raises(wizard.WizardError, match="no release tag"):
            wizard.resolve_hdsh_ref(None, results)

    def test_no_tags_fails_loud_with_no_main_fallback(self) -> None:
        results = transport(
            **{"git ls-remote --tags https://github.com/jukanntenn/harness-deepseek-harness": ""}
        )
        with pytest.raises(wizard.WizardError, match="no release tag"):
            wizard.resolve_hdsh_ref(None, results)

    def test_nonrelease_tags_do_not_count(self) -> None:
        results = transport(
            **{
                "git ls-remote --tags https://github.com/jukanntenn/harness-deepseek-harness": (
                    "a\trefs/tags/nightly\n"
                )
            }
        )
        with pytest.raises(wizard.WizardError, match="no release tag"):
            wizard.resolve_hdsh_ref(None, results)


class TestResolveAccountType:
    def test_the_flag_wins(self) -> None:
        resolution = wizard.resolve_account_type("user", "o", "r", None)
        assert (resolution.value, resolution.source) == ("user", wizard.FLAG)

    def test_user_owners_derive_the_user_flavor(self) -> None:
        results = transport(**{"gh api repos/o/r --jq .owner.type": "User"})
        resolution = wizard.resolve_account_type(None, "o", "r", results)
        assert (resolution.value, resolution.source) == ("user", wizard.DERIVED)

    def test_organization_owners_derive_the_organization_flavor(self) -> None:
        results = transport(**{"gh api repos/o/r --jq .owner.type": "Organization"})
        resolution = wizard.resolve_account_type(None, "o", "r", results)
        assert (resolution.value, resolution.source) == ("organization", wizard.DERIVED)

    def test_an_unreadable_owner_type_fails_loud(self) -> None:
        with pytest.raises(wizard.WizardError, match="could not be derived"):
            wizard.resolve_account_type(
                None, "o", "r", failing("gh api repos/o/r --jq .owner.type")
            )


class TestResolveLifecycleActor:
    def test_the_flag_wins(self) -> None:
        resolution = wizard.resolve_lifecycle_actor("bot", None)
        assert (resolution.value, resolution.source) == ("bot", wizard.FLAG)

    def test_the_gh_identity_derives_the_actor(self) -> None:
        results = transport(**{"gh api user --jq .login": "operator"})
        resolution = wizard.resolve_lifecycle_actor(None, results)
        assert (resolution.value, resolution.source) == ("operator", wizard.DERIVED)

    def test_a_rejected_credential_fails_loud_as_unauthenticated(self) -> None:
        rejected = {
            "gh api user --jq .login": subprocess.CompletedProcess(
                ["gh", "api", "user", "--jq", ".login"],
                1,
                stdout="",
                stderr="gh: To use GitHub CLI, please run: gh auth login\n",
            )
        }
        with pytest.raises(wizard.WizardError, match="gh is not authenticated"):
            wizard.resolve_lifecycle_actor(None, rejected)

    def test_a_probe_failure_keeps_the_exit_status_and_stderr(self) -> None:
        with pytest.raises(wizard.WizardError, match=r"exited 1: boom.*rerun if transient"):
            wizard.resolve_lifecycle_actor(None, failing("gh api user --jq .login"))

    def test_a_probe_failure_never_claims_a_missing_credential(self) -> None:
        with pytest.raises(wizard.WizardError) as raised:
            wizard.resolve_lifecycle_actor(None, failing("gh api user --jq .login"))
        assert "not authenticated" not in str(raised.value)

    def test_an_absent_gh_names_the_install_remedy(self) -> None:
        with pytest.raises(wizard.WizardError, match="gh is not runnable on PATH"):
            wizard.resolve_lifecycle_actor(None, {})

    def test_an_empty_login_fails_loud(self) -> None:
        empty = {
            "gh api user --jq .login": subprocess.CompletedProcess(
                ["gh", "api", "user", "--jq", ".login"], 0, stdout="\n", stderr=""
            )
        }
        with pytest.raises(wizard.WizardError, match="empty login"):
            wizard.resolve_lifecycle_actor(None, empty)


class TestResolveTimeZone:
    def test_the_flag_wins(self) -> None:
        resolution = wizard.resolve_time_zone("Asia/Shanghai")
        assert (resolution.value, resolution.source) == ("Asia/Shanghai", wizard.FLAG)

    def test_the_local_zone_links_to_iana(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = tmp_path / "zoneinfo" / "Asia" / "Shanghai"
        link.parent.mkdir(parents=True)
        link.write_text("", encoding="utf-8")
        monkeypatch.setattr(wizard, "_LOCAL_TIMEZONE_LINK", str(tmp_path / "localtime"))
        (tmp_path / "localtime").symlink_to(link)
        resolution = wizard.resolve_time_zone(None)
        assert (resolution.value, resolution.source) == ("Asia/Shanghai", wizard.DEFAULT)

    def test_no_iana_name_fails_loud(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wizard, "_LOCAL_TIMEZONE_LINK", str(tmp_path / "nowhere"))
        with pytest.raises(wizard.WizardError, match="no IANA name"):
            wizard.resolve_time_zone(None)


class TestRealTransport:
    def test_a_real_probe_runs_without_a_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, check=False
        )

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return completed

        monkeypatch.setattr(wizard.subprocess, "run", fake_run)
        assert wizard._run(["git", "--version"], None) is completed

    def test_an_absent_executable_answers_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def absent_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("gh")

        monkeypatch.setattr(wizard.subprocess, "run", absent_run)
        completed = wizard._run(["gh", "api", "user"], None)
        assert completed.returncode == wizard._COMMAND_NOT_FOUND
        assert completed.stderr == "command not found"

    def test_the_local_timezone_oserror_path_fails_loud(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken_resolve(self: Path) -> str:
            raise OSError("gone")

        monkeypatch.setattr(wizard.Path, "resolve", broken_resolve)
        with pytest.raises(wizard.WizardError, match="no IANA name"):
            wizard.resolve_time_zone(None)


class TestPreflightMain:
    def test_main_prints_one_line_per_failure_and_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def one_failure(transport: wizard.Transport | None) -> tuple[list[str], list[str]]:
            return ["gh is not authenticated; run gh auth login"], []

        monkeypatch.setattr(wizard, "preflight", one_failure)
        from tests.helpers import parse_command

        request = parse_command(wizard.register, ["preflight"])
        from hdsh.adopt.wizard import main

        assert main(request) == 1
        error = capsys.readouterr().err
        assert "gh is not authenticated" in error
        assert "1 preflight failure(s)" in error

    def test_main_reports_a_ready_toolchain(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def no_failures(transport: wizard.Transport | None) -> tuple[list[str], list[str]]:
            return [], []

        monkeypatch.setattr(wizard, "preflight", no_failures)
        from tests.helpers import parse_command

        request = parse_command(wizard.register, ["preflight"])
        from hdsh.adopt.wizard import main

        assert main(request) == 0
        assert "local toolchain ready" in capsys.readouterr().out


class TestPreflight:
    READY: wizard.Transport = transport(
        **{
            "git --version": "git version 2.45.0",
            "gh auth status": "Logged in",
            "hdsh --version": "hdsh 0.1.0",
            "rg --version": "ripgrep 14.1.0",
        }
    )

    def test_a_ready_toolchain_reports_nothing(self) -> None:
        assert wizard.preflight(self.READY) == ([], [])

    def test_each_absent_tool_is_one_diagnostic(self) -> None:
        failures, notices = wizard.preflight({})
        assert len(failures) == 4
        assert any("git is not runnable" in line for line in failures)
        assert any("gh is not runnable" in line for line in failures)
        assert any("bare hdsh is not runnable" in line for line in failures)
        assert any("ripgrep is not runnable" in line for line in failures)
        assert notices == []

    def test_a_rejected_credential_still_names_the_login_remedy(self) -> None:
        rejected = {
            **{key: value for key, value in self.READY.items() if key != "gh auth status"},
            "gh auth status": subprocess.CompletedProcess(
                ["gh", "auth", "status"],
                1,
                stdout="",
                stderr="You are not logged into any GitHub hosts. Run gh auth login.\n",
            ),
        }
        failures, _ = wizard.preflight(rejected)
        assert failures == ["gh is not authenticated; run gh auth login"]

    def test_a_preflight_probe_failure_is_never_read_as_a_missing_credential(self) -> None:
        unreachable = {
            **{key: value for key, value in self.READY.items() if key != "gh auth status"},
            "gh auth status": subprocess.CompletedProcess(
                ["gh", "auth", "status"],
                1,
                stdout="",
                stderr="gh: error connecting to api.github.com:\n    dial tcp: no route\n",
            ),
        }
        failures, _ = wizard.preflight(unreachable)
        assert failures == [
            (
                "the gh probe failed (gh auth status exited 1: gh: error connecting to "
                "api.github.com:); rerun if transient"
            )
        ]

    def test_the_hdsh_remediation_names_the_git_install_form(self) -> None:
        failures, _ = wizard.preflight(
            {key: value for key, value in self.READY.items() if key != "hdsh --version"}
        )
        assert any("git+<url>@<ref>" in line for line in failures)

    def test_a_scopeless_token_earns_the_refresh_notice(self) -> None:
        results = {
            **{key: value for key, value in self.READY.items() if key != "gh auth status"},
            "gh auth status": subprocess.CompletedProcess(
                ["gh", "auth", "status"],
                0,
                stdout="github.com\n  Token scopes: 'gist', 'read:org', 'repo'\n",
                stderr="",
            ),
        }
        failures, notices = wizard.preflight(results)
        assert failures == []
        assert notices == [
            (
                "gh token lacks the 'project' scope; creating the Phase 1 board needs it — "
                "run gh auth refresh -s project (advisory: the workflows' own credentials "
                "are unaffected)"
            )
        ]

    def test_a_token_already_carrying_project_earns_no_notice(self) -> None:
        results = {
            **{key: value for key, value in self.READY.items() if key != "gh auth status"},
            "gh auth status": subprocess.CompletedProcess(
                ["gh", "auth", "status"],
                0,
                stdout="github.com\n  Token scopes: 'project', 'repo'\n",
                stderr="",
            ),
        }
        assert wizard.preflight(results) == ([], [])


class TestProjectScopeNotice:
    def test_disclosed_scopes_without_project_advise_the_refresh(self) -> None:
        notice = wizard.gh_project_scope_notice("  Token scopes: 'gist', 'repo'")
        assert notice is not None
        assert "gh auth refresh -s project" in notice

    def test_ghs_list_marker_form_discloses_scopes_too(self) -> None:
        # Current gh prints the scopes line behind a `- ` list marker; the
        # notice must fire there, or a scopeless token passes preflight.
        notice = wizard.gh_project_scope_notice("  - Token scopes: 'gist', 'read:org', 'repo'")
        assert notice is not None
        assert "gh auth refresh -s project" in notice

    def test_no_disclosed_scopes_stay_silent(self) -> None:
        assert wizard.gh_project_scope_notice("Logged in to github.com") is None
        assert wizard.gh_project_scope_notice("") is None

    def test_any_mention_of_project_counts(self) -> None:
        assert wizard.gh_project_scope_notice("Token scopes: read:project, repo") is None
        assert wizard.gh_project_scope_notice("- Token scopes: 'project', 'repo'") is None


class TestChecklist:
    def test_every_taxonomy_label_prints_with_its_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from hdsh.policy import rules
        from tests.helpers import parse_command

        parsed = parse_command(wizard.register, ["checklist"])
        assert wizard.checklist_main(parsed) == 0
        output = capsys.readouterr().out
        for name, description in rules.LABEL_DESCRIPTIONS.items():
            assert f'gh label create {name} --description "{description}"' in output
        assert "user accounts also carry the Issue classification on type/* labels" in output
        assert "area/* labels are consumer-specific" in output

    def test_the_board_enumeration_prints_statuses_and_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from hdsh.adopt.corpus import STANDARD_STATUSES
        from tests.helpers import parse_command

        parsed = parse_command(wizard.register, ["checklist"])
        assert wizard.checklist_main(parsed) == 0
        output = capsys.readouterr().out
        assert all(status in output for status in STANDARD_STATUSES)
        assert "gh cannot edit those options; the mutation below sets all seven" in output
        assert 'query{user(login:"<owner>"){projectV2(number:<number>)' in output
        assert "updateProjectV2Field(input:{projectId:$p,fieldId:$f,singleSelectOptions:[" in output
        assert '{name:"Inbox"},{name:"Backlog"},{name:"Ready"},{name:"In progress"},' in output
        assert 'organization(login:"<owner>")' in output
        field_create = (
            '--name Priority --data-type SINGLE_SELECT --single-select-options "p0,p1,p2,p3"'
        )
        assert field_create in output
        assert '--name "Start date" --data-type DATE' in output
        assert "gh project create --title <title> --owner <owner>" in output
        assert "gh project link <number> --owner <owner> --repo <repository>" in output
        assert "gh auth refresh -s project" in output

    def test_the_taxonomy_covers_exactly_the_closed_sets(self) -> None:
        from hdsh.policy import rules

        assert set(rules.LABEL_DESCRIPTIONS) == set(rules.PR_KINDS) | set(rules.TYPE_LABELS) | set(
            rules.PRIORITIES
        )


class TestPreflightNotices:
    def test_main_prints_advisories_without_failing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def advisory_only(transport: wizard.Transport | None) -> tuple[list[str], list[str]]:
            return [], ["gh token lacks the 'project' scope"]

        monkeypatch.setattr(wizard, "preflight", advisory_only)
        from tests.helpers import parse_command

        request = parse_command(wizard.register, ["preflight"])
        from hdsh.adopt.wizard import main

        assert main(request) == 0
        captured = capsys.readouterr()
        assert "gh token lacks the 'project' scope" in captured.out
        assert captured.err == ""
