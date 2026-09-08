"""The markdown hard-wrap gate."""

from __future__ import annotations

import pytest

import hdsh.docs.wrap as wrap_module
from hdsh.docs.config import DocsConfigError
from hdsh.docs.wrap import main, run
from tests.helpers import Repo, parse_command

WRAP_SCOPE = {"include": ["docs/**/*.md"], "exclude": []}


def write_manifest(repo: Repo, **sections: object) -> None:
    """Write a docs manifest into the disposable repository."""
    import json

    repo.write(".hdsh/docs.manifest.json", json.dumps(sections, indent=2) + "\n")


def wrap_cli() -> int:
    """Run ``hdsh docs wrap`` with parsed arguments."""
    return main(parse_command(wrap_module.register, ["wrap"]))


class TestWrapGate:
    def test_green_corpus_reports_file_count(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_manifest(repo, markdownWrap=WRAP_SCOPE)
        repo.write("docs/a.md", "# A\n\none line.\n")
        assert run(repo.root) == 0
        assert "1 file(s) checked, no hard-wrapped prose paragraphs" in capsys.readouterr().out

    def test_violations_report_file_line_and_snippet(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_manifest(repo, markdownWrap=WRAP_SCOPE)
        long_line = "x" * 100
        repo.write("docs/a.md", f"# A\n\n{long_line}\nwrapped\n")
        repo.write("docs/b.md", "# B\n\nshort first line\nwrapped too\n")
        assert run(repo.root) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert f"docs/a.md:3  {'x' * 80}…" in captured.err
        assert "docs/b.md:3  short first line" in captured.err

    def test_missing_section_refuses_to_run(self, repo: Repo) -> None:
        write_manifest(repo, docBudgets={"AGENTS.md": 5})
        with pytest.raises(DocsConfigError, match="markdownWrap section is required"):
            run(repo.root)

    def test_main_returns_zero_on_green_corpus(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_manifest(repo, markdownWrap=WRAP_SCOPE)
        repo.write("docs/a.md", "# A\n\none line.\n")
        monkeypatch.chdir(repo.root)
        assert wrap_cli() == 0

    def test_main_exits_two_on_config_error(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo.write(".hdsh/docs.manifest.json", "{}\n")
        monkeypatch.chdir(repo.root)
        assert wrap_cli() == 2
        assert "markdownWrap" in capsys.readouterr().err

    def test_extra_arguments_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse_command(wrap_module.register, ["wrap", "--nope"])
