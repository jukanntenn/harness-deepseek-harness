"""Worktree-config migration and pairing merge-driver registration."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from hdsh.worktree.git import WorktreeError, nul_values, run_git
from hdsh.worktree.ownership import lstat_if_present

_CONFIG_PAIR_FIELDS = 3
REPOSITORY_EXTENSION_PATTERN = re.compile(r"^extensions\.")
PAIRING_MERGE_DRIVER_CONFIG = (
    ("merge.hdsh-pairing.name", "harness-deepseek-harness bilingual pairing records"),
    (
        "merge.hdsh-pairing.driver",
        "scripts/pairing-merge-driver.sh %O %A %B %P",
    ),
)
PAIRING_MERGE_DRIVER_PROBE = ("uv", "run", "--no-sync", "hdsh", "pairing", "merge", "--probe")
_INTEGER = re.compile(r"-?\d+")


def normalized_path(path: str) -> str:
    """Normalize one path, lowercasing it on Windows."""
    normalized = str(Path(path).resolve())
    return normalized.lower() if sys.platform == "win32" else normalized


def direct_config_values(root: str, config_path: str, key: str) -> list[str]:
    """Read every value of one key from one config file, without includes."""
    return nul_values(
        run_git(
            root,
            ["config", "--file", config_path, "--no-includes", "--null", "--get-all", key],
            allow_status=(1,),
        )
    )


def direct_config_matching_entries(
    root: str, config_path: str, pattern: str
) -> list[dict[str, str]]:
    """Read every ``--get-regexp`` key/value pair from one config file, with origins."""
    fields = nul_values(
        run_git(
            root,
            [
                "config",
                "--file",
                config_path,
                "--no-includes",
                "--null",
                "--show-origin",
                "--get-regexp",
                pattern,
            ],
            allow_status=(1,),
        )
    )
    if len(fields) % 2 != 0:
        msg = f"git config returned invalid matching file entries for {pattern}"
        raise WorktreeError(msg)
    entries: list[dict[str, str]] = []
    for index in range(0, len(fields), 2):
        name_value = fields[index + 1]
        separator = name_value.find("\n")
        if separator < 0:
            msg = f"git config returned an invalid name and value for {pattern}"
            raise WorktreeError(msg)
        entries.append(
            {
                "origin": fields[index],
                "name": name_value[:separator],
                "value": name_value[separator + 1 :],
            }
        )
    return entries


def included_config_entries(root: str, config_path: str, key: str) -> list[dict[str, str]]:
    """Read every value of one key from one config file, with includes."""
    fields = nul_values(
        run_git(
            root,
            [
                "config",
                "--file",
                config_path,
                "--includes",
                "--null",
                "--show-origin",
                "--get-all",
                key,
            ],
            allow_status=(1,),
        )
    )
    if len(fields) % 2 != 0:
        msg = f"git config returned invalid file entries for {key}"
        raise WorktreeError(msg)
    return [
        {"origin": fields[index], "value": fields[index + 1]} for index in range(0, len(fields), 2)
    ]


def effective_config_entry(root: str, key: str) -> dict[str, str] | None:
    """Read the effective value of one key with its scope and origin."""
    fields = nul_values(
        run_git(
            root,
            ["config", "--null", "--show-scope", "--show-origin", "--get", key],
            allow_status=(1,),
        )
    )
    if not fields:
        return None
    if len(fields) != _CONFIG_PAIR_FIELDS:
        msg = f"git config returned an invalid scoped value for {key}"
        raise WorktreeError(msg)
    return {"scope": fields[0], "origin": fields[1], "value": fields[2]}


def parse_git_boolean(value: str, key: str) -> bool:
    """Parse one Git Boolean config value, failing loud on anything else."""
    normalized = value.lower()
    if normalized in ("", "true", "yes", "on", "1"):
        return True
    if normalized in ("false", "no", "off", "0"):
        return False
    msg = f"invalid Boolean value for {key}: {value!r}"
    raise WorktreeError(msg)


def assert_single(values: list[str], key: str) -> str | None:
    """Return the only value of one key, refusing multi-valued config."""
    if len(values) > 1:
        msg = f"multiple {key} values are not supported"
        raise WorktreeError(msg)
    return values[0] if values else None


def has_direct_config_entries(root: str, config_path: str) -> bool:
    """Whether one config file carries entries of its own, ignoring includes."""
    return (
        run_git(root, ["config", "--file", config_path, "--no-includes", "--null", "--list"]).stdout
        != ""
    )


def registered_worktree_config_paths(common_directory: str) -> list[str]:
    """Every worktree config file Git may activate for this repository."""
    paths = [str(Path(common_directory, "config.worktree"))]
    linked_directory = Path(common_directory, "worktrees")
    try:
        entries = sorted(os.scandir(linked_directory), key=lambda entry: entry.name)
    except FileNotFoundError:
        return paths
    paths.extend(str(Path(entry.path, "config.worktree")) for entry in entries)
    return paths


def assert_common_config_file(common_config_path: str) -> None:
    """Refuse to write through a common config that is not a regular file."""
    config_stat = lstat_if_present(common_config_path)
    if config_stat is None or not stat.S_ISREG(config_stat.st_mode):
        msg = (
            f"refusing common repository config {common_config_path!r} "
            "because it is not a regular file"
        )
        raise WorktreeError(msg)


def assert_worktree_config_files(
    root: str, common_directory: str, common_config_path: str, current_config_path: str
) -> None:
    """Refuse worktree config files that migration would activate unsafely.

    Args:
        root: Repository root.
        common_directory: Shared git directory of the repository worktrees.
        common_config_path: Shared config file path.
        current_config_path: This worktree's own config file path.

    Raises:
        WorktreeError: When any registered worktree config is a symlink or a
            dormant file carrying user-owned settings.
    """
    extension_enabled = worktree_config_extension_enabled(root, common_config_path)
    for config_path in registered_worktree_config_paths(common_directory):
        config_stat = lstat_if_present(config_path)
        if config_stat is None:
            continue
        if not stat.S_ISREG(config_stat.st_mode):
            state = "active" if extension_enabled else "dormant"
            msg = (
                f"refusing {state} worktree config {config_path!r} because it is not a regular "
                "file; replace it with a regular worktree config or remove it before retrying"
            )
            raise WorktreeError(msg)
        if extension_enabled:
            continue
        if not has_direct_config_entries(root, config_path):
            continue
        owner = (
            "current"
            if normalized_path(config_path) == normalized_path(current_config_path)
            else "sibling"
        )
        msg = (
            f"cannot enable extensions.worktreeConfig while {owner} dormant worktree config "
            f"{config_path!r} contains user-owned settings that enabling the extension would "
            "activate; inspect and migrate those settings, then enable the extension explicitly "
            "or remove them before retrying"
        )
        raise WorktreeError(msg)


def worktree_config_extension_enabled(root: str, common_config_path: str) -> bool:
    """Whether the common config already enables worktree-local config."""
    text = assert_single(
        direct_config_values(root, common_config_path, "extensions.worktreeConfig"),
        "extensions.worktreeConfig",
    )
    return False if text is None else parse_git_boolean(text, "extensions.worktreeConfig")


def _parse_format_version(version_text: str) -> int:
    """Parse one ``core.repositoryFormatVersion`` value like Git's own grammar."""
    stripped = version_text.strip()
    if _INTEGER.fullmatch(stripped):
        return int(stripped)
    if stripped == "":
        return 0
    msg = f"unsupported core.repositoryFormatVersion: {version_text!r}"
    raise WorktreeError(msg)


