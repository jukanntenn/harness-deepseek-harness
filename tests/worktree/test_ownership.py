"""The installer-owned hooks directory markers and the install lock."""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any

import pytest

from hdsh.worktree import install as worktree_install
from hdsh.worktree.git import WorktreeError
from hdsh.worktree.install import install
from hdsh.worktree.ownership import (
    INSTALL_LOCK,
    OWNERSHIP_MARKER,
    OWNERSHIP_MARKER_OWNER,
    acquire_install_lock,
    ensure_owned_hooks_directory,
    inspect_owned_hooks_directory,
    ownership_marker_content,
    parse_ownership_marker,
    release_install_lock,
)
from tests.helpers import Repo, git


def git_dir(repo: Repo) -> Path:
    return Path(git("rev-parse", "--absolute-git-dir", cwd=repo.root).stdout.strip())


def common_dir(repo: Repo) -> Path:
    output = git("rev-parse", "--git-common-dir", cwd=repo.root).stdout.strip()
    path = Path(output)
    return path if path.is_absolute() else repo.root / path


def lock_path_of(repo: Repo) -> Path:
    return common_dir(repo) / INSTALL_LOCK


@pytest.fixture(autouse=True)
def no_prek(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the probe and prek invocation; ownership is under test."""

    def skipped(root: str) -> None:
        return None

    monkeypatch.setattr(worktree_install, "run_prek", skipped)
    monkeypatch.setattr(worktree_install, "probe_pairing_merge_driver", skipped)


def _no_sleep(seconds: float) -> None:
    """A time.sleep double that never waits."""


def _write_owned_hooks(hooks: Path, *, external_link: Path | None = None) -> None:
    """An owned hooks directory with one regular entry, optionally hardlinked."""
    hooks.mkdir(parents=True)
    marker = hooks / OWNERSHIP_MARKER
    marker.write_text(ownership_marker_content(str(hooks)), encoding="utf-8")
    entry = hooks / "pre-commit"
    entry.write_text("#!/bin/sh\n", encoding="utf-8")
    if external_link is not None:
        os.link(entry, external_link)


class TestMarkers:
    def test_marker_rejects_invalid_json(self) -> None:
        assert parse_ownership_marker("{nope") is None

    def test_marker_rejects_wrong_version(self) -> None:
        marker = json.dumps({"version": 9, "owner": OWNERSHIP_MARKER_OWNER, "hooksPath": "/x"})
        assert parse_ownership_marker(marker) is None

    def test_marker_rejects_relative_path(self) -> None:
        marker = json.dumps({"version": 1, "owner": OWNERSHIP_MARKER_OWNER, "hooksPath": "x"})
        assert parse_ownership_marker(marker) is None

    def test_marker_rejects_wrong_owner(self) -> None:
        marker = json.dumps({"version": 1, "owner": "someone else", "hooksPath": "/x"})
        assert parse_ownership_marker(marker) is None


class TestInspect:
    def test_inspect_absent_directory_returns_none(self, tmp_path: Path) -> None:
        assert inspect_owned_hooks_directory(str(tmp_path / "gone")) is None

    def test_inspect_rejects_symlinked_directory(self, repo: Repo, tmp_path: Path) -> None:
        link = tmp_path / "hooks-link"
        link.symlink_to(git_dir(repo))
        with pytest.raises(WorktreeError, match="non-directory or symlinked"):
            inspect_owned_hooks_directory(str(link))

    def test_inspect_rejects_non_directory(self, repo: Repo) -> None:
        target = git_dir(repo) / "not-a-dir"
        target.write_text("x", encoding="utf-8")
        with pytest.raises(WorktreeError, match="non-directory or symlinked"):
            inspect_owned_hooks_directory(str(target))

    def test_inspect_rejects_unowned_directory(self, repo: Repo) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        hooks.mkdir()
        with pytest.raises(WorktreeError, match="unowned hooks directory"):
            inspect_owned_hooks_directory(str(hooks))

    def test_inspect_rejects_invalid_marker(self, repo: Repo) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        hooks.mkdir()
        (hooks / OWNERSHIP_MARKER).write_text("garbage\n", encoding="utf-8")
        with pytest.raises(WorktreeError, match="invalid ownership marker"):
            inspect_owned_hooks_directory(str(hooks))

    def test_inspect_rejects_symlinked_marker(self, repo: Repo, tmp_path: Path) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        hooks.mkdir()
        target = tmp_path / "marker-target"
        target.write_text("{}\n", encoding="utf-8")
        (hooks / OWNERSHIP_MARKER).symlink_to(target)
        with pytest.raises(WorktreeError, match="invalid ownership marker"):
            inspect_owned_hooks_directory(str(hooks))

    def test_inspect_rejects_multiply_linked_marker(self, repo: Repo, tmp_path: Path) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        hooks.mkdir()
        marker = hooks / OWNERSHIP_MARKER
        marker.write_text(ownership_marker_content(str(hooks)), encoding="utf-8")
        os.link(marker, tmp_path / "external-marker")
        with pytest.raises(WorktreeError, match="invalid ownership marker"):
            inspect_owned_hooks_directory(str(hooks))

    def test_inspect_rejects_symlinked_hook_entry(self, repo: Repo) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        hooks.mkdir()
        (hooks / OWNERSHIP_MARKER).write_text(
            ownership_marker_content(str(hooks)), encoding="utf-8"
        )
        (hooks / "pre-commit").symlink_to("/etc/hostname")
        with pytest.raises(WorktreeError, match="non-regular or multiply linked hook entry"):
            inspect_owned_hooks_directory(str(hooks))

    def test_inspect_rejects_multiply_linked_hook_entry(self, repo: Repo, tmp_path: Path) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        _write_owned_hooks(hooks, external_link=tmp_path / "external-hook")
        with pytest.raises(WorktreeError, match="non-regular or multiply linked hook entry"):
            inspect_owned_hooks_directory(str(hooks))

    def test_inspect_accepts_regular_entries(self, repo: Repo) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        _write_owned_hooks(hooks)
        marker = inspect_owned_hooks_directory(str(hooks))
        assert marker is not None
        assert marker["hooksPath"] == str(hooks)


class TestEnsure:
    def test_ensure_creates_directory_and_owner_only_files(self, repo: Repo) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        marker_path = ensure_owned_hooks_directory(str(hooks))
        assert marker_path == str(hooks / OWNERSHIP_MARKER)
        assert stat.S_IMODE(hooks.stat().st_mode) == 0o700
        marker = Path(marker_path)
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        assert json.loads(marker.read_text(encoding="utf-8"))["hooksPath"] == str(hooks)

    def test_ensure_preserves_the_marker_of_an_owned_directory(self, repo: Repo) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        hooks.mkdir()
        marker = hooks / OWNERSHIP_MARKER
        marker.write_text(ownership_marker_content("/gone/old-path/hdsh-hooks"), encoding="utf-8")
        (hooks / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
        assert ensure_owned_hooks_directory(str(hooks)) == str(marker)
        assert json.loads(marker.read_text(encoding="utf-8"))["hooksPath"] == (
            "/gone/old-path/hdsh-hooks"
        )

    def test_ensure_rejects_existing_directory_without_marker(self, repo: Repo) -> None:
        hooks = git_dir(repo) / "hdsh-hooks"
        hooks.mkdir()
        with pytest.raises(WorktreeError, match="unowned hooks directory"):
            ensure_owned_hooks_directory(str(hooks))


class TestLockRecords:
    def test_record_owner_parses_complete_records(self) -> None:
        from hdsh.worktree.ownership import _lock_record_may_be_incomplete, _lock_record_owner

        assert _lock_record_owner("123 12345678-1234-1234-1234-123456789012\n") == 123
        assert _lock_record_owner("123 12345678-1234-1234-1234-1234567890AB\n".upper()) == 123
        assert _lock_record_owner("123 12345678-1234-1234-1234-12345678901\n") is None
        assert _lock_record_owner("123 12345678-1234-1234-1234-123456789012") is None
        assert _lock_record_owner("garbage\n") is None
        assert _lock_record_may_be_incomplete("") is True
        assert _lock_record_may_be_incomplete("123") is True
        assert _lock_record_may_be_incomplete("123 deadbee") is True
        assert _lock_record_may_be_incomplete("123 deadbee\n") is False
        assert _lock_record_may_be_incomplete("not an installer lock\n") is False


class TestAcquire:
    def test_stale_lock_fails_loud(self, repo: Repo) -> None:
        lock_path_of(repo).write_text(
            "999999 12345678-1234-1234-1234-123456789012\n", encoding="utf-8"
        )
        with pytest.raises(WorktreeError, match="stale installer lock"):
            install(str(repo.root))
        assert lock_path_of(repo).exists()

    def test_invalid_lock_fails_loud(self, repo: Repo) -> None:
        lock_path_of(repo).write_text("garbage\n", encoding="utf-8")
        with pytest.raises(WorktreeError, match="invalid installer lock"):
            install(str(repo.root))

    def test_invalid_non_regular_lock_fails_loud(self, repo: Repo) -> None:
        lock_path_of(repo).symlink_to(repo.root / "elsewhere")
        with pytest.raises(WorktreeError, match="invalid installer lock"):
            install(str(repo.root))

    def test_lock_timeout_waiting_for_live_owner(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hdsh.worktree import ownership as ownership_module

        lock_path_of(repo).write_text(
            f"{os.getpid()} 12345678-1234-1234-1234-123456789012\n", encoding="utf-8"
        )

        # A shortened wall-clock deadline and a no-op sleep converge immediately.
        monkeypatch.setattr(ownership_module, "INSTALL_LOCK_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(time, "sleep", _no_sleep)
        with pytest.raises(WorktreeError, match="timed out waiting"):
            install(str(repo.root))

    def test_lock_disappears_between_attempts(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = lock_path_of(repo)
        lock.write_text(f"{os.getpid()} 12345678-1234-1234-1234-123456789012\n", encoding="utf-8")

        def vanishing_sleep(seconds: float) -> None:
            lock.unlink()

        monkeypatch.setattr(time, "sleep", vanishing_sleep)
        install(str(repo.root))
        assert not lock.exists()

    def test_incomplete_record_waits_for_owner_then_times_out(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hdsh.worktree import ownership as ownership_module

        lock = lock_path_of(repo)
        lock.write_text("", encoding="utf-8")

        def completing_sleep(seconds: float) -> None:
            lock.write_text(
                f"{os.getpid()} 12345678-1234-1234-1234-123456789012\n", encoding="utf-8"
            )

        # A live owner completes the record: the installer waits, then times out.
        monkeypatch.setattr(ownership_module, "INSTALL_LOCK_TIMEOUT_SECONDS", 0.3)
        monkeypatch.setattr(time, "sleep", completing_sleep)
        with pytest.raises(WorktreeError, match="timed out waiting"):
            install(str(repo.root))

    def test_initialization_window_expires_for_stuck_records(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = lock_path_of(repo)
        lock.write_text("12345 deadbeef", encoding="utf-8")
        real_monotonic = time.monotonic
        calls = {"n": 0}

        def advancing_monotonic() -> float:
            calls["n"] += 1
            return real_monotonic() + 6.0 * calls["n"]

        monkeypatch.setattr(time, "monotonic", advancing_monotonic)
        monkeypatch.setattr(time, "sleep", _no_sleep)
        with pytest.raises(WorktreeError, match="invalid installer lock"):
            install(str(repo.root))

    def test_lock_owner_alive_via_permission_error(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hdsh.worktree import ownership as ownership_module

        lock_path_of(repo).write_text(
            f"{os.getpid()} 12345678-1234-1234-1234-123456789012\n", encoding="utf-8"
        )

        def permission_denied(pid: int, sig: int) -> None:
            raise PermissionError

        monkeypatch.setattr(os, "kill", permission_denied)
        monkeypatch.setattr(ownership_module, "INSTALL_LOCK_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(time, "sleep", _no_sleep)
        with pytest.raises(WorktreeError, match="timed out waiting"):
            install(str(repo.root))

    def test_lock_vanishes_before_the_first_stat(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hdsh.worktree import ownership as ownership_module

        lock = lock_path_of(repo)
        lock.write_text("someone\n", encoding="utf-8")
        real_lstat = ownership_module.lstat_if_present
        calls = {"n": 0}

        def vanishing(path: str | Path) -> os.stat_result | None:
            calls["n"] += 1
            if calls["n"] == 1:
                lock.unlink()
                return None
            return real_lstat(path)

        monkeypatch.setattr(ownership_module, "lstat_if_present", vanishing)
        install(str(repo.root))
        assert not lock.exists()

    def test_lock_record_read_vanishes(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:

        lock = lock_path_of(repo)
        lock.write_text("12345 deadbeef", encoding="utf-8")
        real_read_text = Path.read_text
        calls = {"n": 0}

        def vanishing_read(target: Path, *args: Any, **kwargs: Any) -> str:
            if target == lock:
                calls["n"] += 1
                if calls["n"] == 1:
                    lock.unlink()
                    raise FileNotFoundError(str(lock))
            return real_read_text(target, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", vanishing_read)
        install(str(repo.root))
        assert not lock.exists()

    def test_lock_verifying_stat_vanishes(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hdsh.worktree import ownership as ownership_module

        lock = lock_path_of(repo)
        lock.write_text("12345 deadbeef", encoding="utf-8")
        real_lstat = ownership_module.lstat_if_present
        calls = {"n": 0}

        def vanishing_second(path: str | Path) -> os.stat_result | None:
            calls["n"] += 1
            if calls["n"] == 2:
                lock.unlink()
                return None
            return real_lstat(path)

        monkeypatch.setattr(ownership_module, "lstat_if_present", vanishing_second)
        install(str(repo.root))
        assert not lock.exists()

    def test_lock_verify_sees_a_symlinked_replacement(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from hdsh.worktree import ownership as ownership_module

        lock = lock_path_of(repo)
        lock.write_text("12345 deadbeef", encoding="utf-8")
        external = tmp_path / "external-lock"
        external.write_text("12345 deadbeef\n", encoding="utf-8")
        real_lstat = ownership_module.lstat_if_present
        calls = {"n": 0}

        def swapped_second(path: str | Path) -> os.stat_result | None:
            calls["n"] += 1
            if calls["n"] == 2:
                lock.unlink()
                lock.symlink_to(external)
            return real_lstat(path)

        monkeypatch.setattr(ownership_module, "lstat_if_present", swapped_second)
        with pytest.raises(WorktreeError, match="invalid installer lock"):
            install(str(repo.root))

    def test_lock_verify_sees_a_replaced_inode_then_proceeds(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hdsh.worktree import ownership as ownership_module

        lock = lock_path_of(repo)
        lock.write_text("12345 deadbeef", encoding="utf-8")
        real_lstat = ownership_module.lstat_if_present
        calls = {"n": 0}

        def flaky(path: str | Path) -> os.stat_result | None:
            calls["n"] += 1
            if calls["n"] == 2:
                # The verifying stat names a different inode than the first one.
                result = real_lstat(path)
                assert result is not None
                return os.stat_result((result.st_mode, result.st_ino + 1, *tuple(result)[2:]))
            if calls["n"] == 3:
                lock.unlink()
                return None
            return real_lstat(path)

        monkeypatch.setattr(ownership_module, "lstat_if_present", flaky)
        install(str(repo.root))
        assert not lock.exists()

    def test_published_stat_mismatch_refuses_acquisition(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hdsh.worktree import ownership as ownership_module

        real_lstat = ownership_module.lstat_if_present
        tampered = {"used": False}

        def skewed(path: str | Path) -> os.stat_result | None:
            result = real_lstat(path)
            if result is not None and not tampered["used"]:
                tampered["used"] = True
                return os.stat_result(
                    (result.st_mode, result.st_ino + 1, *tuple(result)[2:]),
                )
            return result

        monkeypatch.setattr(ownership_module, "lstat_if_present", skewed)
        with pytest.raises(WorktreeError, match="installer lock ownership changed"):
            acquire_install_lock(str(common_dir(repo)))

    def test_acquired_lock_is_owner_only(self, repo: Repo) -> None:
        _, record, owned_stat = acquire_install_lock(str(common_dir(repo)))
        lock = lock_path_of(repo)
        try:
            assert stat.S_IMODE(lock.stat().st_mode) == 0o600
            assert record.startswith(f"{os.getpid()} ")
            assert record.endswith("\n")
            assert len(record.split(" ")[1].strip()) == 36
            assert stat.S_ISREG(owned_stat.st_mode)
        finally:
            release_install_lock(lock, record, owned_stat)


class TestRelease:
    def test_release_removes_owned_lock(self, repo: Repo) -> None:
        lock = lock_path_of(repo)
        _, record, owned_stat = acquire_install_lock(str(common_dir(repo)))
        release_install_lock(lock, record, owned_stat)
        assert not lock.exists()

    def test_release_refuses_when_content_read_vanishes(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = lock_path_of(repo)
        _, record, owned_stat = acquire_install_lock(str(common_dir(repo)))
        real_read_text = Path.read_text

        def vanishing_read(target: Path, *args: Any, **kwargs: Any) -> str:
            if target == lock:
                lock.unlink()
                raise FileNotFoundError(str(lock))
            return real_read_text(target, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", vanishing_read)
        with pytest.raises(WorktreeError, match="ownership changed"):
            release_install_lock(lock, record, owned_stat)

    def test_release_refuses_when_unlink_vanishes(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = lock_path_of(repo)
        _, record, owned_stat = acquire_install_lock(str(common_dir(repo)))

        def vanishing_unlink(target: Path, *args: object) -> None:
            raise FileNotFoundError(str(target))

        monkeypatch.setattr(Path, "unlink", vanishing_unlink)
        with pytest.raises(WorktreeError, match="ownership changed"):
            release_install_lock(lock, record, owned_stat)

    def test_release_refuses_when_content_changed(self, repo: Repo) -> None:
        lock = lock_path_of(repo)
        _, record, owned_stat = acquire_install_lock(str(common_dir(repo)))
        lock.write_text("someone else\n", encoding="utf-8")
        with pytest.raises(WorktreeError, match="ownership changed"):
            release_install_lock(lock, record, owned_stat)

    def test_release_refuses_when_inode_changed(self, repo: Repo) -> None:
        lock = lock_path_of(repo)
        _, record, owned_stat = acquire_install_lock(str(common_dir(repo)))
        forged = os.stat_result((owned_stat.st_mode, owned_stat.st_ino + 1, *tuple(owned_stat)[2:]))
        with pytest.raises(WorktreeError, match="ownership changed"):
            release_install_lock(lock, record, forged)

    def test_release_refuses_when_file_missing(self, repo: Repo) -> None:
        lock = lock_path_of(repo)
        _, record, owned_stat = acquire_install_lock(str(common_dir(repo)))
        lock.unlink()
        with pytest.raises(WorktreeError, match="ownership changed"):
            release_install_lock(lock, record, owned_stat)

    def test_release_refuses_symlinked_lock(self, repo: Repo, tmp_path: Path) -> None:
        lock = lock_path_of(repo)
        _, record, owned_stat = acquire_install_lock(str(common_dir(repo)))
        lock.unlink()
        external = tmp_path / "external-lock"
        external.write_text(record, encoding="utf-8")
        lock.symlink_to(external)
        with pytest.raises(WorktreeError, match="ownership changed"):
            release_install_lock(lock, record, owned_stat)


class TestInstallLockIntegration:
    def test_success_releases_lock(self, repo: Repo) -> None:
        install(str(repo.root))
        assert not lock_path_of(repo).exists()

    def test_lock_release_failure_is_reported_with_installation_error(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_prek(root: str) -> None:
            raise WorktreeError("prek exploded")

        def failing_release(lock_path: Path, record: str, owned_stat: os.stat_result) -> None:
            raise WorktreeError("lock release exploded")

        monkeypatch.setattr(worktree_install, "run_prek", failing_prek)
        monkeypatch.setattr(worktree_install, "release_install_lock", failing_release)
        with pytest.raises(WorktreeError, match="prek exploded.*lock release exploded"):
            install(str(repo.root))
