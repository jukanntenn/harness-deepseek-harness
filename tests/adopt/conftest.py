"""Shared fixtures for the adopt-domain tests: disposable consumer repositories."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import Repo, git


@pytest.fixture
def consumer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """One clean consumer repository with a github.com origin, cwd inside it."""
    root = tmp_path / "consumer"
    root.mkdir()
    git("init", "-q", cwd=root)
    git("config", "user.email", "t@t.t", cwd=root)
    git("config", "user.name", "t", cwd=root)
    git("remote", "add", "origin", "https://github.com/consumer-org/consumer-repo.git", cwd=root)
    (root / ".gitattributes").write_text("*.py text=auto\n", encoding="utf-8")
    readme = root / "README.md"
    readme.write_text("# consumer\n\nEnglish | [中文](README.zh.md)\n", encoding="utf-8")
    readme_zh = root / "README.zh.md"
    readme_zh.write_text("# 消费方仓库\n\n[English](README.md) | 中文\n", encoding="utf-8")
    record = root / "README.i18n.yaml"
    record.write_text(
        "README.md: "
        + git("hash-object", str(readme), cwd=root).stdout.strip()
        + "\nREADME.zh.md: "
        + git("hash-object", str(readme_zh), cwd=root).stdout.strip()
        + "\n",
        encoding="utf-8",
    )
    git("add", "-A", cwd=root)
    git("commit", "-qm", "base", cwd=root)
    monkeypatch.chdir(root)
    return Repo(root)


def commit_all(repo: Repo, message: str = "commit") -> None:
    """Stage and commit every worktree change in the consumer repository."""
    git("add", "-A", cwd=repo.root)
    git("commit", "-qm", message, cwd=repo.root)


def adopt_arguments(*extra: str) -> list[str]:
    """The canonical adoption parameters with per-test overrides."""
    return [
        "--hdsh-ref",
        "v0.1.0",
        "--account-type",
        "user",
        "--project-number",
        "3",
        "--project-title",
        "Consumer Issues",
        "--lifecycle-actor",
        "consumer-bot",
        "--time-zone",
        "Asia/Shanghai",
        *extra,
    ]