def plan_worktree_config_migration(root: str, common_config_path: str) -> dict[str, object]:
    """Validate the common config before enabling worktree-local config.

    Args:
        root: Repository root.
        common_config_path: Shared config file path.

    Returns:
        Migration plan carrying the direct ``core.bare`` value, the extension
        state, and the repository format version.

    Raises:
        WorktreeError: When migration preconditions are violated.
    """
    version_text = assert_single(
        direct_config_values(root, common_config_path, "core.repositoryFormatVersion"),
        "core.repositoryFormatVersion",
    )
    if version_text is None:
        msg = f"unsupported core.repositoryFormatVersion: {version_text!r}"
        raise WorktreeError(msg)
    version = _parse_format_version(version_text)
    if version < 0:
        msg = f"unsupported core.repositoryFormatVersion: {version_text!r}"
        raise WorktreeError(msg)

    if version == 0:
        dormant_entries = direct_config_matching_entries(
            root, common_config_path, REPOSITORY_EXTENSION_PATTERN.pattern
        )
        if dormant_entries:
            entry = dormant_entries[0]
            msg = (
                f"cannot upgrade core.repositoryFormatVersion from 0 while dormant repository "
                f"extension {entry['name']} is configured ({entry['origin']}: {entry['value']!r}); "
                "audit and migrate it, then set repository format 1 explicitly before retrying"
            )
            raise WorktreeError(msg)

    extension_enabled = worktree_config_extension_enabled(root, common_config_path)
    worktree_text = assert_single(
        direct_config_values(root, common_config_path, "core.worktree"), "core.worktree"
    )
    if worktree_text is not None:
        msg = (
            "cannot enable extensions.worktreeConfig while core.worktree is in the common "
            f"config (file:{common_config_path}: {worktree_text!r}); "
            "move it to the main worktree config first"
        )
        raise WorktreeError(msg)
    bare_text = assert_single(
        direct_config_values(root, common_config_path, "core.bare"), "core.bare"
    )
    direct_bare = None if bare_text is None else parse_git_boolean(bare_text, "core.bare")
    if direct_bare is True:
        msg = (
            "cannot enable extensions.worktreeConfig for a common config with core.bare=true "
            f"(file:{common_config_path}: {bare_text!r})"
        )
        raise WorktreeError(msg)
    return {"directBare": direct_bare, "extensionEnabled": extension_enabled, "version": version}


