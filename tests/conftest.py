"""Shared fixtures: disposable Git repositories with pairing corpora."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import MANIFEST, Repo, git


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """A disposable initialized Git repository with the pairing manifest."""
    root = tmp_path / "repo"
    root.mkdir()
    git("init", "-b", "main", cwd=root)
    git("config", "user.email", "test@example.com", cwd=root)
    git("config", "user.name", "Test", cwd=root)
    hdsh = root / ".hdsh"
    hdsh.mkdir()
    (hdsh / "pairing.manifest.json").write_text(
        json.dumps(MANIFEST, indent=2) + "\n", encoding="utf-8"
    )
    return Repo(root)
