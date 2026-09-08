"""Orchestration behind ``hdsh worktree install``.

Each git worktree gets its own hook directory inside its private git dir, so
parallel worktrees never share hook state. The installer refuses to mask or
replace user-owned configuration: an inherited ``core.hooksPath`` or a foreign
pairing merge-driver entry fails loud unless explicitly overridden, and every
owned change is rolled back when a later step fails. ``prek install`` writes
its shims into the worktree-local hooks path it honors natively.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from hdsh.worktree.config import (
    apply_worktree_config_migration,
    assert_common_config_file,
    assert_single,
    assert_worktree_config_files,
    effective_config_entry,
    included_config_entries,
    install_pairing_merge_driver,
    normalized_path,
    origin_is_file,
    plan_worktree_config_migration,
    probe_pairing_merge_driver,
    registered_worktree_config_paths,
    rollback_pairing_merge_driver,
    run_prek,
)
from hdsh.worktree.git import WorktreeError, run_git, strip_git_line_terminator
from hdsh.worktree.ownership import (
    HOOKS_DIRECTORY,
    acquire_install_lock,
    assert_supported_git,
    ensure_owned_hooks_directory,
    inspect_owned_hooks_directory,
    parse_ownership_marker,
    release_install_lock,
    update_ownership_marker,
)

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

ALLOW_HOOKS_PATH_OVERRIDE = "HDSH_PREK_ALLOW_HOOKS_PATH_OVERRIDE"
TOOL = "hdsh worktree install"
_KNOWN_INHERITED_SCOPES = ("system", "global", "local")
_REPLACEABLE_SCOPES = ("command", "worktree")


def _refuse_inherited_hooks_path(entry: dict[str, str]) -> NoReturn:
    """Fail loud on a user-owned inherited ``core.hooksPath``."""
    msg = (
        f"refusing to replace user-owned core.hooksPath ({entry['origin']}: "
        f"{entry['value']!r}). Chain those hooks through prek.toml, or, if this inherited "
        f"path may remain active only in other worktrees, rerun with "
        f"{ALLOW_HOOKS_PATH_OVERRIDE}=1"
    )
    raise WorktreeError(msg)


def _refuse_scoped_hooks_path(entry: dict[str, str]) -> NoReturn:
    """Fail loud on a scoped ``core.hooksPath`` that is never replaceable."""
    source = f"{entry['origin']}: {entry['value']!r}"
    if entry["scope"] == "command":
        msg = (
            f"refusing to replace command-scoped core.hooksPath ({source}); "
            f"{ALLOW_HOOKS_PATH_OVERRIDE} cannot override transient command configuration"
        )
        raise WorktreeError(msg)
    if entry["scope"] == "worktree":
        msg = (
            f"refusing to replace worktree-scoped core.hooksPath ({source}); "
            "a worktree-specific custom path must be integrated or removed explicitly"
        )
        raise WorktreeError(msg)
    msg = f"refusing to replace core.hooksPath from unsupported {entry['scope']} scope ({source})"
    raise WorktreeError(msg)


def _is_registered_owned_hooks_path(common_directory: str, hooks_path: str) -> bool:
    """Whether ``hooks_path`` is the owned hooks directory of a registered worktree."""
    normalized_hooks_path = normalized_path(hooks_path)
    is_registered = any(
        normalized_path(str(Path(config_path).parent / HOOKS_DIRECTORY)) == normalized_hooks_path
        for config_path in registered_worktree_config_paths(common_directory)
    )
    if not is_registered:
        return False
    inspected = inspect_owned_hooks_directory(hooks_path)
    return inspected is not None and inspected["hooksPath"] == hooks_path


def install(root: str) -> None:
    """Install worktree-local prek hooks and the pairing merge driver.

    Args:
        root: Repository root (a linked worktree or the main worktree).

    Raises:
        WorktreeError: When any safety precondition fails; owned changes roll
            back before the error surfaces.
    """
    assert_supported_git(run_git(root, ["--version"]).stdout.strip())
    git_directory = strip_git_line_terminator(
        run_git(root, ["rev-parse", "--absolute-git-dir"]).stdout
    )
    common_output = strip_git_line_terminator(
        run_git(root, ["rev-parse", "--git-common-dir"]).stdout
    )
    common_directory = (
        common_output
        if Path(common_output).is_absolute()
        else str(Path(root, common_output).resolve())
    )
    common_config_path = str(Path(common_directory, "config"))
    worktree_config_path = str(Path(git_directory, "config.worktree"))
    hooks_path = str(Path(git_directory, HOOKS_DIRECTORY))

    lock_path, lock_record, lock_stat = acquire_install_lock(common_directory)
    installation_error: Exception | None = None
    try:
        assert_common_config_file(common_config_path)
        assert_worktree_config_files(
            root, common_directory, common_config_path, worktree_config_path
        )
        worktree_entries = included_config_entries(root, worktree_config_path, "core.hooksPath")
        included_entry = next(
            (
                e
                for e in worktree_entries
                if not origin_is_file(e["origin"], root, worktree_config_path)
            ),
            None,
        )
        if included_entry is not None:
            _refuse_scoped_hooks_path({**included_entry, "scope": "worktree"})
        worktree_hooks_value = assert_single(
            [e["value"] for e in worktree_entries], "worktree core.hooksPath"
        )
        owned_hooks_directory: dict[str, str] | None = None
        copied_worktree_path_is_owned = False
        if worktree_hooks_value is not None and worktree_hooks_value != hooks_path:
            owned_hooks_directory = inspect_owned_hooks_directory(hooks_path)
            worktree_path_is_relocated = (
                owned_hooks_directory is not None
                and owned_hooks_directory["hooksPath"] == worktree_hooks_value
            )
            copied_worktree_path_is_owned = (
                not worktree_path_is_relocated
                and _is_registered_owned_hooks_path(common_directory, worktree_hooks_value)
            )
            if not worktree_path_is_relocated and not copied_worktree_path_is_owned:
                _refuse_scoped_hooks_path(
                    {
                        "origin": f"file:{worktree_config_path}",
                        "scope": "worktree",
                        "value": worktree_hooks_value,
                    }
                )
        direct_worktree_path_is_owned = worktree_hooks_value is not None and (
            worktree_hooks_value == hooks_path
            or (
                owned_hooks_directory is not None
                and owned_hooks_directory["hooksPath"] == worktree_hooks_value
            )
            or copied_worktree_path_is_owned
        )
        effective = effective_config_entry(root, "core.hooksPath")
        if effective is not None:
            effective_path_is_owned = (
                effective["scope"] == "worktree"
                and effective["value"] == worktree_hooks_value
                and direct_worktree_path_is_owned
                and origin_is_file(effective["origin"], root, worktree_config_path)
            )
            if not effective_path_is_owned:
                if (
                    effective["scope"] in _REPLACEABLE_SCOPES
                    or effective["scope"] not in _KNOWN_INHERITED_SCOPES
                ):
                    _refuse_scoped_hooks_path(effective)
                if os.environ.get(ALLOW_HOOKS_PATH_OVERRIDE) != "1":
                    _refuse_inherited_hooks_path(effective)
        migration = plan_worktree_config_migration(root, common_config_path)
        marker_path = ensure_owned_hooks_directory(hooks_path)
        owned_hooks_directory = parse_ownership_marker(
            Path(marker_path).read_text(encoding="utf-8")
        )
        if (
            worktree_hooks_value is not None
            and worktree_hooks_value != hooks_path
            and owned_hooks_directory is not None
            and owned_hooks_directory["hooksPath"] != worktree_hooks_value
            and not copied_worktree_path_is_owned
        ):
            msg = f"hooks directory ownership changed while relocating {worktree_hooks_value!r}"
            raise WorktreeError(msg)
        apply_worktree_config_migration(root, common_config_path, migration)

        path_changed = False
        driver_added: list[str] = []
        try:
            probe_pairing_merge_driver(root)
            driver_added = install_pairing_merge_driver(root, worktree_config_path)
            run_git(root, ["config", "--worktree", "core.hooksPath", hooks_path])
            path_changed = worktree_hooks_value != hooks_path
            installed = effective_config_entry(root, "core.hooksPath")
            if (
                installed is None
                or installed["scope"] != "worktree"
                or installed["value"] != hooks_path
                or not origin_is_file(installed["origin"], root, worktree_config_path)
            ):
                msg = (
                    "new worktree-local core.hooksPath did not become the effective "
                    "direct worktree value"
                )
                raise WorktreeError(msg)
            run_prek(root)
            update_ownership_marker(marker_path, hooks_path)
        except Exception as error:
            rollback_errors: list[Exception] = []
            if path_changed:
                try:
                    if worktree_hooks_value is None:
                        run_git(
                            root,
                            ["config", "--worktree", "--unset-all", "core.hooksPath"],
                            allow_status=(5,),
                        )
                    else:
                        run_git(
                            root, ["config", "--worktree", "core.hooksPath", worktree_hooks_value]
                        )
                except WorktreeError as rollback_error:
                    rollback_errors.append(rollback_error)
            try:
                rollback_pairing_merge_driver(root, driver_added)
            except WorktreeError as rollback_error:
                rollback_errors.append(rollback_error)
            if rollback_errors:
                detail = "; ".join(str(rollback_error) for rollback_error in rollback_errors)
                msg = (
                    f"prek hook installation failed: {error}; "
                    f"worktree integration rollback also failed: {detail}"
                )
                raise WorktreeError(msg) from error
            raise
    except Exception as error:
        installation_error = error
        raise
    finally:
        try:
            release_install_lock(lock_path, lock_record, lock_stat)
        except WorktreeError as release_error:
            if installation_error is not None:
                msg = (
                    f"prek hook installation failed: {installation_error}; "
                    f"installer lock release also failed: {release_error}"
                )
                raise WorktreeError(msg) from release_error
            raise


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``install`` command leaf."""
    parser = subparsers.add_parser("install", help="worktree-local prek hooks")
    parser.set_defaults(handler=main)


def main(_args: argparse.Namespace) -> int:
    """``hdsh worktree install`` entry point."""
    if os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true":
        return 0
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        )
    except OSError as error:
        print(f"[{TOOL}] {error}", file=sys.stderr)
        return 1
    if probe.returncode != 0:
        return 0
    try:
        install(strip_git_line_terminator(probe.stdout))
    except WorktreeError as error:
        print(f"[{TOOL}] {error}", file=sys.stderr)
        return 1
    return 0