def apply_worktree_config_migration(
    root: str, common_config_path: str, migration: dict[str, object]
) -> None:
    """Apply one validated migration plan to the common config."""
    if migration["version"] == 0:
        run_git(root, ["config", "--file", common_config_path, "core.repositoryFormatVersion", "1"])
    if not migration["extensionEnabled"]:
        run_git(root, ["config", "--file", common_config_path, "extensions.worktreeConfig", "true"])
    if migration["directBare"] is False:
        run_git(root, ["config", "--file", common_config_path, "--unset-all", "core.bare"])


def origin_is_file(origin: str, root: str, config_path: str) -> bool:
    """Whether one ``--show-origin`` entry names exactly ``config_path``."""
    if not origin.startswith("file:"):
        return False
    origin_path = origin[len("file:") :]
    absolute = (
        origin_path
        if Path(origin_path).is_absolute()
        else str((Path(root) / origin_path).resolve())
    )
    return normalized_path(absolute) == normalized_path(config_path)


def _unset_worktree_config(root: str, key: str) -> None:
    run_git(root, ["config", "--worktree", "--unset-all", key], allow_status=(5,))


def install_pairing_merge_driver(root: str, worktree_config_path: str) -> list[str]:
    """Register the pairing merge driver as worktree-local config.

    Args:
        root: Repository root.
        worktree_config_path: Worktree config file path.

    Returns:
        The keys this call added, for rollback.

    Raises:
        WorktreeError: When a foreign or conflicting value exists, or when the
            registration could not be rolled back after a failure.
    """
    added: list[str] = []
    try:
        for key, expected in PAIRING_MERGE_DRIVER_CONFIG:
            entries = included_config_entries(root, worktree_config_path, key)
            included_foreign = next(
                (e for e in entries if not origin_is_file(e["origin"], root, worktree_config_path)),
                None,
            )
            if included_foreign is not None:
                msg = (
                    f"refusing pairing merge-driver config from an included worktree "
                    f"file ({included_foreign['origin']}: {included_foreign['value']!r})"
                )
                raise WorktreeError(msg)
            existing = assert_single([e["value"] for e in entries], f"worktree {key}")
            effective = effective_config_entry(root, key)
            if effective is not None and effective["scope"] == "command":
                msg = (
                    f"refusing command-scoped {key} ({effective['origin']}: "
                    f"{effective['value']!r}); transient configuration cannot be replaced"
                )
                raise WorktreeError(msg)
            if existing is None and effective is not None and effective["value"] != expected:
                msg = (
                    f"refusing to mask inherited {key} ({effective['origin']}: "
                    f"{effective['value']!r}); remove or integrate the custom driver explicitly"
                )
                raise WorktreeError(msg)
            if existing is not None and existing != expected:
                msg = (
                    f"refusing to replace worktree {key} value {existing!r}; remove or "
                    "integrate the custom pairing merge driver explicitly"
                )
                raise WorktreeError(msg)
            if existing is None:
                run_git(root, ["config", "--worktree", key, expected])
                added.append(key)
            installed = included_config_entries(root, worktree_config_path, key)
            if (
                len(installed) != 1
                or installed[0]["value"] != expected
                or not origin_is_file(installed[0]["origin"], root, worktree_config_path)
            ):
                msg = f"new worktree-local {key} did not become the direct worktree value"
                raise WorktreeError(msg)
            effective_after = effective_config_entry(root, key)
            if (
                effective_after is None
                or effective_after["scope"] != "worktree"
                or effective_after["value"] != expected
                or not origin_is_file(effective_after["origin"], root, worktree_config_path)
            ):
                msg = f"new worktree-local {key} did not become the effective direct worktree value"
                raise WorktreeError(msg)
    except Exception as error:
        rollback_errors: list[WorktreeError] = []
        for key in reversed(added):
            try:
                _unset_worktree_config(root, key)
            except WorktreeError as rollback_error:
                rollback_errors.append(rollback_error)
        if rollback_errors:
            detail = "; ".join(str(rollback_error) for rollback_error in rollback_errors)
            msg = (
                f"Pairing merge-driver configuration failed: {error}; "
                f"rollback also failed: {detail}"
            )
            raise WorktreeError(msg) from error
        raise
    return added


