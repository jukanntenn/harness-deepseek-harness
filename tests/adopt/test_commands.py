"""The adopt command leaves: plan, apply, and verify over real repositories."""

from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path

import pytest

import hdsh.adopt.commands as adopt_module
from hdsh.adopt import commands as adopt_commands
from hdsh.adopt.commands import (
    _apply_prek_block,
    _gitattributes_content,
    _gitattributes_driver,
    _managed_prek_block,
    _required_anchors,
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


def wire_ci_gates(repo: Repo) -> None:
    """Give the consumer repository a CI workflow that runs the gates.

    Apply installs only the policy workflows; wiring the gates into CI is the
    consumer's own step, so tests asserting a green verify wire it first.
    """
    (repo.root / ".github" / "workflows" / "gates.yml").write_text(
        "name: gates\n"
        "on: [push]\n"
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: prek run --all-files\n",
        encoding="utf-8",
    )


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
        consumer.write(".agents/skills/merging-stacked-prs/SKILL.md", "# conflicting skill\n")
        commit_all(consumer, "conflicting skill")
        assert plan_cli(*adopt_arguments()) == 1
        error = capsys.readouterr().err
        assert "1 blocker(s) prevent adoption" in error
        assert ".agents/skills/merging-stacked-prs/SKILL.md" in error
        assert git("status", "--porcelain", cwd=consumer.root).stdout.strip() == ""


class TestApplyRoundTrip:
    def test_apply_installs_the_full_corpus_and_records_pairs(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert "installed 61 file(s); recorded 13 pair(s)" in output
        assert "pairing corpus after apply: 14 English document(s) in scope" in output
        assert (consumer.root / ".agents" / "skills" / "pushing" / "SKILL.md").is_file()
        assert (consumer.root / ".github" / "actionlint.yaml").is_file()
        actionlint = (consumer.root / ".github" / "actionlint.yaml").read_text(encoding="utf-8")
        assert "invalid activity type" in actionlint
        assert "events-that-trigger-workflows#issue" in actionlint
        reviewing = (consumer.root / ".agents" / "skills" / "reviewing" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "`hdsh scope --base" in reviewing
        assert "uv run hdsh" not in reviewing
        assert "uv run hdsh" not in (consumer.root / "docs" / "AGENTS.md").read_text("utf-8")
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
        transplanted = (consumer.root / ".agents" / "rfcs" / "README.md").read_text(
            encoding="utf-8"
        )
        assert "src/hdsh/rfc/format.py" not in transplanted
        assert "https://github.com/jukanntenn/harness-deepseek-harness/blob/" not in transplanted
        assert "`hdsh rfc verify`" in transplanted
        moved = (
            consumer.root
            / ".agents"
            / "rfcs"
            / "implemented"
            / "process"
            / "2026-09-07-local-git-workflow.md"
        ).read_text(encoding="utf-8")
        assert "src/hdsh/scope.py" not in moved
        assert "`hdsh scope`" in moved
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

    def test_a_pre_existing_english_document_defers_its_whole_pair(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (consumer.root / "docs").mkdir(exist_ok=True)
        (consumer.root / "docs" / "development.md").write_text(
            "# Development\n\nReal consumer content.\n", encoding="utf-8"
        )
        commit_all(consumer)
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert (
            "docs/development.md: a pre-existing document was left untouched together "
            "with its counterpart and its pair record" in output
        )
        assert not (consumer.root / "docs" / "development.zh.md").exists()
        assert not (consumer.root / "docs" / "development.i18n.yaml").exists()
        assert "recorded 12 pair(s)" in output
        assert "1 still need a Chinese counterpart and a record" in output
        manifest = json.loads(
            (consumer.root / ".hdsh" / "adopt.manifest.json").read_text(encoding="utf-8")
        )
        assert "docs/development.md" not in manifest["editable"]
        assert "docs/development.zh.md" not in manifest["editable"]

    def test_a_pre_existing_chinese_document_defers_its_whole_pair(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (consumer.root / "docs").mkdir(exist_ok=True)
        (consumer.root / "docs" / "architecture.zh.md").write_text(
            "# 架构\n\n真实内容。\n", encoding="utf-8"
        )
        commit_all(consumer)
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert (
            "docs/architecture.md: a pre-existing document was left untouched together "
            "with its counterpart and its pair record" in output
        )
        assert not (consumer.root / "docs" / "architecture.md").exists()
        assert not (consumer.root / "docs" / "architecture.i18n.yaml").exists()
        assert "recorded 12 pair(s)" in output

    def test_an_adopt_installed_template_pair_still_records_on_reapply(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopted")
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert "recorded 13 pair(s)" in output
        assert (consumer.root / "docs" / "development.i18n.yaml").is_file()

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

    def test_a_malformed_consumer_pairing_manifest_skips_the_sizing_note(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (consumer.root / ".hdsh").mkdir()
        (consumer.root / ".hdsh" / "pairing.manifest.json").write_text("{ bad", encoding="utf-8")
        commit_all(consumer, "malformed manifest")
        assert apply_cli(*adopt_arguments()) == 1
        captured = capsys.readouterr()
        assert "pairing corpus after apply:" not in captured.out
        assert "recording .agents/rfcs/README.md failed" in captured.err

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
        target = consumer.root / ".agents" / "skills" / "merging-stacked-prs" / "SKILL.md"
        target.write_text("# locally edited\n", encoding="utf-8")
        commit_all(consumer, "local edit")
        assert apply_cli(*adopt_arguments()) == 1
        assert ".agents/skills/merging-stacked-prs/SKILL.md" in capsys.readouterr().err
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
        assert "AGENTS.md: an existing standing-orders file was left untouched" in (
            capsys.readouterr().out
        )
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert "AGENTS.md: an existing standing-orders file was left untouched" in output
        assert (consumer.root / "AGENTS.md").read_text(encoding="utf-8") == "# ours\n"
        manifest = json.loads(
            (consumer.root / ".hdsh" / "adopt.manifest.json").read_text(encoding="utf-8")
        )
        assert "AGENTS.md" not in manifest["files"]
        assert manifest["pendingMerges"] == ["AGENTS.md"]


class TestConsumerConfigOwnership:
    def test_consumer_config_files_are_never_pinned_or_refused(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pairing_manifest = (
            json.dumps({"excluded": [".zcode/"], "generated": [], "public_blob_root": ""}, indent=2)
            + "\n"
        )
        (consumer.root / ".hdsh").mkdir()
        (consumer.root / ".hdsh" / "pairing.manifest.json").write_text(
            pairing_manifest, encoding="utf-8"
        )
        git("add", "-A", cwd=consumer.root)
        git("commit", "-qm", "consumer manifest", cwd=consumer.root)
        assert apply_cli(*adopt_arguments()) == 0
        assert (consumer.root / ".hdsh" / "pairing.manifest.json").read_text(
            encoding="utf-8"
        ) == pairing_manifest
        manifest = json.loads(
            (consumer.root / ".hdsh" / "adopt.manifest.json").read_text(encoding="utf-8")
        )
        assert ".hdsh/pairing.manifest.json" not in manifest["files"]
        assert ".hdsh/docs.manifest.json" not in manifest["files"]
        assert ".github/issue-management/config.json" not in manifest["files"]
        assert ".hdsh/pairing.manifest.json" in manifest["consumerConfig"]
        wire_ci_gates(consumer)
        capsys.readouterr()
        assert verify_cli() == 1  # placeholders remain, but no drift
        error = capsys.readouterr().err
        assert "0 drift item(s)" in error

    def test_existing_config_json_binds_its_values(self, consumer: Repo) -> None:
        config = _consumer_config(
            project_number=9, title="Renamed Board", actor="other-bot", zone="Asia/Tokyo"
        )
        target = consumer.root / ".github" / "issue-management" / "config.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        git("add", "-A", cwd=consumer.root)
        git("commit", "-qm", "hand-authored config", cwd=consumer.root)
        arguments = adopt_arguments(
            "--project-number",
            "9",
            "--project-title",
            "Renamed Board",
            "--lifecycle-actor",
            "other-bot",
            "--time-zone",
            "Asia/Tokyo",
        )
        assert apply_cli(*arguments) == 0
        assert json.loads(target.read_text(encoding="utf-8"))["projectNumber"] == 9
        rendered = (consumer.root / ".github" / "workflows" / "issue-policy.yml").read_text(
            encoding="utf-8"
        )
        assert "secrets.HDSH_ISSUE_PROJECT_TOKEN" in rendered

    def test_conflicting_flag_against_existing_config_json_blocks(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = consumer.root / ".github" / "issue-management" / "config.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(_consumer_config(), indent=2) + "\n", encoding="utf-8")
        git("add", "-A", cwd=consumer.root)
        git("commit", "-qm", "hand-authored config", cwd=consumer.root)
        assert plan_cli(*adopt_arguments("--project-number", "4")) == 1
        assert "contradicts the existing config.json projectNumber value '3'" in (
            capsys.readouterr().err
        )

    def test_malformed_existing_config_json_blocks(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = consumer.root / ".github" / "issue-management" / "config.json"
        target.parent.mkdir(parents=True)
        target.write_text("{ broken\n", encoding="utf-8")
        assert plan_cli(*adopt_arguments()) == 1
        assert "malformed" in capsys.readouterr().err

    def test_existing_config_json_with_nonstandard_statuses_blocks(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _consumer_config()
        config["statuses"] = ["Inbox", "In progress", "In review", "Done"]
        target = consumer.root / ".github" / "issue-management" / "config.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        git("add", "-A", cwd=consumer.root)
        git("commit", "-qm", "hand-authored config", cwd=consumer.root)
        assert plan_cli(*adopt_arguments()) == 1
        assert "standard set" in capsys.readouterr().err

    def test_verify_reports_consumer_config_structure_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        (consumer.root / ".hdsh" / "pairing.manifest.json").write_text(
            "{ broken\n", encoding="utf-8"
        )
        capsys.readouterr()
        assert verify_cli() == 1
        assert ".hdsh/pairing.manifest.json: invalid" in capsys.readouterr().err

    def test_verify_reports_config_json_repository_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        target = consumer.root / ".github" / "issue-management" / "config.json"
        config = json.loads(target.read_text(encoding="utf-8"))
        config["repository"] = "renamed-repo"
        target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        capsys.readouterr()
        assert verify_cli() == 1
        assert "does not match the origin remote" in capsys.readouterr().err

    def test_verify_reports_invalid_config_json_as_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        target = consumer.root / ".github" / "issue-management" / "config.json"
        target.write_text('{"owner": "x"}\n', encoding="utf-8")
        capsys.readouterr()
        assert verify_cli() == 1
        assert ".github/issue-management/config.json: invalid" in capsys.readouterr().err

    def test_verify_reports_status_set_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        target = consumer.root / ".github" / "issue-management" / "config.json"
        config = json.loads(target.read_text(encoding="utf-8"))
        config["statuses"] = ["Inbox", "In progress", "In review", "Done"]
        target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        capsys.readouterr()
        assert verify_cli() == 1
        assert "statuses differ from the standard set" in capsys.readouterr().err

    def test_verify_reports_invalid_docs_manifest_as_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        (consumer.root / ".hdsh" / "docs.manifest.json").write_text("{ broken\n", encoding="utf-8")
        capsys.readouterr()
        assert verify_cli() == 1
        assert ".hdsh/docs.manifest.json: invalid" in capsys.readouterr().err

    def test_verify_reports_missing_consumer_config_as_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        (consumer.root / ".hdsh" / "docs.manifest.json").unlink()
        capsys.readouterr()
        assert verify_cli() == 1
        assert ".hdsh/docs.manifest.json: missing" in capsys.readouterr().err


def _consumer_config(
    project_number: int = 3,
    title: str = "Consumer Issues",
    actor: str = "consumer-bot",
    zone: str = "Asia/Shanghai",
) -> dict[str, object]:
    return {
        "owner": "consumer-org",
        "accountType": "user",
        "repository": "consumer-repo",
        "projectNumber": project_number,
        "projectTitle": title,
        "lifecycleActor": actor,
        "priorityField": "Priority",
        "startDateField": "Start date",
        "projectTimeZone": zone,
        "allowUnassignedOwner": False,
        "statuses": ["Inbox", "Backlog", "Ready", "In progress", "In review", "Done", "No action"],
    }


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
        consumer.write(".agents/skills/merging-stacked-prs/SKILL.md", "# conflicting skill\n")
        assert plan_cli(*adopt_arguments()) == 1
        error = capsys.readouterr().err
        assert ".agents/skills/merging-stacked-prs/SKILL.md" in error
        assert "adopt never overwrites consumer-owned files" in error

    def test_refuses_a_malformed_previous_manifest(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write(".hdsh/adopt.manifest.json", "[]")
        assert plan_cli(*adopt_arguments()) == 1
        assert "previous adopt manifest is malformed" in capsys.readouterr().err

    def test_invalid_optional_flags_still_block(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plan_cli(*adopt_arguments("--account-type", "enterprise")) == 1
        assert "is not one of ['user', 'organization']" in capsys.readouterr().err
        assert plan_cli(*adopt_arguments("--time-zone", "Mars/Olympus")) == 1
        assert "is not a known IANA zone" in capsys.readouterr().err

    def test_absent_derivable_flags_without_config_block_with_named_guidance(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plan_cli("--project-number", "3", "--project-title", "Consumer Issues") == 1
        error = capsys.readouterr().err
        assert "--hdsh-ref: the parameter could not be derived" in error
        assert "--account-type: the parameter could not be derived" in error

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
        wire_ci_gates(consumer)
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
        (consumer.root / ".agents" / "rfcs" / "README.md").unlink()
        capsys.readouterr()
        assert verify_cli() == 1
        error = capsys.readouterr().err
        assert "docs/AGENTS.md: content differs" in error
        assert ".agents/skills/pushing/SKILL.md: missing" in error
        assert ".agents/rfcs/README.md: missing" in error
        assert "docs/architecture.md: missing" in error

    def test_pending_merge_names_the_missing_harness_anchors(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (consumer.root / "AGENTS.md").write_text("# ours\n", encoding="utf-8")
        git("add", "-A", cwd=consumer.root)
        git("commit", "-qm", "standing orders", cwd=consumer.root)
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        capsys.readouterr()
        assert verify_cli() == 1
        output = capsys.readouterr().out
        assert "AGENTS.md: manual merge pending" in output
        assert "#run-relevant-checks-locally" in output
        assert "#conventions" in output

    def test_pending_merge_clears_once_the_anchors_resolve(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (consumer.root / "AGENTS.md").write_text("# ours\n", encoding="utf-8")
        git("add", "-A", cwd=consumer.root)
        git("commit", "-qm", "standing orders", cwd=consumer.root)
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        for path in consumer.root.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if "TODO(adopt):" in text and path.name != "AGENTS.md":
                path.write_text(text.replace("TODO(adopt): ", ""), encoding="utf-8")
        (consumer.root / "AGENTS.md").write_text(
            "# ours\n\n## Conventions\n\nOurs.\n\n## Run relevant checks locally\n\nOurs.\n",
            encoding="utf-8",
        )
        wire_ci_gates(consumer)
        capsys.readouterr()
        assert verify_cli() == 0, capsys.readouterr().out
        assert "manual merge pending" not in capsys.readouterr().out

    def test_pending_merge_file_deleted_becomes_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (consumer.root / "AGENTS.md").write_text("# ours\n", encoding="utf-8")
        git("add", "-A", cwd=consumer.root)
        git("commit", "-qm", "standing orders", cwd=consumer.root)
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        (consumer.root / "AGENTS.md").unlink()
        capsys.readouterr()
        assert verify_cli() == 1
        assert "AGENTS.md: missing" in capsys.readouterr().err


class TestWorkflowGroupDrift:
    def _write_workflow(self, consumer: Repo, run_line: str, name: str = "lint.yml") -> None:
        workflow = consumer.root / ".github" / "workflows" / name
        workflow.write_text(
            "on: [push]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - run: {run_line}\n",
            encoding="utf-8",
        )
        commit_all(consumer, "add CI")

    def test_a_group_filter_without_hdsh_is_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        self._write_workflow(consumer, "prek run --all-files --group format --group lint")
        capsys.readouterr()
        assert verify_cli() == 1
        error = capsys.readouterr().err
        assert "lint.yml:6: prek run filters --group without 'hdsh'" in error
        assert "add --group hdsh" in error

    def test_yaml_workflows_are_scanned_too(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        self._write_workflow(consumer, "prek run --all-files --group format", name="check.yaml")
        capsys.readouterr()
        assert verify_cli() == 1
        assert "check.yaml:6: prek run filters --group without 'hdsh'" in (capsys.readouterr().err)

    def test_including_the_hdsh_group_clears_the_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        self._write_workflow(consumer, "prek run --all-files --group format --group hdsh")
        capsys.readouterr()
        assert verify_cli() == 1  # placeholders remain
        assert "--group without 'hdsh'" not in capsys.readouterr().err

    def test_unfiltered_and_commented_commands_are_ignored(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        self._write_workflow(
            consumer, "prek run --all-files  # prek run --group format stays a comment"
        )
        capsys.readouterr()
        assert verify_cli() == 1  # placeholders remain
        assert "--group without 'hdsh'" not in capsys.readouterr().err

    def test_no_workflows_directory_is_not_drift(self, tmp_path: Path) -> None:
        assert adopt_commands._workflow_group_drift(str(tmp_path)) == []


class TestCiGateDrift:
    def test_a_freshly_adopted_ci_without_any_gate_is_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        capsys.readouterr()
        assert verify_cli() == 1
        error = capsys.readouterr().err
        assert "CI runs no hdsh gate" in error
        assert "prek run --all-files" in error

    def test_a_pinned_hdsh_install_counts_as_wiring(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        (consumer.root / ".github" / "workflows" / "gates.yml").write_text(
            "on: [push]\njobs:\n  gates:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: uv tool install hdsh && hdsh pairing verify\n",
            encoding="utf-8",
        )
        capsys.readouterr()
        assert verify_cli() == 1  # placeholders remain
        assert "CI runs no hdsh gate" not in capsys.readouterr().err

    def test_policy_workflow_input_names_do_not_count_as_gates(self, tmp_path: Path) -> None:
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "issue-policy.yml").write_text(
            "on: [issues]\njobs:\n  policy:\n    steps:\n      - uses: o/r/a@v1\n"
            "        with:\n          hdsh-ref: v0.1.0\n",
            encoding="utf-8",
        )
        drift = adopt_commands._ci_gate_drift(str(tmp_path))
        assert len(drift) == 1
        assert "CI runs no hdsh gate" in drift[0]

    def test_a_repository_without_workflows_is_not_drift(self, tmp_path: Path) -> None:
        assert adopt_commands._ci_gate_drift(str(tmp_path)) == []

    def test_a_repository_with_no_workflows_gets_an_informational_line(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        for workflow in (consumer.root / ".github" / "workflows").iterdir():
            workflow.unlink()
        capsys.readouterr()
        assert verify_cli() == 1
        assert "no CI workflows found; the gates run only locally" in capsys.readouterr().out


class TestPairingSizingNote:
    def test_without_any_manifest_there_is_no_note(self, tmp_path: Path) -> None:
        assert adopt_commands._pairing_sizing_note(str(tmp_path), [], []) is None

    def test_a_hard_wrapped_pre_existing_corpus_is_sized_before_apply(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        readme = consumer.root / "README.md"
        readme.write_text(
            "# consumer\n\nEnglish | [中文](README.zh.md)\n\nA hard-wrapped\nparagraph.\n",
            encoding="utf-8",
        )
        commit_all(consumer, "wrap legacy prose")
        assert plan_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert (
            "wrap gate after apply: 1 hard-wrapped paragraph(s) across 1 pre-existing "
            "file(s) must reflow to one physical line per paragraph" in output
        )

    def test_a_reflowed_corpus_gets_no_wrap_note(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plan_cli(*adopt_arguments()) == 0
        assert "wrap gate after apply" not in capsys.readouterr().out

    def test_without_any_docs_manifest_there_is_no_note(self, tmp_path: Path) -> None:
        assert adopt_commands._wrap_sizing_note(str(tmp_path), []) is None

    def test_a_malformed_pre_existing_docs_manifest_yields_no_note(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (consumer.root / ".hdsh").mkdir()
        (consumer.root / ".hdsh" / "docs.manifest.json").write_text("{ nope", encoding="utf-8")
        commit_all(consumer, "broken docs manifest")
        assert plan_cli(*adopt_arguments()) == 0
        assert "wrap gate after apply" not in capsys.readouterr().out


class TestInvocationDrift:
    def test_a_hand_reintroduced_source_invocation_is_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        target = consumer.root / ".agents" / "skills" / "reviewing" / "SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8").replace("`hdsh scope", "`uv run hdsh scope"),
            encoding="utf-8",
        )
        commit_all(consumer, "hand edit")
        capsys.readouterr()
        assert verify_cli() == 1
        error = capsys.readouterr().err
        assert "reviewing/SKILL.md:8: carries `uv run hdsh`" in error
        assert "rerun hdsh adopt apply" in error


class TestPrekBlockUnits:
    def test_managed_block_pins_the_ref_and_every_hook(self) -> None:
        block = _managed_prek_block("v9.9.9")
        assert 'rev = "v9.9.9"' in block
        assert 'groups = ["hdsh"]' in block
        for hook in (
            "hdsh-pairing-verify",
            "hdsh-rfc-verify",
            "hdsh-rfc-archive",
            "hdsh-docs-wrap",
            "hdsh-docs-links",
            "hdsh-docs-budgets",
            "hdsh-adopt-verify",
        ):
            assert f'{{ id = "{hook}", groups = ["hdsh"] }}' in block

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


class TestWizardIntegration:
    def test_every_explicit_flag_run_stays_offline_with_echoes(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plan_cli(*adopt_arguments()) == 0
        assert "resolved --hdsh-ref v0.1.0 (flag)" in capsys.readouterr().out

    def test_apply_records_the_project_anchor(self, consumer: Repo) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        manifest = json.loads(
            (consumer.root / ".hdsh" / "adopt.manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["projectAnchor"] == 3

    def test_a_moved_board_is_an_anchor_conflict_naming_the_rebind(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        target = consumer.root / ".github" / "issue-management" / "config.json"
        config = json.loads(target.read_text(encoding="utf-8"))
        config["projectNumber"] = 9
        target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        capsys.readouterr()
        assert verify_cli() == 1
        error = capsys.readouterr().err
        assert "no longer matches the bound board 3" in error
        assert "rerun hdsh adopt apply with the new number to rebind" in error

    def test_a_matching_board_number_does_not_conflict(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        target = consumer.root / ".github" / "issue-management" / "config.json"
        config = json.loads(target.read_text(encoding="utf-8"))
        config["lifecycleActor"] = "renamed-bot"
        target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        capsys.readouterr()
        assert verify_cli() == 1  # placeholders remain
        assert "no longer matches the bound board" not in capsys.readouterr().err


class TestSlotTemplates:
    def test_fresh_apply_installs_guidance_and_verify_demands_fills(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        skill = consumer.root / ".agents" / "skills" / "pushing" / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        assert "<!-- hdsh:slot focused-tests -->" in text
        assert "TODO(adopt):" in text
        manifest = json.loads(
            (consumer.root / ".hdsh" / "adopt.manifest.json").read_text(encoding="utf-8")
        )
        assert ".agents/skills/pushing/SKILL.md" in manifest["slotTemplates"]
        assert manifest["slotGuidance"][".agents/skills/pushing/SKILL.md"]["focused-tests"]
        capsys.readouterr()
        assert verify_cli() == 1
        output = capsys.readouterr().out
        assert ".agents/skills/pushing/SKILL.md:" in output
        assert "TODO(adopt):" in output

    def test_reapply_preserves_filled_slot_values(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        skill = consumer.root / ".agents" / "skills" / "archiving-rfcs" / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        guidance = (
            "TODO(adopt): Name this repository's focused tests for the archive path "
            "(hdsh's own: `uv run pytest tests/rfc/test_archive.py`)."
        )
        filled = text.replace(guidance, "`cargo test --test archive`")
        skill.write_text(filled, encoding="utf-8")
        commit_all(consumer, "fill the archive-tests slot")
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert "1 consumer slot value(s) preserved" in output
        assert "`cargo test --test archive`" in skill.read_text(encoding="utf-8")

    def test_reapply_resets_a_filled_slot_whose_guidance_changed(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        skill = consumer.root / ".agents" / "skills" / "archiving-rfcs" / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        guidance = (
            "TODO(adopt): Name this repository's focused tests for the archive path "
            "(hdsh's own: `uv run pytest tests/rfc/test_archive.py`)."
        )
        filled = text.replace(guidance, "`cargo test --test archive`")
        skill.write_text(filled, encoding="utf-8")
        commit_all(consumer, "fill the slot")
        manifest_path = consumer.root / ".hdsh" / "adopt.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["slotGuidance"][".agents/skills/archiving-rfcs/SKILL.md"]["archive-tests"] = (
            "0" * 64
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        commit_all(consumer, "stale guidance baseline")
        assert apply_cli(*adopt_arguments()) == 0
        output = capsys.readouterr().out
        assert "upstream changed the archive-tests slot guidance" in output
        assert "TODO(adopt):" in skill.read_text(encoding="utf-8")

    def test_malformed_installed_slot_markers_block_reapplication(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        skill = consumer.root / ".agents" / "skills" / "reviewing" / "SKILL.md"
        text = skill.read_text(encoding="utf-8").replace("<!-- /hdsh:slot -->\n", "", 1)
        skill.write_text(text, encoding="utf-8")
        commit_all(consumer, "break the slot markers")
        assert apply_cli(*adopt_arguments()) == 1
        assert "slot text is malformed" in capsys.readouterr().err

    def test_consumer_edits_outside_slots_are_replaced_not_blocked(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        skill = consumer.root / ".agents" / "skills" / "pushing" / "SKILL.md"
        text = skill.read_text(encoding="utf-8").replace("# Pushing branches", "# locally retitled")
        skill.write_text(text, encoding="utf-8")
        commit_all(consumer, "local retitle")
        assert apply_cli(*adopt_arguments()) == 0
        assert "# Pushing branches" in skill.read_text(encoding="utf-8")

    def test_verify_reports_missing_slot_template_as_drift(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert apply_cli(*adopt_arguments()) == 0
        commit_all(consumer, "adopt hdsh")
        (consumer.root / ".agents" / "skills" / "reviewing" / "SKILL.md").unlink()
        capsys.readouterr()
        assert verify_cli() == 1
        assert ".agents/skills/reviewing/SKILL.md: missing" in capsys.readouterr().err

    def test_hook_mode_still_fails_on_a_malformed_manifest(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        consumer.write(".hdsh/adopt.manifest.json", "[]\n")
        commit_all(consumer, "malformed manifest")
        request = parse_command(adopt_commands.register, ["verify", "--hook"])
        capsys.readouterr()
        assert verify_main(request) == 1
        assert "must be a JSON object" in capsys.readouterr().err

    def test_hook_mode_is_a_no_op_without_a_manifest(
        self, consumer: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        request = parse_command(adopt_commands.register, ["verify", "--hook"])
        capsys.readouterr()
        assert verify_main(request) == 0
        assert "nothing to verify" in capsys.readouterr().out


class TestRequiredAnchorsUnits:
    def test_collects_fragments_targeting_the_destination(self, tmp_path: Path) -> None:
        (tmp_path / ".agents" / "skills" / "reviewing").mkdir(parents=True)
        (tmp_path / ".agents" / "skills" / "reviewing" / "SKILL.md").write_text(
            "See [checks](../../../AGENTS.md#run-relevant-checks-locally) and "
            "[rules](../../../AGENTS.md#conventions); also [bare](../../../AGENTS.md).\n",
            encoding="utf-8",
        )
        anchors = _required_anchors(
            str(tmp_path), "AGENTS.md", (".agents/skills/reviewing/SKILL.md",)
        )
        assert anchors == ("conventions", "run-relevant-checks-locally")

    def test_skips_fenced_examples_absolute_and_foreign_targets(self, tmp_path: Path) -> None:
        (tmp_path / ".agents" / "skills" / "reviewing").mkdir(parents=True)
        (tmp_path / ".agents" / "skills" / "reviewing" / "SKILL.md").write_text(
            "```markdown\n[example](../../../AGENTS.md#fenced)\n```\n"
            "[web](https://example.com/AGENTS.md#web) "
            "[root](/AGENTS.md#root) "
            "[here](#here) "
            "[else](../../../docs/other.md#else)\n",
            encoding="utf-8",
        )
        assert (
            _required_anchors(str(tmp_path), "AGENTS.md", (".agents/skills/reviewing/SKILL.md",))
            == ()
        )

    def test_missing_sources_contribute_nothing(self, tmp_path: Path) -> None:
        assert _required_anchors(str(tmp_path), "AGENTS.md", (".agents/skills/gone.md",)) == ()


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


class TestAdoptionDate:
    def test_the_date_follows_the_project_zone(self) -> None:
        instant = datetime.datetime(
            2026, 10, 3, 6, 14, tzinfo=datetime.timezone(datetime.timedelta(hours=8))
        )

        def frozen(tz: datetime.tzinfo) -> datetime.datetime:
            return instant.astimezone(tz)

        assert adopt_commands._adoption_date("Asia/Shanghai", now=frozen) == "2026-10-03"
        assert adopt_commands._adoption_date("America/New_York", now=frozen) == "2026-10-02"

    def test_an_unresolvable_zone_stays_computable_until_its_blocker_aborts(self) -> None:
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}",
            adopt_commands._adoption_date("Mars/Olympus", now=datetime.datetime.now),
        )
