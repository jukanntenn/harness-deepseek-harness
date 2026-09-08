"""The installer-owned hooks directory and the common-directory install lock."""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from pathlib import Path

from hdsh.worktree.git import WorktreeError

MINIMUM_GIT = (2, 26, 0)
HOOKS_DIRECTORY = "hdsh-hooks"
OWNERSHIP_MARKER = ".hdsh-hooks-owned"
OWNERSHIP_MARKER_VERSION = 1
OWNERSHIP_MARKER_OWNER = "harness-deepseek-harness worktree-local prek hooks"
INSTALL_LOCK = "hdsh-hooks-install.lock"
INSTALL_LOCK_TIMEOUT_SECONDS = 30.0
INSTALL_LOCK_INITIALIZATION_TIMEOUT_SECONDS = 5.0
INSTALL_LOCK_POLL_SECONDS = 0.05

_LOCK_RECORD = re.compile(
    r"^([1-9]\d*) [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\n$",
    re.IGNORECASE,
)
_LOCK_PARTIAL_RECORD = re.compile(r"^[1-9]\d*(?: [0-9a-f-]*)?$", re.IGNORECASE)


def assert_supported_git(version_output: str) -> None:
    """Refuse Git releases without worktree-local config support.

    Args:
        version_output: The output of ``git --version``.

    Raises:
        WorktreeError: When the Git version cannot be parsed or is too old.
    """
    match = re.search(r"git version (\d+)\.(\d+)(?:\.(\d+))?", version_output)
    if match is None:
        msg = f"cannot determine Git version from {version_output!r}"
        raise WorktreeError(msg)
    actual = (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
    if actual < MINIMUM_GIT:
        msg = f"Git 2.26 or newer is required for worktree-local hooks; found {version_output}"
        raise WorktreeError(msg)


def lstat_if_present(path: str | Path) -> os.stat_result | None:
    """Stat one path without following symlinks, or ``None`` when absent."""
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def ownership_marker_content(hooks_path: str) -> str:
    """Render the ownership marker guarding one hooks directory."""
    return (
        json.dumps(
            {
                "version": OWNERSHIP_MARKER_VERSION,
                "owner": OWNERSHIP_MARKER_OWNER,
                "hooksPath": hooks_path,
            }
        )
        + "\n"
    )


def parse_ownership_marker(content: str) -> dict[str, str] | None:
    """Parse one ownership marker, or ``None`` when it does not identify this installer."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(parsed, dict)
        or parsed.get("version") != OWNERSHIP_MARKER_VERSION
        or parsed.get("owner") != OWNERSHIP_MARKER_OWNER
        or not isinstance(parsed.get("hooksPath"), str)
        or not Path(parsed["hooksPath"]).is_absolute()
    ):
        return None
    return {"hooksPath": parsed["hooksPath"]}


def inspect_owned_hooks_directory(hooks_path: str) -> dict[str, str] | None:
    """Validate one hooks directory this installer is allowed to manage.

    Args:
        hooks_path: Candidate hooks directory.

    Returns:
        The parsed ownership marker, or ``None`` when the directory is absent.

    Raises:
        WorktreeError: When the directory, its marker, or any entry is not an
            owned, singly linked, regular file or directory.
    """
    directory = Path(hooks_path)
    marker_path = directory / OWNERSHIP_MARKER
    directory_stat = lstat_if_present(directory)
    if directory_stat is None:
        return None
    if not stat.S_ISDIR(directory_stat.st_mode):
        msg = f"refusing to use non-directory or symlinked hooks path {hooks_path}"
        raise WorktreeError(msg)
    marker_stat = lstat_if_present(marker_path)
    if marker_stat is None:
        msg = f"refusing to overwrite unowned hooks directory {hooks_path}"
        raise WorktreeError(msg)
    marker = (
        parse_ownership_marker(marker_path.read_text(encoding="utf-8"))
        if stat.S_ISREG(marker_stat.st_mode) and marker_stat.st_nlink == 1
        else None
    )
    if marker is None:
        msg = (
            f"refusing to overwrite hooks directory with an invalid ownership marker: {hooks_path}"
        )
        raise WorktreeError(msg)
    for entry in directory.iterdir():
        if entry.name == OWNERSHIP_MARKER:
            continue
        entry_stat = os.lstat(entry)
        if not stat.S_ISREG(entry_stat.st_mode) or entry_stat.st_nlink != 1:
            msg = f"refusing to overwrite non-regular or multiply linked hook entry {str(entry)!r}"
            raise WorktreeError(msg)
    return marker


def update_ownership_marker(marker_path: str, hooks_path: str) -> None:
    """Rewrite one ownership marker as a singly linked, owner-only file."""
    descriptor = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(ownership_marker_content(hooks_path))


def ensure_owned_hooks_directory(hooks_path: str) -> str:
    """Create or validate the installer-owned hooks directory.

    The marker of an already-owned directory is left untouched here: the
    recorded path stays the pre-relocation one until the installation itself
    succeeds and :func:`update_ownership_marker` refreshes it.

    Args:
        hooks_path: Candidate hooks directory.

    Returns:
        The ownership-marker path.

    Raises:
        WorktreeError: When the directory exists but is not owned.
    """
    if inspect_owned_hooks_directory(hooks_path) is None:
        Path(hooks_path).mkdir(mode=0o700)
        marker_path = str(Path(hooks_path, OWNERSHIP_MARKER))
        update_ownership_marker(marker_path, hooks_path)
        return marker_path
    return str(Path(hooks_path, OWNERSHIP_MARKER))


def _lock_record_owner(record: str) -> int | None:
    """Return the owner PID of one complete installer lock record."""
    match = _LOCK_RECORD.match(record)
    return int(match.group(1)) if match is not None else None


def _lock_record_may_be_incomplete(record: str) -> bool:
    """Whether one unparsable record may still be mid-write by its creator."""
    # Exclusive creation exposes the inode before its owner record is fully written.
    return record == "" or (
        not record.endswith("\n") and _LOCK_PARTIAL_RECORD.match(record) is not None
    )


def _lock_owner_is_alive(owner: int) -> bool:
    """Whether one lock-owner PID still names a live process."""
    try:
        os.kill(owner, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _manual_lock_recovery_error(lock_path: Path, condition: str) -> WorktreeError:
    """The fail-loud error directing the operator to remove one stuck lock."""
    return WorktreeError(
        f"{condition} installer lock {lock_path}. Confirm no installer is running, "
        "remove it manually, and retry."
    )


def _ownership_changed_error(lock_path: Path) -> WorktreeError:
    return WorktreeError(f"installer lock ownership changed for {lock_path}; refusing to remove it")


def release_install_lock(lock_path: Path, owned_record: str, owned_stat: os.stat_result) -> None:
    """Remove the installer lock only when it still names this process.

    Args:
        lock_path: The acquired lock file.
        owned_record: The record this installer wrote.
        owned_stat: The ``lstat`` of the lock file at acquisition time.

    Raises:
        WorktreeError: When the lock file, its inode, or its content changed.
    """
    changed = _ownership_changed_error(lock_path)
    current_stat = lstat_if_present(lock_path)
    if (
        current_stat is None
        or not stat.S_ISREG(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != (owned_stat.st_dev, owned_stat.st_ino)
    ):
        raise changed
    try:
        content = lock_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise changed from None
    if content != owned_record:
        raise changed
    try:
        lock_path.unlink()
    except FileNotFoundError as error:
        raise changed from error


def acquire_install_lock(common_directory: str) -> tuple[Path, str, os.stat_result]:
    """Acquire the common-directory installer lock, failing loud when stuck.

    Args:
        common_directory: Shared git directory of the repository worktrees.

    Returns:
        The lock path, owned record, and acquisition-time ``lstat`` for release.

    Raises:
        WorktreeError: When the lock is invalid, stale, never released, or its
            ownership changes during publication.
    """
    lock_path = Path(common_directory, INSTALL_LOCK)
    deadline = time.monotonic() + INSTALL_LOCK_TIMEOUT_SECONDS
    record = f"{os.getpid()} {uuid.uuid4()}\n"
    initializing: tuple[float, int, int] | None = None
    while True:
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing_stat = lstat_if_present(lock_path)
            if existing_stat is None:
                continue
            if not stat.S_ISREG(existing_stat.st_mode):
                raise _manual_lock_recovery_error(lock_path, "invalid") from None
            try:
                existing_record = lock_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            verified_stat = lstat_if_present(lock_path)
            if verified_stat is None:
                continue
            if not stat.S_ISREG(verified_stat.st_mode):
                raise _manual_lock_recovery_error(lock_path, "invalid") from None
            if (verified_stat.st_dev, verified_stat.st_ino) != (
                existing_stat.st_dev,
                existing_stat.st_ino,
            ):
                continue
            owner = _lock_record_owner(existing_record)
            if owner is None:
                if not _lock_record_may_be_incomplete(existing_record):
                    raise _manual_lock_recovery_error(lock_path, "invalid") from None
                now = time.monotonic()
                if initializing is None or initializing[1:] != (
                    existing_stat.st_dev,
                    existing_stat.st_ino,
                ):
                    initializing = (
                        now + INSTALL_LOCK_INITIALIZATION_TIMEOUT_SECONDS,
                        existing_stat.st_dev,
                        existing_stat.st_ino,
                    )
                if now >= initializing[0]:
                    raise _manual_lock_recovery_error(lock_path, "invalid") from None
                time.sleep(INSTALL_LOCK_POLL_SECONDS)
                continue
            initializing = None
            if not _lock_owner_is_alive(owner):
                raise _manual_lock_recovery_error(lock_path, "stale") from None
            if time.monotonic() >= deadline:
                msg = f"timed out waiting for installer lock {lock_path}"
                raise WorktreeError(msg) from None
            time.sleep(INSTALL_LOCK_POLL_SECONDS)
            continue
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(record)
                owned_stat = os.fstat(handle.fileno())
            published_stat = lstat_if_present(lock_path)
            if (
                published_stat is None
                or not stat.S_ISREG(published_stat.st_mode)
                or (published_stat.st_dev, published_stat.st_ino)
                != (owned_stat.st_dev, owned_stat.st_ino)
            ):
                raise _ownership_changed_error(lock_path) from None
            return lock_path, record, owned_stat
