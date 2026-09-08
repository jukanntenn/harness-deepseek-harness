"""Git-backed pairing operations: index reads, blob storage, merge inputs."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from hdsh.pairing.git import (
    GitError,
    blob_hash,
    git_index_paths,
    git_merge_input_paths,
    read_git_index_blob,
    run_git,
    store_git_blob,
)
from tests.helpers import Repo, git


def test_blob_hash_matches_git_hash_object(repo: Repo) -> None:
    content = b"cross-check\n"
    expected = git(
        "hash-object", "--stdin", cwd=repo.root, check=True, input=content
    ).stdout.strip()
    assert blob_hash(content) == expected
    int(digest := blob_hash(b"hello pair\n"), 16)
    assert len(digest) == 40


def test_index_paths_lists_stage_zero(repo: Repo) -> None:
    repo.write("a.md", "a\n")
    repo.write("b.md", "b\n")
    repo.add_all()
    assert git_index_paths(str(repo.root)) == {
        "a.md",
        "b.md",
        ".hdsh/pairing.manifest.json",
    }


def test_index_paths_rejects_malformed_entry(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_git(
        root: str, args: list[str], operation: str, *, input_bytes: bytes | None = None
    ) -> bytes:
        return b"malformed-entry"

    monkeypatch.setattr("hdsh.pairing.git.run_git", fake_run_git)
    with pytest.raises(GitError, match="malformed entry"):
        git_index_paths(str(repo.root))


def test_read_git_index_blob_round_trips(repo: Repo) -> None:
    repo.write("docs/x.md", "staged content\n")
    repo.add_all()
    staged = read_git_index_blob(str(repo.root), "docs/x.md")
    assert staged is not None
    object_id, content = staged
    assert content == b"staged content\n"
    assert object_id == blob_hash(content)


def test_read_git_index_blob_absent_returns_none(repo: Repo) -> None:
    assert read_git_index_blob(str(repo.root), "gone.md") is None


def test_read_git_index_blob_unmerged_raises(repo: Repo) -> None:
    repo.write("conflict.md", "base\n")
    repo.commit("base")
    git("branch", "side", cwd=repo.root)
    repo.write("conflict.md", "main version\n")
    repo.commit("main change")
    git("checkout", "side", cwd=repo.root)
    repo.write("conflict.md", "side version\n")
    repo.commit("side change")
    git("merge", "main", cwd=repo.root, check=False)
    with pytest.raises(GitError, match="unmerged|exactly one"):
        read_git_index_blob(str(repo.root), "conflict.md")


def test_store_git_blob_persists_and_pins(repo: Repo) -> None:
    content = b"uncommitted bytes\n"
    object_id = store_git_blob(str(repo.root), content)
    assert object_id == blob_hash(content)
    cat = git("cat-file", "blob", object_id, cwd=repo.root).stdout.encode()
    assert cat == content
    ref = f"refs/hdsh/pairing/snapshots/{object_id}"
    assert git("rev-parse", ref, cwd=repo.root).stdout.strip() == object_id


def test_store_git_blob_survives_aggressive_gc(repo: Repo) -> None:
    content = b"gc survivor\n"
    object_id = store_git_blob(str(repo.root), content)
    git("gc", "--prune=now", cwd=repo.root)
    cat = git("cat-file", "blob", object_id, cwd=repo.root, check=False)
    assert cat.returncode == 0
    assert cat.stdout.encode() == content


def test_store_git_blob_outside_a_repository_fails(tmp_path: Path) -> None:
    with pytest.raises(GitError, match="hash-object"):
        store_git_blob(str(tmp_path), b"nowhere\n")


def test_read_staged_bytes_ignores_worktree_overwrite(repo: Repo) -> None:
    repo.write("owner.md", "staged")
    repo.add_all()
    repo.write("owner.md", "unstaged")
    staged = read_git_index_blob(str(repo.root), "owner.md")
    assert staged is not None
    assert staged[1] == b"staged"
    assert staged[0] == blob_hash(b"staged")


def _git_supports_sha256() -> bool:
    probe = tempfile.mkdtemp(prefix="hdsh-sha256-probe-")
    try:
        return (
            subprocess.run(
                ["git", "init", "--quiet", "--object-format=sha256", probe],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
    finally:
        shutil.rmtree(probe, ignore_errors=True)


@pytest.mark.skipif(not _git_supports_sha256(), reason="git lacks sha256 object format")
def test_store_git_blob_rejects_sha256_object_format(tmp_path: Path) -> None:
    root = tmp_path / "sha256"
    root.mkdir()
    git("init", "--quiet", "--object-format=sha256", cwd=root)
    with pytest.raises(GitError, match="returned unexpected object ID"):
        store_git_blob(str(root), b"snapshot\n")


def test_merge_input_paths_includes_merge_head_trees(repo: Repo) -> None:
    repo.write("shared.md", "base\n")
    repo.commit("base")
    git("branch", "side", cwd=repo.root)
    repo.write("shared.md", "main version\n")
    repo.commit("main change")
    git("checkout", "side", cwd=repo.root)
    repo.write("shared.md", "side version\n")
    repo.write("side.md", "side only\n")
    repo.commit("side change")
    git("merge", "main", cwd=repo.root, check=False)
    environment = dict(os.environ)
    merge_head = git("rev-parse", "MERGE_HEAD", cwd=repo.root).stdout.strip()
    environment[f"GITHEAD_{merge_head}"] = ""
    paths = git_merge_input_paths(str(repo.root), environment)
    # stage zero holds this side's files; the merge-head tree contributes the
    # other side's clean addition before git writes it to the index.
    assert "shared.md" in paths
    assert ".hdsh/pairing.manifest.json" in paths


def test_run_git_failure_raises_with_stderr(repo: Repo) -> None:
    with contextlib.suppress(AssertionError):
        git("rev-parse", "--verify", "definitely-not-a-ref", cwd=repo.root)
    with pytest.raises(GitError, match="probe failed with status"):
        run_git(str(repo.root), ["rev-parse", "--verify", "definitely-not-a-ref"], "probe")


class TestGitOpsEdges:
    def test_run_git_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("no git")

        monkeypatch.setattr(subprocess, "run", raising_run)
        with pytest.raises(GitError, match="probe failed"):
            run_git(".", ["--version"], "probe")

    def test_store_git_blob_mismatch(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run_git(
            root: str, args: list[str], operation: str, *, input_bytes: bytes | None = None
        ) -> bytes:
            return b"0" * 40

        monkeypatch.setattr("hdsh.pairing.git.run_git", fake_run_git)
        with pytest.raises(GitError, match="unexpected object ID"):
            store_git_blob(str(repo.root), b"data\n")

    def test_merge_input_paths_without_environment(self, repo: Repo) -> None:
        from tests.helpers import MANIFEST, write_pair

        write_pair(repo, "docs/guide.md")
        repo.add_all()
        paths = git_merge_input_paths(str(repo.root), {"HOME": "/x"})
        assert MANIFEST["excluded"]
        assert ".hdsh/pairing.manifest.json" in paths

    def test_read_git_index_blob_meta_separator_missing(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run_git(
            root: str, args: list[str], operation: str, *, input_bytes: bytes | None = None
        ) -> bytes:
            return b"no-tabs-here\0"

        monkeypatch.setattr("hdsh.pairing.git.run_git", fake_run_git)
        with pytest.raises(GitError, match="invalid index entry"):
            read_git_index_blob(str(repo.root), "docs/x.md")

    def test_git_ops_malformed_stage_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run_git(
            root: str, args: list[str], operation: str, *, input_bytes: bytes | None = None
        ) -> bytes:
            return b"bad-entry\0"

        monkeypatch.setattr("hdsh.pairing.git.run_git", fake_run_git)
        with pytest.raises(GitError, match="malformed entry"):
            git_index_paths("/repo")

    def test_git_ops_stage_wrong_stage_number(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run_git(
            root: str, args: list[str], operation: str, *, input_bytes: bytes | None = None
        ) -> bytes:
            return b"100644 abc 2\tx.md\0"

        monkeypatch.setattr("hdsh.pairing.git.run_git", fake_run_git)
        with pytest.raises(GitError, match="unmerged or has an invalid index entry"):
            read_git_index_blob("/repo", "x.md")

    def test_git_ops_malformed_stage_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run_git(
            root: str, args: list[str], operation: str, *, input_bytes: bytes | None = None
        ) -> bytes:
            return b"onefield\tx.md\0"

        monkeypatch.setattr("hdsh.pairing.git.run_git", fake_run_git)
        with pytest.raises(GitError, match="malformed entry"):
            git_index_paths("/repo")

    def test_git_ops_index_blob_malformed_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run_git(
            root: str, args: list[str], operation: str, *, input_bytes: bytes | None = None
        ) -> bytes:
            return b"nometadata\tx.md\0"

        monkeypatch.setattr("hdsh.pairing.git.run_git", fake_run_git)
        with pytest.raises(GitError, match="invalid index entry"):
            read_git_index_blob("/repo", "x.md")
