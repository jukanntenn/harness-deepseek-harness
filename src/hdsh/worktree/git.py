"""Git subprocess boundary for the worktree installer."""

from __future__ import annotations

import subprocess
import sys

_WINDOWS = sys.platform == "win32"


class WorktreeError(RuntimeError):
    """The installer refused to proceed or a Git subprocess failed."""


def strip_git_line_terminator(output: str) -> str:
    """Strip one trailing line feed, plus one carriage return on Windows."""
    without_line_feed = output.removesuffix("\n")
    if _WINDOWS and without_line_feed.endswith("\r"):
        return without_line_feed[:-1]
    return without_line_feed


def run_git(
    root: str, args: list[str], *, allow_status: tuple[int, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """Run one Git subprocess, decoding output as UTF-8 text.

    Args:
        root: Working directory for Git.
        args: Arguments following the ``git`` executable.
        allow_status: Exit statuses treated as success.

    Returns:
        The completed process.

    Raises:
        WorktreeError: When Git cannot start or exits unsuccessfully.
    """
    try:
        result = subprocess.run(
            ["git", "-C", root, *args], capture_output=True, text=True, check=False
        )
    except OSError as error:
        msg = f"git {' '.join(args)} failed: {error}"
        raise WorktreeError(msg) from error
    if result.returncode != 0 and result.returncode not in allow_status:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        msg = f"git {' '.join(args)} failed: {detail}"
        raise WorktreeError(msg) from None
    return result


def nul_values(result: subprocess.CompletedProcess[str]) -> list[str]:
    """Split one NUL-separated ``git --null`` output, keeping empty values.

    An empty-valued key reports one empty string, matching Git's NUL framing,
    so Boolean parsing can distinguish "unset" from "set to the empty value".
    """
    if result.returncode != 0:
        return []
    if result.stdout == "":
        return [""]
    output = result.stdout.removesuffix("\0")
    return output.split("\0")
