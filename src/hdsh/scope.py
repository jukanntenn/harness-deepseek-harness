"""Report the explicit committed and worktree scope of a repository change."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh scope"

FORMAT_VERSION = 1

_WINDOWS = sys.platform == "win32"


class ScopeError(RuntimeError):
    """A repository-owned Git subprocess failed or returned invalid output."""


def _strip_git_line_terminator(output: str) -> str:
    """Strip one trailing line feed, plus one carriage return on Windows."""
    without_line_feed = output.removesuffix("\n")
    if _WINDOWS and without_line_feed.endswith("\r"):
        return without_line_feed[:-1]
    return without_line_feed


def _execute_git_bytes(cwd: str, args: list[str], context: str) -> tuple[int, bytes, bytes]:
    """Run one Git subprocess, returning its raw status and output streams.

    Args:
        cwd: Directory whose containing worktree is inspected.
        args: Arguments following the ``git`` executable.
        context: Human-readable operation for failure diagnostics.

    Returns:
        The exit status, stdout bytes, and stderr bytes.

    Raises:
        ScopeError: When Git cannot start.
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "-c", "core.fsmonitor=false", *args],
            capture_output=True,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LANG": "C", "LC_ALL": "C"},
        )
    except OSError as error:
        raise ScopeError(f"{context}: {error}") from error
    return result.returncode, result.stdout, result.stderr


def _decode_strict(output: bytes, context: str, stream: str) -> str:
    """Decode one Git output stream as UTF-8 or fail loud."""
    try:
        return output.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ScopeError(f"{context}: Git {stream} is not valid UTF-8") from error


def _execute_git(cwd: str, args: list[str], context: str) -> tuple[int, str, str]:
    """Run one Git subprocess with both streams strictly decoded as UTF-8."""
    status, stdout, stderr = _execute_git_bytes(cwd, args, context)
    return (
        status,
        _decode_strict(stdout, context, "stdout"),
        _decode_strict(stderr, context, "stderr"),
    )


def _require_git(cwd: str, args: list[str], context: str) -> str:
    """Run one Git subprocess and return its stdout, failing loud on errors."""
    status, stdout, stderr = _execute_git(cwd, args, context)
    if status != 0:
        raise ScopeError(f"{context}: {stderr.strip() or f'Git exited with status {status}'}")
    return stdout


def _require_git_bytes(cwd: str, args: list[str], context: str) -> bytes:
    """Run one Git subprocess and return raw stdout, failing loud on errors."""
    status, stdout, stderr = _execute_git_bytes(cwd, args, context)
    if status != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise ScopeError(f"{context}: {detail or f'Git exited with status {status}'}")
    return stdout


def register(domains: cliargs.CommandSubparsers) -> None:
    """Register the ``hdsh scope`` domain parser and its handler."""
    parser = domains.add_parser("scope", help="explicit committed and worktree change-scope report")
    parser.add_argument("--base", required=True, help="base ref of the outgoing change")
    parser.add_argument("--head", default="HEAD", help="head ref of the outgoing change")
    parser.set_defaults(handler=main)


def _resolve_commit(root: str, label: str, ref: str) -> str:
    """Resolve one ref to exactly one commit ID.

    Args:
        root: Repository root.
        label: ``base`` or ``head``, for diagnostics.
        ref: The ref to resolve.

    Returns:
        The commit ID.

    Raises:
        ScopeError: When the ref is ambiguous or does not resolve to one commit.
    """
    context = f"cannot resolve {label} ref {ref!r}"
    status, stdout, stderr = _execute_git(
        root,
        [
            "-c",
            "core.warnAmbiguousRefs=true",
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{ref}^{{commit}}",
        ],
        context,
    )
    if re.search(r"\bambiguous\b", stderr, re.IGNORECASE):
        raise ScopeError(
            f"{label} ref {ref!r} is ambiguous; use a fully qualified ref or commit ID"
        )
    if status != 0:
        detail = stderr.strip() or f"Git exited with status {status}"
        raise ScopeError(f"{label} ref {ref!r} does not resolve to a commit: {detail}")
    commits = [line for line in stdout.splitlines() if line]
    if len(commits) != 1:
        raise ScopeError(f"{label} ref {ref!r} did not resolve to exactly one commit")
    return commits[0]


