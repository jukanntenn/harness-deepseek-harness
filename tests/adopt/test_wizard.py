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
            **{"git ls-remote --tags origin": "a\trefs/tags/v0.1.0\nb\trefs/tags/v0.9.0\n"}
        )
        resolution = wizard.resolve_hdsh_ref(None, results)
        assert (resolution.value, resolution.source) == ("v0.9.0", wizard.DEFAULT)

    def test_no_tags_fails_loud_with_no_main_fallback(self) -> None:
        results = transport(**{"git ls-remote --tags origin": ""})
        with pytest.raises(wizard.WizardError, match="no release tag"):
            wizard.resolve_hdsh_ref(None, results)

    def test_nonrelease_tags_do_not_count(self) -> None:
        results = transport(**{"git ls-remote --tags origin": "a\trefs/tags/nightly\n"})
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

    def test_an_unauthenticated_gh_fails_loud(self) -> None:
        with pytest.raises(wizard.WizardError, match="not authenticated"):
            wizard.resolve_lifecycle_actor(None, failing("gh api user --jq .login"))


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
        def one_failure(transport: wizard.Transport | None) -> list[str]:
            return ["gh is not authenticated; run gh auth login"]

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
        def no_failures(transport: wizard.Transport | None) -> list[str]:
            return []

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
        }
    )

    def test_a_ready_toolchain_reports_nothing(self) -> None:
        assert wizard.preflight(self.READY) == []

    def test_each_absent_tool_is_one_diagnostic(self) -> None:
        failures = wizard.preflight({})
        assert len(failures) == 3
        assert any("git is not runnable" in line for line in failures)
        assert any("gh is not authenticated" in line for line in failures)
        assert any("bare hdsh is not runnable" in line for line in failures)
