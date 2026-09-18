"""The adopt command leaves: plan, apply, and verify over real repositories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import hdsh.adopt.commands as adopt_module
from hdsh.adopt import commands as adopt_commands
from hdsh.adopt.commands import (
    _apply_prek_block,
    _gitattributes_content,
    _gitattributes_driver,
    _managed_prek_block,
    apply_main,
    plan_main,
    verify_main,
)
from hdsh.pairing.verify import run_gate, verify_request
from tests.adopt.conftest import adopt_arguments, commit_all
from tests.helpers import Repo, git, parse_command


def plan_cli(*arguments: str) -> int:
    """Run ``hdsh adopt plan`` with parsed arguments."""
    return plan_main(parse_command(adopt_commands.register, ["plan", *arguments]))


def apply_cli(*arguments: str) -> int:
    """Run ``hdsh adopt apply`` with parsed arguments."""
    return apply_main(parse_command(adopt_commands.register, ["apply", *arguments]))


def verify_cli() -> int:
    """Run ``hdsh adopt verify``."""
    return verify_main(parse_command(adopt_commands.register, ["verify"]))


def pairing_check(root: Path) -> int:
    """Run the corpus-wide pairing gate against one repository root."""
    return run_gate(verify_request(argparse.Namespace(cached=False, anchors=[])), str(root))


class TestPlan:
    def test_plan_writes_nothing_and_lists_the_installation(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plan_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert "would write prek.toml" in output
        assert "would write .gitattributes" in output
        assert "would record pair .agents/rfcs/README.md" in output
        assert git("status", "--porcelain", cwd=consumer.root).stdout.strip() == ""

    def test_plan_reports_every_blocker_without_writing(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write("docs/AGENTS.md", "# conflicting standard\n")
        commit_all(consumer, "conflicting standard")
        assert plan_cli(*adopt_arguments()) == 1
        error = capsys.readouterr().err
        assert "1 blocker(s) prevent adoption" in error
        assert "docs/AGENTS.md" in error
        assert git("status", "--porcelain", cwd=consumer.root).stdout.strip() == ""


class TestApplyRoundTrip:
    def test_apply_installs_the_full_corpus_and_records_pairs(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert "installed 48 file(s); recorded 7 pair(s)" in output
        assert (consumer.root / ".agents" / "skills" / "pushing" / "SKILL.md").is_file()
        assert (consumer.root / "docs" / "i18n" / "README.zh.md").is_file()
        assert (consumer.root / ".github" / "workflows" / "issue-policy.yml").is_file()
        assert "project-token: ${{ secrets.HDSH_ISSUE_PROJECT_TOKEN }}" in (
            consumer.root / ".github" / "workflows" / "issue-policy.yml"
        ).read_text(encoding="utf-8")
        assert "uses: jukanntenn/harness-deepseek-harness/.github/actions/issue-policy@v0.1.0" in (
            consumer.root / ".github" / "workflows" / "issue-policy.yml"
        ).read_text(encoding="utf-8")
        config = json.loads(
            (consumer.root / ".github" / "issue-management" / "config.json").read_text(
                encoding="utf-8"
            )
        )
        assert config["accountType"] == "user"
        assert config["owner"] == "consumer-org"
        assert config["repository"] == "consumer-repo"
        assert "*.i18n.yaml merge=hdsh-pairing" in (consumer.root / ".gitattributes").read_text(
            encoding="utf-8"
        )
        assert 'rev = "v0.1.0"' in (consumer.root / "prek.toml").read_text(encoding="utf-8")
        rewritten = (consumer.root / ".agents" / "rfcs" / "README.md").read_text(encoding="utf-8")
        assert (
            "https://github.com/jukanntenn/harness-deepseek-harness/blob/v0.1.0/"
            "src/hdsh/rfc/format.py" in rewritten
        )
        manifest = json.loads(
            (consumer.root / ".hdsh" / "adopt.manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["hdshRef"] == "v0.1.0"
        assert manifest["files"][".agents/rfcs/AGENTS.md"]
        assert "prek.toml" not in manifest["files"]
        assert "docs/architecture.md" not in manifest["files"]
        assert manifest["editable"] == [
            "AGENTS.md",
            "docs/architecture.md",
            "docs/architecture.zh.md",
            "docs/development.md",
            "docs/development.zh.md",
        ]
        assert pairing_check(consumer.root) == 0

    def test_organization_flavor_renders_app_credentials(self, consumer: Repo) -> None:
        assert apply_cli(*adopt_arguments("--account-type", "organization")) == 0
        workflow = (consumer.root / ".github" / "workflows" / "issue-lifecycle.yml").read_text(
            encoding="utf-8"
        )
        assert "app-client-id: ${{ vars.HDSH_ISSUE_APP_CLIENT_ID }}" in workflow

    def test_public_blob_root_override_lands_in_the_seed(
        self, consumer: Repo, tmp_path: Path
    ) -> None:
        url = "https://example.com/consumer/blob/main/"
        assert apply_cli(*adopt_arguments("--public-blob-root", url)) == 0
        manifest = json.loads(
            (consumer.root / ".hdsh" / "pairing.manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["public_blob_root"] == url

    def test_reapply_is_idempotent(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        assert apply_cli(*adopt_arguments()) == 0
        assert "the .gitattributes pairing driver line is already present" in (
            capsys.readouterr().out
        )

    def test_upgrade_replaces_unmodified_files_and_the_pinned_ref(self, consumer: Repo) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        assert apply_cli(*adopt_arguments("--hdsh-ref", "v0.2.0")) == 0
        assert 'rev = "v0.2.0"' in (consumer.root / "prek.toml").read_text(encoding="utf-8")
        assert "issue-policy@v0.2.0" in (
            consumer.root / ".github" / "workflows" / "issue-policy.yml"
        ).read_text(encoding="utf-8")
        manifest = json.loads(
            (consumer.root / ".hdsh" / "adopt.manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["hdshRef"] == "v0.2.0"

    def test_consumer_modified_generated_file_refuses_reapplication(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        target = consumer.root / "docs" / "AGENTS.md"
        target.write_text("# locally edited\n", encoding="utf-8")
        commit_all(consumer, "local edit")
        assert apply_cli(*adopt_arguments()) == 1
        assert "docs/AGENTS.md" in capsys.readouterr().err
        assert target.read_text(encoding="utf-8") == "# locally edited\n"

    def test_recording_failure_fails_the_application(
        self, consumer: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def failing_gate(*args: object, **kwargs: object) -> int:
            return 1

        monkeypatch.setattr(adopt_module.pairing_verify, "run_gate", failing_gate)
        assert apply_cli(*adopt_arguments()) == 1
        assert "recording" in capsys.readouterr().err

    def test_existing_root_agents_md_is_skipped_not_refused(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (consumer.root / "AGENTS.md").write_text("# ours\n", encoding="utf-8")
        git("add", "-A", cwd=consumer.root)
        git("commit", "-qm", "standing orders", cwd=consumer.root)
        assert plan_cli(*adopt_arguments()) == 0
        assert "an existing root AGENTS.md was left untouched" in capsys.readouterr().out
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert "an existing root AGENTS.md was left untouched" in output
        assert (consumer.root / "AGENTS.md").read_text(encoding="utf-8") == "# ours\n"
        manifest = json.loads(
            (consumer.root / ".hdsh" / "adopt.manifest.json").read_text(encoding="utf-8")
        )
        assert "AGENTS.md" not in manifest["files"]


class TestBlockers:
    def test_refuses_outside_a_git_work_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert plan_cli(*adopt_arguments()) == 1
        assert "not a git work tree" in capsys.readouterr().err

    def test_refuses_a_dirty_worktree(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write("scratch.txt", "pending work\n")
        assert plan_cli(*adopt_arguments()) == 1
        assert "the worktree is dirty" in capsys.readouterr().err

    def test_refuses_without_a_github_origin(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        git("remote", "remove", "origin", cwd=consumer.root)
        assert plan_cli(*adopt_arguments()) == 1
        assert "origin remote" in capsys.readouterr().err

    def test_refuses_a_non_github_origin(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        git(
            "remote", "set-url", "origin", "https://gitlab.com/consumer/repo.git", cwd=consumer.root
        )
        assert plan_cli(*adopt_arguments()) == 1
        assert "origin remote" in capsys.readouterr().err

    def test_refuses_a_legacy_pre_commit_config(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write(".pre-commit-config.yaml", "repos: []\n")
        assert plan_cli(*adopt_arguments()) == 1
        assert ".pre-commit-config.yaml" in capsys.readouterr().err

    def test_refuses_invalid_prek_toml(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write("prek.toml", "not [ valid toml")
        assert plan_cli(*adopt_arguments()) == 1
        assert "not valid TOML" in capsys.readouterr().err

    def test_a_non_list_repos_field_fails_with_dedicated_guidance(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write("prek.toml", "repos = 0\n")
        commit_all(consumer, "typed repos field")
        assert apply_cli(*adopt_arguments()) == 1
        error = capsys.readouterr().err
        assert "the repos key is not an array of repository tables" in error
        assert "[[repos]] table form" in error

    def test_a_marker_replacement_that_breaks_toml_fails_loud(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write(
            "prek.toml",
            'x = """\n'
            "# BEGIN hdsh adopt (managed by hdsh adopt apply)\n"
            '"""\n'
            "y = 1\n"
            "# END hdsh adopt (managed by hdsh adopt apply)\n"
            "z = 2\n",
        )
        commit_all(consumer, "markers spanning a value")
        assert apply_cli(*adopt_arguments()) == 1
        error = capsys.readouterr().err
        assert "the managed block would produce invalid TOML" in error
        assert "Report this as a bug" in error

    def test_apply_refuses_outside_a_git_work_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert apply_cli(*adopt_arguments()) == 1
        assert "not a git work tree" in capsys.readouterr().err

    def test_verify_refuses_outside_a_git_work_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert verify_cli() == 1
        assert "not a git work tree" in capsys.readouterr().err

    def test_refuses_a_hand_pinned_harness_entry(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write(
            "prek.toml",
            '[[repos]]\nrepo = "https://github.com/jukanntenn/harness-deepseek-harness"\n'
            'rev = "v0.0.1"\n',
        )
        assert plan_cli(*adopt_arguments()) == 1
        assert "hand-pinned" in capsys.readouterr().err

    def test_refuses_a_foreign_merge_driver_mapping(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write(".gitattributes", "*.i18n.yaml merge=union\n")
        assert plan_cli(*adopt_arguments()) == 1
        assert "mapped to another driver" in capsys.readouterr().err

    def test_refuses_conflicting_existing_targets(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write("docs/AGENTS.md", "# conflicting standard\n")
        assert plan_cli(*adopt_arguments()) == 1
        error = capsys.readouterr().err
        assert "docs/AGENTS.md" in error
        assert "adopt never overwrites consumer-owned files" in error

    def test_refuses_a_malformed_previous_manifest(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write(".hdsh/adopt.manifest.json", "[]")
        assert plan_cli(*adopt_arguments()) == 1
        assert "previous adopt manifest is malformed" in capsys.readouterr().err

    def test_refuses_invalid_parameters(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plan_cli(*adopt_arguments("--account-type", "enterprise")) == 1
        assert "--account-type" in capsys.readouterr().err

    def test_refuses_unknown_time_zone(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plan_cli(*adopt_arguments("--time-zone", "Mars/Olympus")) == 1
        assert "--time-zone" in capsys.readouterr().err

    def test_refuses_non_positive_project_number(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plan_cli(*adopt_arguments("--project-number", "0")) == 1
        assert "--project-number" in capsys.readouterr().err


class TestVerify:
    def test_without_a_manifest_it_fails_with_guidance(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert verify_cli() == 1
        assert "run hdsh adopt apply first" in capsys.readouterr().err

    def test_reports_placeholders_until_they_are_completed(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        capsys.readouterr()
        assert verify_cli() == 1
        output = capsys.readouterr().out
        assert "TODO(adopt)" in output
        for path in consumer.root.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if "TODO(adopt):" in text:
                path.write_text(text.replace("TODO(adopt): ", ""), encoding="utf-8")
        capsys.readouterr()
        assert verify_cli() == 0
        assert "placeholder(s) remain" not in capsys.readouterr().out

    def test_reports_drift_on_modified_and_missing_files(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        target = consumer.root / "docs" / "AGENTS.md"
        target.write_text("# edited\n", encoding="utf-8")
        (consumer.root / ".agents" / "skills" / "pushing" / "SKILL.md").unlink()
        (consumer.root / "docs" / "architecture.md").unlink()
        capsys.readouterr()
        assert verify_cli() == 1
        error = capsys.readouterr().err
        assert "docs/AGENTS.md: content differs" in error
        assert ".agents/skills/pushing/SKILL.md: missing" in error
        assert "docs/architecture.md: missing" in error


class TestPrekBlockUnits:
    def test_managed_block_pins_the_ref_and_every_hook(self) -> None:
        block = _managed_prek_block("v9.9.9")
        assert 'rev = "v9.9.9"' in block
        for hook in (
            "hdsh-pairing-verify",
            "hdsh-rfc-verify",
            "hdsh-rfc-archive",
            "hdsh-docs-wrap",
            "hdsh-docs-links",
            "hdsh-docs-budgets",
        ):
            assert hook in block

    def test_block_is_appended_to_consumer_configuration(self) -> None:
        existing = 'default_install_hook_types = ["pre-commit"]\n'
        updated = _apply_prek_block(existing, _managed_prek_block("v1"))
        assert updated.startswith(existing)
        assert "default_install_hook_types" in updated
        assert "BEGIN hdsh adopt" in updated

    def test_block_is_replaced_wholesale_on_upgrade(self) -> None:
        first = _apply_prek_block(None, _managed_prek_block("v1"))
        second = _apply_prek_block(first, _managed_prek_block("v2"))
        assert 'rev = "v2"' in second
        assert 'rev = "v1"' not in second
        assert second.count("BEGIN hdsh adopt") == 1

    def test_append_to_content_without_a_trailing_newline(self) -> None:
        updated = _apply_prek_block("x = 1", _managed_prek_block("v1"))
        assert updated.startswith("x = 1\n")


class TestGitattributesUnits:
    def test_driver_detection(self) -> None:
        assert _gitattributes_driver(None) is None
        assert _gitattributes_driver("*.md text=auto\n") is None
        assert _gitattributes_driver("*.i18n.yaml merge=hdsh-pairing\n") == "hdsh-pairing"
        assert _gitattributes_driver("*.i18n.yaml merge=union\n") == "union"

    def test_content_appends_the_line(self) -> None:
        assert _gitattributes_content(None) == "*.i18n.yaml merge=hdsh-pairing\n"
        appended = _gitattributes_content("*.md text=auto")
        assert appended == "*.md text=auto\n*.i18n.yaml merge=hdsh-pairing\n"
        present = "*.md text=auto\n*.i18n.yaml merge=hdsh-pairing\n"
        assert _gitattributes_content(present) == present
        missing_newline = "*.md text=auto\n*.i18n.yaml merge=hdsh-pairing"
        assert _gitattributes_content(missing_newline) == present


class TestLeafParsing:
    def test_missing_required_flags_is_a_usage_error(self) -> None:
        with pytest.raises(ValueError, match="required"):
            parse_command(adopt_commands.register, ["apply"])

    def test_verify_takes_no_parameters(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse_command(adopt_commands.register, ["verify", "--hdsh-ref", "v1"])