def rollback_pairing_merge_driver(root: str, added: list[str]) -> None:
    """Undo one merge-driver registration by unsetting the keys it added.

    Raises:
        WorktreeError: When any rollback unset fails.
    """
    rollback_errors: list[WorktreeError] = []
    for key in reversed(added):
        try:
            _unset_worktree_config(root, key)
        except WorktreeError as rollback_error:
            rollback_errors.append(rollback_error)
    if rollback_errors:
        detail = "; ".join(str(rollback_error) for rollback_error in rollback_errors)
        msg = f"pairing merge-driver rollback failed: {detail}"
        raise WorktreeError(msg)


def environment_without_command_git_config() -> dict[str, str]:
    """Scrub command-scoped ``GIT_CONFIG_*`` variables from the environment."""
    env = dict(os.environ)
    for key in list(env):
        normalized = key.upper()
        git_config_command_keys = {
            "GIT_CONFIG_PARAMETERS",
            "GIT_CONFIG_COUNT",
        }
        if normalized in git_config_command_keys or re.fullmatch(
            r"GIT_CONFIG_(?:KEY|VALUE)_\d+", normalized
        ):
            del env[key]
    return env


def probe_pairing_merge_driver(root: str) -> None:
    """Verify the pairing merge runtime before any config is published.

    Raises:
        WorktreeError: When the probe cannot start or exits unsuccessfully.
    """
    try:
        result = subprocess.run(
            PAIRING_MERGE_DRIVER_PROBE,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        msg = f"hdsh pairing merge --probe failed: {error}"
        raise WorktreeError(msg) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        msg = f"hdsh pairing merge --probe failed: {detail}"
        raise WorktreeError(msg)


def run_prek(root: str) -> None:
    """Run ``prek install --overwrite`` with command-scoped git config scrubbed.

    Raises:
        WorktreeError: When prek cannot start or exits unsuccessfully.
    """
    try:
        result = subprocess.run(
            ["prek", "install", "--overwrite"],
            cwd=root,
            capture_output=True,
            text=True,
            env=environment_without_command_git_config(),
            check=False,
        )
    except OSError as error:
        msg = f"prek install --overwrite failed: {error}"
        raise WorktreeError(msg) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        msg = f"prek install --overwrite failed: {detail}"
        raise WorktreeError(msg)
