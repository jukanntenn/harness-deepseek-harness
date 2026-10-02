"""Derivation, binding, and preflight for the guided adoption wizard.

Every parameter a consumer cannot know from the command line derives here,
through one injectable transport so the hermetic suite proves each path
offline. Each derivation is echoed — a resolved default the operator never
saw is a silent failure waiting to happen — and every flag remains an
explicit override, so a fully explicit run never touches the network.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh adopt"

#: Sources of one resolved parameter, most to least authoritative.
FLAG = "flag"
CONFIG = "config.json"
DERIVED = "derived"
DEFAULT = "default"

_VERSION_TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")
_LOCAL_TIMEZONE_LINK = "/etc/localtime"


class WizardError(ValueError):
    """One derivation, binding, or preflight step cannot proceed."""


@dataclass(frozen=True)
class Resolution:
    """One resolved adoption parameter with its provenance."""

    #: The resolved value.
    value: str
    #: Where the value came from: ``flag``, ``config.json``, ``derived``, or ``default``.
    source: str
    #: The human-readable echo naming the parameter, value, and source.
    echo: str


Transport = dict[str, "subprocess.CompletedProcess[str]"]


def _run(command: list[str], transport: Transport | None) -> subprocess.CompletedProcess[str]:
    """Run one probe command, or answer from the injected transport.

    A command missing from the transport is a failing probe: the hermetic
    suite models an absent tool by omitting it.
    """
    if transport is not None:
        key = " ".join(command)
        if key not in transport:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="not installed")
        return transport[key]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def resolve_hdsh_ref(explicit: str | None, transport: Transport | None) -> Resolution:
    """Resolve the pinned hdsh ref: the flag, or the latest upstream release tag.

    Args:
        explicit: The ``--hdsh-ref`` flag value, or ``None`` when absent.
        transport: Injected command results for the hermetic suite.

    Returns:
        The resolution with its echo.

    Raises:
        WizardError: When no flag was given and the upstream carries no
            release tag — there is deliberately no main-HEAD fallback.
    """
    if explicit is not None:
        return Resolution(explicit, FLAG, f"--hdsh-ref {explicit} (flag)")
    tags = _run(["git", "ls-remote", "--tags", "origin"], transport)
    versions: list[tuple[tuple[int, int, int], str]] = []
    for line in tags.stdout.splitlines():
        match = _VERSION_TAG.search(line.strip())
        if match is not None:
            major, minor, patch = (int(part) for part in match.groups())
            versions.append(((major, minor, patch), f"v{major}.{minor}.{patch}"))
    if not versions:
        msg = (
            "--hdsh-ref was not passed and the upstream repository carries no release tag; "
            "pass --hdsh-ref explicitly, or tag an upstream release"
        )
        raise WizardError(msg)
    latest = max(versions)[1]
    return Resolution(latest, DEFAULT, f"--hdsh-ref {latest} (latest upstream release tag)")


def resolve_account_type(
    explicit: str | None, owner: str, repository: str, transport: Transport | None
) -> Resolution:
    """Resolve the deployment flavor from the origin remote's owner type.

    Args:
        explicit: The ``--account-type`` flag value, or ``None`` when absent.
        owner: Owner derived from the origin remote.
        repository: Repository name derived from the origin remote.
        transport: Injected command results for the hermetic suite.

    Returns:
        The resolution with its echo.

    Raises:
        WizardError: When no flag was given and the owner type cannot be read.
    """
    if explicit is not None:
        return Resolution(explicit, FLAG, f"--account-type {explicit} (flag)")
    probe = _run(["gh", "api", f"repos/{owner}/{repository}", "--jq", ".owner.type"], transport)
    owner_type = probe.stdout.strip()
    if probe.returncode != 0 or owner_type not in ("User", "Organization"):
        msg = (
            f"--account-type was not passed and the owner type of {owner}/{repository} "
            "could not be derived; pass --account-type user or --account-type organization"
        )
        raise WizardError(msg)
    flavor = "user" if owner_type == "User" else "organization"
    return Resolution(flavor, DERIVED, f"--account-type {flavor} (derived from the origin remote)")


def resolve_time_zone(explicit: str | None) -> Resolution:
    """Resolve the Project time zone from the operator's local system zone.

    Args:
        explicit: The ``--time-zone`` flag value, or ``None`` when absent.

    Returns:
        The resolution with its echo.

    Raises:
        WizardError: When no flag was given and the local zone has no IANA name.
    """
    if explicit is not None:
        return Resolution(explicit, FLAG, f"--time-zone {explicit} (flag)")
    link = None
    try:
        link = str(Path(_LOCAL_TIMEZONE_LINK).resolve())
    except OSError:
        link = None
    match = re.search(r"/zoneinfo/(.+)$", link or "")
    if match is None:
        msg = (
            "--time-zone was not passed and the local system zone has no IANA name; "
            "pass the Project time zone, for example Asia/Shanghai"
        )
        raise WizardError(msg)
    zone = match.group(1)
    return Resolution(zone, DEFAULT, f"--time-zone {zone} (local system zone)")


def resolve_lifecycle_actor(explicit: str | None, transport: Transport | None) -> Resolution:
    """Resolve the lifecycle actor from the authenticated gh identity.

    The credential that will write Project mutations is the identity the
    lifecycle compares against, so its login — not the operator's guess —
    is the actor.

    Args:
        explicit: The ``--lifecycle-actor`` flag value, or ``None`` when absent.
        transport: Injected command results for the hermetic suite.

    Returns:
        The resolution with its echo.

    Raises:
        WizardError: When no flag was given and gh is not authenticated.
    """
    if explicit is not None:
        return Resolution(explicit, FLAG, f"--lifecycle-actor {explicit} (flag)")
    probe = _run(["gh", "api", "user", "--jq", ".login"], transport)
    login = probe.stdout.strip()
    if probe.returncode != 0 or not login:
        msg = (
            "--lifecycle-actor was not passed and gh is not authenticated; "
            "authenticate gh or pass the Project credential's login"
        )
        raise WizardError(msg)
    return Resolution(login, DERIVED, f"--lifecycle-actor {login} (derived from the gh identity)")


def preflight(transport: Transport | None) -> list[str]:
    """Run the local-toolchain preflight layer, one diagnostic per failure.

    Args:
        transport: Injected command results for the hermetic suite.

    Returns:
        The failure diagnostics; empty means the layer passed.
    """
    failures: list[str] = []
    git_version = _run(["git", "--version"], transport)
    if git_version.returncode != 0:
        failures.append("git is not runnable; install Git 2.26 or newer")
    gh_auth = _run(["gh", "auth", "status"], transport)
    if gh_auth.returncode != 0:
        failures.append("gh is not authenticated; run gh auth login")
    hdsh = _run(["hdsh", "--version"], transport)
    if hdsh.returncode != 0:
        failures.append(
            "bare hdsh is not runnable on PATH; host-install it with "
            "`uv tool install harness-deepseek-harness`"
        )
    return failures


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``preflight`` command leaf."""
    parser = subparsers.add_parser("preflight", help="check the local adoption toolchain")
    parser.set_defaults(handler=main)


def main(args: argparse.Namespace) -> int:  # noqa: ARG001
    """``hdsh adopt preflight`` entry point."""
    failures = preflight(None)
    for failure in failures:
        print(f"{TOOL}: {failure}", file=sys.stderr)
    if failures:
        print(f"{TOOL}: {len(failures)} preflight failure(s)", file=sys.stderr)
        return 1
    print(f"{TOOL}: local toolchain ready (git, gh authenticated, bare hdsh on PATH)")
    return 0
