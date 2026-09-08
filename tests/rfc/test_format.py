"""The RFC format gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import hdsh.rfc.format as format_module
from hdsh.rfc.format import main as format_main
from hdsh.rfc.format import run as run_rfc_format
from hdsh.rfc.tree import walk_notes
from tests.helpers import (
    VALID_IMPLEMENTED,
    VALID_PROPOSED,
    VALID_REJECTED,
    Repo,
    parse_command,
)


def verify_cli() -> int:
    """Run ``hdsh rfc verify`` with parsed arguments."""
    return format_main(parse_command(format_module.register, ["verify"]))


def write_rfc(repo: Repo, relative: str, content: str) -> None:
    repo.write(relative, content)
    repo.write(relative[: -len(".md")] + ".zh.md", content)


class TestStructure:
    def test_empty_unknown_lifecycle_folder_is_rejected(self, repo: Repo) -> None:
        (repo.root / ".agents/rfcs/draft").mkdir(parents=True)
        assert run_rfc_format(repo.root) == 1

    def test_unknown_lifecycle_folder_names_the_folder(self, repo: Repo) -> None:
        repo.write(".agents/rfcs/draft/2026-01-01-x.md", VALID_IMPLEMENTED)
        _, errors = walk_notes(repo.root)
        assert any("draft/" in error and "unknown lifecycle folder" in error for error in errors)

    def test_nested_class_depth_is_rejected(self, repo: Repo) -> None:
        write_rfc(
            repo, ".agents/rfcs/implemented/process/sub/2026-01-01-sample.md", VALID_IMPLEMENTED
        )
        _, errors = walk_notes(repo.root)
        assert any("got depth 4" in error for error in errors)
        assert run_rfc_format(repo.root) == 1

    def test_tree_root_files_are_outside_the_walk(self, repo: Repo) -> None:
        repo.write(".agents/rfcs/loose.md", VALID_IMPLEMENTED)
        repo.write(".agents/rfcs/README.md", "# index\n")
        repo.write(".agents/rfcs/AGENTS.md", "# agents\n")
        assert walk_notes(repo.root) == ([], [])
        assert run_rfc_format(repo.root) == 0

    def test_lifecycle_root_allowlist_is_agents_and_claude(self, repo: Repo) -> None:
        repo.write(".agents/rfcs/implemented/AGENTS.md", "# agents\n")
        repo.write(".agents/rfcs/implemented/CLAUDE.md", "# claude\n")
        assert run_rfc_format(repo.root) == 0

    def test_lifecycle_root_readme_is_rejected(self, repo: Repo) -> None:
        repo.write(".agents/rfcs/implemented/README.md", "# readme\n")
        assert run_rfc_format(repo.root) == 1

    def test_class_folder_readme_is_rejected(self, repo: Repo) -> None:
        repo.write(".agents/rfcs/implemented/process/README.md", "# readme\n")
        assert run_rfc_format(repo.root) == 1

    def test_bad_path_is_rejected(self, repo: Repo) -> None:
        write_rfc(repo, ".agents/rfcs/implemented/process/notadate.md", VALID_IMPLEMENTED)
        assert run_rfc_format(repo.root) == 1

    def test_unknown_class_is_rejected(self, repo: Repo) -> None:
        write_rfc(repo, ".agents/rfcs/implemented/other/2026-01-01-sample.md", VALID_IMPLEMENTED)
        assert run_rfc_format(repo.root) == 1

    def test_archived_tree_is_owned_by_the_archive_gate(self, repo: Repo) -> None:
        write_rfc(repo, ".agents/rfcs/archived/process/2026-01-01-sample.md", VALID_IMPLEMENTED)
        assert run_rfc_format(repo.root) == 0

    def test_walk_skips_allowlist_and_chinese_sides(self, repo: Repo) -> None:
        repo.write(".agents/rfcs/implemented/AGENTS.md", "# agents\n")
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-x.md", VALID_IMPLEMENTED)
        notes, errors = walk_notes(repo.root)
        assert errors == []
        assert [note.name for note in notes] == ["2026-01-01-x.md"]


class TestContent:
    def test_valid_rfcs_pass(self, repo: Repo) -> None:
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", VALID_IMPLEMENTED)
        write_rfc(repo, ".agents/rfcs/proposed/process/2026-01-02-sample.md", VALID_PROPOSED)
        write_rfc(repo, ".agents/rfcs/rejected/process/2026-01-03-sample.md", VALID_REJECTED)
        assert run_rfc_format(repo.root) == 0

    def test_rejected_keeps_only_the_proposal_skeleton(self, repo: Repo) -> None:
        stripped = VALID_REJECTED.replace(
            "## Acceptance criteria\n\nThe gate passes.\n\n", ""
        ).replace("## Risks\n\nThe thing might be wrong.\n", "")
        body = f"{stripped.rstrip()}\n"
        write_rfc(repo, ".agents/rfcs/rejected/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 0

    def test_first_section_must_be_problem(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace(
            "## Problem\n\nSomething needed a decision.\n\n## Decision\n\nWe decided the thing.",
            "## Decision\n\nWe decided the thing.\n\n## Problem\n\nSomething needed a decision.",
        )
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_a_file_without_any_section_is_rejected(self, repo: Repo) -> None:
        write_rfc(
            repo,
            ".agents/rfcs/implemented/process/2026-01-01-sample.md",
            VALID_IMPLEMENTED.replace("## ", "#### "),
        )
        assert run_rfc_format(repo.root) == 1

    def test_line_four_must_be_blank(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace(
            "Status: implemented\n\nEnglish", "Status: implemented\nX\nEnglish"
        )
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_a_file_ending_at_the_status_line_is_rejected(self, repo: Repo) -> None:
        write_rfc(
            repo,
            ".agents/rfcs/implemented/process/2026-01-01-sample.md",
            "# RFC: Sample decision\n\nStatus: implemented",
        )
        assert run_rfc_format(repo.root) == 1

    def test_fenced_format_tokens_are_not_structure(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace(
            "## Consequences\n",
            "## Consequences\n\n```markdown\n## Plan\n\nStatus: proposed\n```\n",
        )
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 0

    def test_a_second_status_line_is_rejected(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace("## Problem", "Status: proposed\n\n## Problem")
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_a_duplicated_status_line_is_rejected(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace("## Problem", "Status: implemented\n\n## Problem")
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_spec_language_matches_heading_prefixes(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace(
            "## Consequences", "## Proposal sketch\n\nNope.\n\n## Consequences"
        )
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_spec_language_matches_any_case(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace(
            "## Consequences", "## PROPOSAL\n\nNope.\n\n## Consequences"
        )
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_spec_language_requires_a_word_boundary(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace(
            "## Consequences", "## Planned work\n\nIt shipped.\n\n## Consequences"
        )
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 0

    def test_spec_language_is_rejected_in_implemented(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace("## Decision", "## Decision\n\nNow.\n\n## Plan")
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_title_requires_a_nonspace_title(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace("# RFC: Sample decision", "# RFC:  Sample decision")
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_trailing_spaces_on_a_heading_are_tolerated(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace("## Problem\n", "## Problem   \n")
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 0

    def test_header_block_is_enforced(self, repo: Repo) -> None:
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", "# Not an RFC\n")
        assert run_rfc_format(repo.root) == 1

    def test_status_must_match_folder(self, repo: Repo) -> None:
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", VALID_PROPOSED)
        assert run_rfc_format(repo.root) == 1

    def test_implemented_status_in_proposed_folder(self, repo: Repo) -> None:
        repo.write(".agents/rfcs/proposed/process/2026-01-01-x.md", VALID_IMPLEMENTED)
        repo.write(".agents/rfcs/proposed/process/2026-01-01-x.zh.md", VALID_IMPLEMENTED)
        assert run_rfc_format(repo.root) == 1

    def test_rejected_status_in_implemented_folder(self, repo: Repo) -> None:
        repo.write(".agents/rfcs/implemented/process/2026-01-01-x.md", VALID_REJECTED)
        repo.write(".agents/rfcs/implemented/process/2026-01-01-x.zh.md", VALID_REJECTED)
        assert run_rfc_format(repo.root) == 1

    def test_missing_sections_are_rejected(self, repo: Repo) -> None:
        write_rfc(
            repo,
            ".agents/rfcs/implemented/process/2026-01-01-sample.md",
            VALID_IMPLEMENTED.replace("## Decision", "## Something"),
        )
        assert run_rfc_format(repo.root) == 1

    def test_missing_alternatives_is_rejected(self, repo: Repo) -> None:
        body = VALID_IMPLEMENTED.replace(
            "## Alternatives considered\n\n**Do nothing.** It left the problem unsolved.\n\n", ""
        )
        write_rfc(repo, ".agents/rfcs/implemented/process/2026-01-01-sample.md", body)
        assert run_rfc_format(repo.root) == 1

    def test_trailing_newline_is_enforced(self, repo: Repo) -> None:
        write_rfc(
            repo,
            ".agents/rfcs/implemented/process/2026-01-01-sample.md",
            VALID_IMPLEMENTED.rstrip("\n") + "\n\n",
        )
        assert run_rfc_format(repo.root) == 1

    def test_no_rfc_directory_is_green(self, tmp_path: Path) -> None:
        assert run_rfc_format(tmp_path) == 0


class TestCli:
    def test_main_green(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(repo.root)
        assert verify_cli() == 0
        assert "all RFCs well formed" in capsys.readouterr().out

    def test_main_exits_two_outside_repository(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 128, "", "not a repository")

        monkeypatch.setattr(subprocess, "run", failing_run)
        assert verify_cli() == 2

    def test_main_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("boom")

        monkeypatch.setattr("hdsh.rfc.format.subprocess.run", raising_run)
        assert verify_cli() == 2


def test_extra_arguments_are_rejected() -> None:
    with pytest.raises(ValueError, match="unrecognized arguments"):
        parse_command(format_module.register, ["verify", "--nope"])
