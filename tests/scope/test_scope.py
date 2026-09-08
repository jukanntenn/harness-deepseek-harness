"""Change-scope report collection and rendering."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import pytest

from hdsh.scope import (
    ScopeError,
    _parse_path_set,
    collect_report,
    main,
    register,
    render_scope,
)
from tests.helpers import Repo, completed_run, git, parse_command


def _init_repo(path: Path) -> Path:
    """One disposable repository with an initial commit and no extra files."""
    path.mkdir(parents=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.email", "scope@example.com", cwd=path)
    git("config", "user.name", "Scope Tests", cwd=path)
    (path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    git("add", "README.md", cwd=path)
    git("commit", "-m", "initial", cwd=path)
    return path


def _commit(root: Path, path: str, content: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git("add", "--", path, cwd=root)
    git("commit", "-m", f"add {path}", cwd=root)
    return git("rev-parse", "HEAD", cwd=root).stdout.strip()


def _repository_state(root: Path) -> dict[str, str]:
    index = root / ".git" / "index"
    config = root / ".git" / "config"
    return {
        "status": git("status", "--porcelain=v2", "--branch", "-z", cwd=root).stdout,
        "head": git("rev-parse", "HEAD", cwd=root).stdout,
        "refs": git("for-each-ref", "--format=%(refname) %(objectname)", cwd=root).stdout,
        "index": base64.b64encode(index.read_bytes()).decode("ascii"),
        "config": base64.b64encode(config.read_bytes()).decode("ascii"),
    }


class TestChangeScope:
    def test_uses_explicit_base_on_a_fresh_branch_without_same_name_remote(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin.git"
        git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
        root = _init_repo(tmp_path / "worktree")
        git("remote", "add", "origin", str(origin), cwd=root)
        git("push", "--set-upstream", "origin", "main", cwd=root)
        git("switch", "-c", "feature", cwd=root)
        git("branch", "--set-upstream-to=origin/main", cwd=root)
        head_sha = _commit(root, "feature.txt", "feature\n")
        origin_sha = git("rev-parse", "origin/main", cwd=root).stdout.strip()

        fresh = collect_report("origin/main", "HEAD", str(root))
        assert fresh["repositoryRoot"] == str(root)
        assert fresh["resolved"] == {
            "baseSha": origin_sha,
            "headSha": head_sha,
            "mergeBaseSha": origin_sha,
        }
        assert fresh["paths"] == {
            "committed": ["feature.txt"],
            "staged": [],
            "unstaged": [],
            "untracked": [],
        }
        assert (
            git(
                "for-each-ref", "--format=%(refname)", "refs/remotes/origin/feature", cwd=root
            ).stdout.strip()
            == ""
        )

        git("push", "--set-upstream", "origin", "feature", cwd=root)
        pushed = collect_report("origin/main", "HEAD", str(root))
        assert pushed["paths"]["committed"] == ["feature.txt"]

    def test_preserves_trailing_spaces_in_the_worktree_path(self, tmp_path: Path) -> None:
        root = _init_repo(tmp_path / "worktree ")

        report = collect_report("HEAD", "HEAD", str(root))

        assert report["repositoryRoot"] == str(root)
        assert report["paths"] == {
            "committed": [],
            "staged": [],
            "unstaged": [],
            "untracked": [],
        }

    def test_reports_an_exact_head_above_a_stacked_base(self, tmp_path: Path) -> None:
        root = _init_repo(tmp_path / "worktree")
        git("switch", "-c", "foundation", cwd=root)
        base_sha = _commit(root, "foundation.txt", "foundation\n")
        git("switch", "-c", "topic", cwd=root)
        head_sha = _commit(root, "topic.txt", "topic\n")
        _commit(root, "later.txt", "later\n")
        (root / "current-worktree.txt").write_text("current worktree\n", encoding="utf-8")

        report = collect_report("foundation", head_sha, str(root))
        assert report["input"] == {"base": "foundation", "head": head_sha}
        assert report["resolved"] == {
            "baseSha": base_sha,
            "headSha": head_sha,
            "mergeBaseSha": base_sha,
        }
        assert report["paths"]["committed"] == ["topic.txt"]
        assert report["paths"]["untracked"] == ["current-worktree.txt"]

    def test_keeps_four_planes_independent_and_does_not_mutate_state(self, tmp_path: Path) -> None:
        root = _init_repo(tmp_path / "worktree")
        _commit(root, "unstaged.txt", "before\n")
        base_sha = git("rev-parse", "HEAD", cwd=root).stdout.strip()
        _commit(root, "committed.txt", "committed\n")
        (root / "staged.txt").write_text("staged\n", encoding="utf-8")
        (root / "mixed.txt").write_text("staged part\n", encoding="utf-8")
        git("add", "staged.txt", "mixed.txt", cwd=root)
        (root / "mixed.txt").write_text("staged part\nunstaged part\n", encoding="utf-8")
        (root / "unstaged.txt").write_text("unstaged\n", encoding="utf-8")
        (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        before = _repository_state(root)

        report = collect_report(base_sha, "HEAD", str(root))

        assert report["paths"] == {
            "committed": ["committed.txt"],
            "staged": ["mixed.txt", "staged.txt"],
            "unstaged": ["mixed.txt", "unstaged.txt"],
            "untracked": ["untracked.txt"],
        }
        assert _repository_state(root) == before

    def test_does_not_execute_a_configured_filesystem_monitor(self, tmp_path: Path) -> None:
        root = _init_repo(tmp_path / "worktree")
        monitor = tmp_path / "fsmonitor.sh"
        monitor.write_text('#!/bin/sh\ntouch "$0.ran"\n', encoding="utf-8")
        monitor.chmod(0o755)
        git("config", "core.fsmonitor", str(monitor), cwd=root)

        report = collect_report("HEAD", "HEAD", str(root))

        assert report["paths"] == {
            "committed": [],
            "staged": [],
            "unstaged": [],
            "untracked": [],
        }
        assert not (tmp_path / "fsmonitor.sh.ran").exists()

    def test_rejects_distinct_non_utf8_git_paths(self, repo: Repo) -> None:
        repo.write("a.txt", "a\n")
        repo.commit("a")
        blob_sha = git(
            "hash-object", "-w", "--stdin", input=b"content", cwd=repo.root
        ).stdout.strip()
        entry = b"100644 " + blob_sha.encode("ascii") + b"\t"
        index_input = entry + bytes([0x80]) + b"\0" + entry + bytes([0x81]) + b"\0"
        subprocess.run(
            ["git", "-C", str(repo.root), "update-index", "-z", "--index-info"],
            input=index_input,
            capture_output=True,
            check=True,
        )

        with pytest.raises(
            ScopeError, match="cannot inspect staged paths: Git path 1 is not valid UTF-8"
        ):
            collect_report("main", "HEAD", str(repo.root))

    def test_rejects_missing_ambiguous_and_non_commit_refs(self, tmp_path: Path) -> None:
        root = _init_repo(tmp_path / "worktree")
        git("branch", "collision", cwd=root)
        git("tag", "collision", cwd=root)
        (root / "blob.txt").write_text("blob\n", encoding="utf-8")
        blob_sha = git("hash-object", "-w", "blob.txt", cwd=root).stdout.strip()
        git("tag", "blob-ref", blob_sha, cwd=root)

        with pytest.raises(ScopeError, match=r"base ref 'missing' does not resolve to a commit"):
            collect_report("missing", "HEAD", str(root))
        with pytest.raises(ScopeError, match=r"base ref 'collision' is ambiguous"):
            collect_report("collision", "HEAD", str(root))
        with pytest.raises(ScopeError, match=r"base ref 'blob-ref' does not resolve to a commit"):
            collect_report("blob-ref", "HEAD", str(root))
        with pytest.raises(ScopeError, match=r"head ref 'missing' does not resolve to a commit"):
            collect_report("main", "missing", str(root))

    def test_renders_deterministic_versioned_json(self, tmp_path: Path) -> None:
        root = _init_repo(tmp_path / "worktree")
        git("switch", "-c", "format", cwd=root)
        _commit(root, "zeta.txt", "zeta\n")
        _commit(root, "alpha.txt", "alpha\n")
        _commit(root, "仓库文档.txt", "文档\n")

        rendered = render_scope("main", "HEAD", str(root))
        repeated = render_scope("main", "HEAD", str(root))
        report = json.loads(rendered)

        assert rendered == repeated
        assert report["formatVersion"] == 1
        assert report["paths"]["committed"] == ["alpha.txt", "zeta.txt", "仓库文档.txt"]
        assert "仓库文档.txt" in rendered


class TestScopeEdges:
    def test_untracked_listing_error_context(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hdsh.scope as scope_module

        repo.write("a.txt", "a\n")
        repo.commit("a")
        real = scope_module._require_git_bytes

        def wrapper(cwd: str, args: list[str], context: str) -> bytes:
            if "ls-files" in args:
                raise ScopeError(f"{context}: boom")
            return real(cwd, args, context)

        monkeypatch.setattr(scope_module, "_require_git_bytes", wrapper)
        with pytest.raises(ScopeError, match="cannot inspect untracked paths: boom"):
            collect_report("main", "HEAD", str(repo.root))

    def test_resolve_commit_multiple_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import hdsh.scope as scope_module

        completed = subprocess.CompletedProcess([], 0, b"one\ntwo\n", b"")
        monkeypatch.setattr("hdsh.scope.subprocess.run", completed_run(completed))
        with pytest.raises(ScopeError, match="exactly one commit"):
            scope_module._resolve_commit(".", "base", "main")

    def test_merge_base_multiple_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import hdsh.scope as scope_module

        completed = subprocess.CompletedProcess([], 0, b"one\ntwo\n", b"")
        monkeypatch.setattr("hdsh.scope.subprocess.run", completed_run(completed))
        with pytest.raises(ScopeError, match="unique merge base"):
            scope_module._resolve_merge_base(".", "a", "b")

    def test_execute_git_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import hdsh.scope as scope_module

        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("boom")

        monkeypatch.setattr("hdsh.scope.subprocess.run", raising_run)
        with pytest.raises(ScopeError, match="boom"):
            scope_module._execute_git_bytes(".", ["--version"], "context")

    def test_execute_git_invalid_stdout_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess as subprocess_module

        import hdsh.scope as scope_module

        completed = subprocess_module.CompletedProcess([], 0, b"\xff\xfe", b"")
        monkeypatch.setattr("hdsh.scope.subprocess.run", completed_run(completed))
        with pytest.raises(ScopeError, match="Git stdout is not valid UTF-8"):
            scope_module._execute_git(".", ["--version"], "context")

    def test_execute_git_invalid_stderr_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess as subprocess_module

        import hdsh.scope as scope_module

        completed = subprocess_module.CompletedProcess([], 0, b"", b"\xff")
        monkeypatch.setattr("hdsh.scope.subprocess.run", completed_run(completed))
        with pytest.raises(ScopeError, match="Git stderr is not valid UTF-8"):
            scope_module._execute_git(".", ["--version"], "context")

    def test_require_git_reports_stderr_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess as subprocess_module

        import hdsh.scope as scope_module

        completed = subprocess_module.CompletedProcess([], 1, b"", b"boom\n")
        monkeypatch.setattr("hdsh.scope.subprocess.run", completed_run(completed))
        with pytest.raises(ScopeError, match="context: boom"):
            scope_module._require_git(".", ["--version"], "context")

    def test_require_git_reports_status_without_stderr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess as subprocess_module

        import hdsh.scope as scope_module

        completed = subprocess_module.CompletedProcess([], 1, b"", b"")
        monkeypatch.setattr("hdsh.scope.subprocess.run", completed_run(completed))
        with pytest.raises(ScopeError, match="Git exited with status 1"):
            scope_module._require_git_bytes(".", ["--version"], "context")

    def test_parse_path_set_skips_empty_segments(self) -> None:
        assert _parse_path_set(b"\0a\0", "context") == ["a"]
        assert _parse_path_set(b"", "context") == []

    def test_strip_line_terminator_variants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import hdsh.scope as scope_module

        monkeypatch.setattr(scope_module, "_WINDOWS", True)
        assert scope_module._strip_git_line_terminator("path\r\n") == "path"
        monkeypatch.setattr(scope_module, "_WINDOWS", False)
        assert scope_module._strip_git_line_terminator("path\r\n") == "path\r"
        assert scope_module._strip_git_line_terminator("path\n\n") == "path\n"
        assert scope_module._strip_git_line_terminator("path") == "path"


class TestScopeMain:
    def test_head_defaults_to_head(self) -> None:
        parsed = parse_command(register, ["scope", "--base", "main"])
        assert parsed.head == "HEAD"

    def test_missing_required_base_is_a_usage_error(self) -> None:
        with pytest.raises(ValueError, match="hdsh scope: the following arguments.*--base"):
            parse_command(register, ["scope", "--head", "HEAD"])

    def test_main_writes_report(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo.write("a.txt", "a\n")
        repo.commit("a")
        monkeypatch.chdir(repo.root)
        parsed = parse_command(register, ["scope", "--base", "main"])
        assert main(parsed) == 0
        assert "repositoryRoot" in capsys.readouterr().out

    def test_main_returns_one_on_git_failure(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parsed = parse_command(register, ["scope", "--base", "definitely-not-a-ref"])
        code = main(parsed)
        assert code == 1
        assert "hdsh scope:" in capsys.readouterr().err

    def test_unrelated_histories_fail(self, repo: Repo) -> None:
        repo.write("a.txt", "a\n")
        repo.commit("a")
        git("checkout", "--orphan", "orphan", cwd=repo.root)
        repo.write("b.txt", "b\n")
        repo.commit("b")
        with pytest.raises(ScopeError, match="merge base"):
            collect_report("main", "HEAD", str(repo.root))
