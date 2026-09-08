"""Corpus discovery and repository-root location for the docs gates."""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from hdsh.docs.config import CorpusScope
from hdsh.docs.corpus import discover_corpus_files, find_repository_root
from tests.helpers import Repo


class TestCorpusDiscovery:
    def test_include_order_excludes_and_dedupe(self, repo: Repo) -> None:
        repo.write("docs/a.md", "# A\n")
        repo.write("docs/sub/b.md", "# B\n")
        repo.write("extra/x.md", "# X\n")
        files = discover_corpus_files(
            repo.root, CorpusScope(include=("docs/**/*.md", "extra/*.md"), exclude=("docs/sub/**",))
        )
        assert [file.path for file in files] == ["docs/a.md", "extra/x.md"]

    def test_directory_matches_are_skipped(self, repo: Repo) -> None:
        repo.write("docs/a.md", "# A\n")
        repo.write("docs/sub/b.md", "# B\n")
        files = discover_corpus_files(repo.root, CorpusScope(include=("docs/*",), exclude=()))
        assert [file.path for file in files] == ["docs/a.md"]

    def test_symlinked_files_are_deduped(self, repo: Repo) -> None:
        target = repo.write("docs/a.md", "# A\n")
        (repo.root / "docs" / "b.md").symlink_to(target)
        files = discover_corpus_files(repo.root, CorpusScope(include=("docs/*.md",), exclude=()))
        assert [file.path for file in files] == ["docs/a.md"]


class TestFindRepositoryRoot:
    def test_finds_repository_root(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo.root / ".hdsh")
        assert find_repository_root("tool") == repo.root

    def test_outside_repository_exits_two(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as excinfo:
            find_repository_root("tool")
        assert excinfo.value.code == 2

    def test_unavailable_git_exits_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise OSError("no git")

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(SystemExit) as excinfo:
            find_repository_root("tool")
        assert excinfo.value.code == 2