def _resolve_merge_base(root: str, base_sha: str, head_sha: str) -> str:
    """Resolve the unique merge base of two commits.

    Args:
        root: Repository root.
        base_sha: Base commit ID.
        head_sha: Head commit ID.

    Returns:
        The merge-base commit ID.

    Raises:
        ScopeError: When no unique merge base exists.
    """
    stdout = _require_git(
        root, ["merge-base", "--all", base_sha, head_sha], "cannot resolve the merge base"
    )
    merge_bases = [line for line in stdout.splitlines() if line]
    if len(merge_bases) != 1:
        raise ScopeError(f"base and head do not have a unique merge base; found {len(merge_bases)}")
    return merge_bases[0]


def _parse_path_set(output: bytes, context: str) -> list[str]:
    """Deduplicate and sort one NUL-separated Git path listing.

    Args:
        output: Raw ``-z`` output.
        context: Human-readable operation for failure diagnostics.

    Returns:
        Sorted unique paths.

    Raises:
        ScopeError: When any path is not valid UTF-8.
    """
    paths: list[str] = []
    start = 0
    record = 0
    for end, byte in enumerate(output):
        if byte != 0:
            continue
        if end > start:
            record += 1
            try:
                paths.append(output[start:end].decode("utf-8"))
            except UnicodeDecodeError as error:
                raise ScopeError(f"{context}: Git path {record} is not valid UTF-8") from error
        start = end + 1
    return sorted(set(paths))


def _diff_paths(root: str, args: list[str], context: str) -> list[str]:
    """List paths changed by one ``git diff`` invocation.

    Args:
        root: Repository root.
        args: Diff arguments before the path separator.
        context: Human-readable operation for failure diagnostics.

    Returns:
        Sorted unique changed paths.
    """
    output = _require_git_bytes(
        root,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--ignore-submodules=none",
            "--name-only",
            "-z",
            *args,
            "--",
        ],
        context,
    )
    return _parse_path_set(output, context)


def collect_report(base: str, head: str, cwd: str) -> dict[str, Any]:
    """Collect the versioned change-scope report for one worktree.

    Args:
        base: Base ref of the outgoing change.
        head: Head ref of the outgoing change.
        cwd: Directory whose containing Git worktree is inspected.

    Returns:
        The report dictionary.

    Raises:
        ScopeError: When any repository inspection fails.
    """
    root = _strip_git_line_terminator(
        _require_git(cwd, ["rev-parse", "--show-toplevel"], "cannot locate a Git worktree")
    )
    base_sha = _resolve_commit(root, "base", base)
    head_sha = _resolve_commit(root, "head", head)
    merge_base_sha = _resolve_merge_base(root, base_sha, head_sha)
    return {
        "formatVersion": FORMAT_VERSION,
        "repositoryRoot": root,
        "input": {"base": base, "head": head},
        "resolved": {
            "baseSha": base_sha,
            "headSha": head_sha,
            "mergeBaseSha": merge_base_sha,
        },
        "paths": {
            "committed": _diff_paths(
                root, [merge_base_sha, head_sha], "cannot inspect committed paths"
            ),
            "staged": _diff_paths(root, ["--cached"], "cannot inspect staged paths"),
            "unstaged": _diff_paths(root, [], "cannot inspect unstaged paths"),
            "untracked": _parse_path_set(
                _require_git_bytes(
                    root,
                    ["ls-files", "--others", "--exclude-standard", "-z", "--"],
                    "cannot inspect untracked paths",
                ),
                "cannot inspect untracked paths",
            ),
        },
    }


def render_scope(base: str, head: str, cwd: str) -> str:
    """Render one complete versioned report.

    Args:
        base: Base ref of the outgoing change.
        head: Head ref of the outgoing change.
        cwd: Directory whose containing Git worktree is inspected.

    Returns:
        JSON report with a trailing newline.

    Raises:
        ScopeError: When any repository inspection fails.
    """
    report = collect_report(base, head, cwd)
    return f"{json.dumps(report, indent=2, ensure_ascii=False)}\n"


def main(args: argparse.Namespace) -> int:
    """``hdsh scope`` entry point.

    Args:
        args: Parsed domain namespace with ``base`` and ``head``.

    Returns:
        The exit code: 0 report rendered, 1 repository inspection failed.
    """
    try:
        cwd = str(Path.cwd())
        sys.stdout.write(render_scope(args.base, args.head, cwd))
    except ScopeError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    return 0
