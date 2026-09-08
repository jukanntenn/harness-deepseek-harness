"""The doc word-budget gate."""

from __future__ import annotations

import json

import pytest

import hdsh.docs.budgets as budgets_module
from hdsh.docs.budgets import count_words, main, run
from hdsh.docs.config import DocsConfigError
from tests.helpers import Repo, parse_command


def write_manifest(repo: Repo, **sections: object) -> None:
    """Write a docs manifest into the disposable repository."""
    repo.write(".hdsh/docs.manifest.json", json.dumps(sections, indent=2) + "\n")


def budgets_cli(*args: str) -> int:
    """Run ``hdsh docs budgets`` with parsed arguments."""
    return main(parse_command(budgets_module.register, ["budgets", *args]))


class TestBudgetsGate:
    def test_count_words_matches_wc_w(self) -> None:
        assert count_words("") == 0
        assert count_words("  one  two\tthree\n") == 3

    def test_within_ceiling_passes(self, repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
        write_manifest(repo, docBudgets={"docs/a.md": 5})
        repo.write("docs/a.md", "one two three\n")
        assert run(repo.root) == 0
        assert "1 budgeted docs within ceiling" in capsys.readouterr().out

    def test_over_ceiling_fails(self, repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
        write_manifest(repo, docBudgets={"docs/a.md": 2})
        repo.write("docs/a.md", "one two three\n")
        assert run(repo.root) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "docs/a.md: 3 words exceeds the 2-word ceiling" in captured.err
        assert "relocate or condense" in captured.err

    def test_missing_budgeted_file_fails(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_manifest(repo, docBudgets={"docs/gone.md": 5})
        assert run(repo.root) == 1
        captured = capsys.readouterr()
        assert "docs/gone.md: budgeted file does not exist" in captured.err
        assert "update .hdsh/docs.manifest.json in the same change" in captured.err

    def test_list_reports_usage_without_failing(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_manifest(repo, docBudgets={"docs/a.md": 5, "docs/gone.md": 7})
        repo.write("docs/a.md", "one two\n")
        assert run(repo.root, list_only=True) == 0
        assert capsys.readouterr().out.splitlines() == [
            "ok         2 / 5      docs/a.md",
            "MISS       — / 7      docs/gone.md",
        ]

    def test_missing_section_refuses_to_run(self, repo: Repo) -> None:
        write_manifest(repo, markdownWrap={"include": ["docs/**/*.md"], "exclude": []})
        with pytest.raises(DocsConfigError, match="docBudgets section is required"):
            run(repo.root)

    def test_list_flag_parses_and_unknown_flags_fail(self) -> None:
        parsed = parse_command(budgets_module.register, ["budgets", "--list"])
        assert parsed.list is True
        assert parse_command(budgets_module.register, ["budgets"]).list is False
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse_command(budgets_module.register, ["budgets", "--verbose"])

    def test_main_returns_zero_on_green_corpus(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_manifest(repo, docBudgets={"docs/a.md": 5})
        repo.write("docs/a.md", "one two\n")
        monkeypatch.chdir(repo.root)
        assert budgets_cli() == 0

    def test_main_exits_two_on_config_error(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo.write(".hdsh/docs.manifest.json", "{}\n")
        monkeypatch.chdir(repo.root)
        assert budgets_cli() == 2
