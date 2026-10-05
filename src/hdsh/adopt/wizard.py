"""Derivation, binding, preflight, and the Phase 1 checklist for adoption.

Every parameter a consumer cannot know from the command line derives here,
through one injectable transport so the hermetic suite proves each path
offline. Each derivation is echoed — a resolved default the operator never
saw is a silent failure waiting to happen — and every flag remains an
explicit override, so a fully explicit run never touches the network. The
checklist leaf prints the out-of-git Phase 1 enumeration the adoption manual
otherwise only names.
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

from hdsh.adopt.corpus import HDSH_REPOSITORY, STANDARD_STATUSES
from hdsh.policy import rules

TOOL = "hdsh adopt"

#: Sources of one resolved parameter, most to least authoritative.
FLAG = "flag"
CONFIG = "config.json"
DERIVED = "derived"
DEFAULT = "default"

_VERSION_TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")
_LOCAL_TIMEZONE_LINK = "/etc/localtime"

#: gh's own wording for credential rejections; a failure carrying none of
#: these markers keeps its exit status and stderr instead of being read as
#: a missing credential.
_UNAUTHENTICATED_MARKERS: tuple[str, ...] = (
    "gh auth login",
    "http 401",
    "bad credentials",
    "not logged in",
)

#: The shell's exit-status convention for a command absent from PATH.
_COMMAND_NOT_FOUND = 127


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
    suite models an absent tool by omitting it. A command absent from PATH
    answers with the shell's not-found status instead of raising, so every
    caller classifies both absence forms alike.
    """
    if transport is not None:
        key = " ".join(command)
        if key not in transport:
            return subprocess.CompletedProcess(
                command, _COMMAND_NOT_FOUND, stdout="", stderr="not installed"
            )
        return transport[key]
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        # Only an absent executable reaches here: the probe passes no cwd.
        return subprocess.CompletedProcess(
            command, _COMMAND_NOT_FOUND, stdout="", stderr="command not found"
        )


def _gh_failure_detail(probe: subprocess.CompletedProcess[str], command: str) -> str:
    """Explain one failed gh probe without guessing a cause the probe did not name.

    Args:
        probe: The failed probe.
        command: The probe command, quoted into the diagnostic.

    Returns:
        A failure explanation: the absent-tool and rejected-credential
        classes name their remedy; every other exit names the status and
        gh's first stderr line, so a transient network failure is never
        mistaken for a missing credential.
    """
    if probe.returncode == _COMMAND_NOT_FOUND:
        return "gh is not runnable on PATH; install GitHub CLI"
    if any(marker in probe.stderr.lower() for marker in _UNAUTHENTICATED_MARKERS):
        return "gh is not authenticated; run gh auth login"
    first = probe.stderr.strip().splitlines()[0].strip() if probe.stderr.strip() else ""
    detail = f": {first}" if first else ""
    return f"the gh probe failed ({command} exited {probe.returncode}{detail}); rerun if transient"


def resolve_hdsh_ref(explicit: str | None, transport: Transport | None) -> Resolution:
    """Resolve the pinned hdsh ref: the flag, or the latest upstream release tag.

    Tags are read from the upstream repository URL directly, never from the
    consumer's remotes: a consumer that carries its own ``vX.Y.Z`` tags must
    not have them mistaken for hdsh refs.

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
    tags = _run(["git", "ls-remote", "--tags", f"https://github.com/{HDSH_REPOSITORY}"], transport)
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
        WizardError: When no flag was given and the owner type cannot be
            probed — the tool is absent, the credential is rejected, or the
            probe itself fails.
    """
    if explicit is not None:
        return Resolution(explicit, FLAG, f"--account-type {explicit} (flag)")
    probe = _run(["gh", "api", f"repos/{owner}/{repository}", "--jq", ".owner.type"], transport)
    owner_type = probe.stdout.strip()
    if probe.returncode != 0 or owner_type not in ("User", "Organization"):
        detail = (
            _gh_failure_detail(probe, f"gh api repos/{owner}/{repository}")
            if probe.returncode != 0
            else f"the owner type read as {owner_type!r}"
        )
        msg = (
            f"--account-type was not passed and the owner type of {owner}/{repository} "
            f"could not be derived ({detail}); "
            "pass --account-type user or --account-type organization"
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
        WizardError: When no flag was given and the gh identity cannot be
            probed — the tool is absent, the credential is rejected, or the
            probe itself fails.
    """
    if explicit is not None:
        return Resolution(explicit, FLAG, f"--lifecycle-actor {explicit} (flag)")
    probe = _run(["gh", "api", "user", "--jq", ".login"], transport)
    login = probe.stdout.strip()
    if probe.returncode != 0 or not login:
        detail = (
            _gh_failure_detail(probe, "gh api user")
            if probe.returncode != 0
            else "gh api user returned an empty login"
        )
        msg = (
            f"--lifecycle-actor was not passed and {detail}, or pass the Project credential's login"
        )
        raise WizardError(msg)
    return Resolution(login, DERIVED, f"--lifecycle-actor {login} (derived from the gh identity)")


#: gh reports the authenticated token's scopes on lines of this form.
_GH_SCOPE_LINE = "Token scopes: "

_PROJECT_SCOPE_NOTICE = (
    "gh token lacks the 'project' scope; creating the Phase 1 board needs it — "
    "run gh auth refresh -s project (advisory: the workflows' own credentials "
    "are unaffected)"
)


def gh_project_scope_notice(gh_auth_stdout: str) -> str | None:
    """The advisory for disclosed scope lines that never mention ``project``.

    Args:
        gh_auth_stdout: The stdout of a successful ``gh auth status`` probe.

    Returns:
        The advisory naming the remedy, or ``None`` when the token carries
        ``project`` or gh disclosed no scope line to judge — a format the
        parser does not recognize is never guessed at.
    """
    disclosed = []
    for line in gh_auth_stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(_GH_SCOPE_LINE):
            disclosed.append(stripped.removeprefix(_GH_SCOPE_LINE))
    if not disclosed or any("project" in line for line in disclosed):
        return None
    return _PROJECT_SCOPE_NOTICE


def preflight(transport: Transport | None) -> tuple[list[str], list[str]]:
    """Run the local-toolchain preflight layer, one diagnostic per failure.

    Args:
        transport: Injected command results for the hermetic suite.

    Returns:
        The ``(failures, notices)`` pair: failures block adoption, notices
        advise on out-of-toolchain setup the operator may still need.
    """
    failures: list[str] = []
    notices: list[str] = []
    git_version = _run(["git", "--version"], transport)
    if git_version.returncode != 0:
        failures.append("git is not runnable; install Git 2.26 or newer")
    gh_auth = _run(["gh", "auth", "status"], transport)
    if gh_auth.returncode != 0:
        failures.append(_gh_failure_detail(gh_auth, "gh auth status"))
    else:
        notice = gh_project_scope_notice(gh_auth.stdout)
        if notice is not None:
            notices.append(notice)
    hdsh = _run(["hdsh", "--version"], transport)
    if hdsh.returncode != 0:
        failures.append(
            "bare hdsh is not runnable on PATH; host-install it with "
            '`uv tool install "harness-deepseek-harness @ git+<url>@<ref>"` '
            "(until PyPI publishes)"
        )
    rg_version = _run(["rg", "--version"], transport)
    if rg_version.returncode != 0:
        failures.append("ripgrep is not runnable on PATH; install ripgrep (the rg command)")
    return failures, notices


def checklist_lines() -> list[str]:
    """Render the Phase 1 label and board enumeration as copy-pasteable commands."""
    lines = [f"{TOOL}: Phase 1 out-of-git checklist — labels and the Project board"]
    lines.append("labels:")
    lines.extend(
        f'  gh label create {name} --description "{description}"'
        for name, description in rules.LABEL_DESCRIPTIONS.items()
        if name.startswith("kind/")
    )
    lines.append("  user accounts also carry the Issue classification on type/* labels:")
    lines.extend(
        f'  gh label create {name} --description "{description}"'
        for name, description in rules.LABEL_DESCRIPTIONS.items()
        if name.startswith("type/")
    )
    lines.extend(
        f'  gh label create {name} --description "{description}"'
        for name, description in rules.LABEL_DESCRIPTIONS.items()
        if name in rules.PRIORITIES
    )
    lines.append(
        "  area/* labels are consumer-specific: create the initial set for the touched areas"
    )
    lines.append("board (its number is --project-number, its title is --project-title):")
    lines.append("  gh project create --title <title> --owner <owner>")
    lines.append("  gh project link <number> --owner <owner> --repository <repository>")
    lines.append(
        "  statuses on the built-in Status field: "
        + ", ".join(STANDARD_STATUSES)
        + " — gh cannot edit those options; set them in the board UI"
    )
    lines.append(
        "  gh project field-create <number> --owner <owner> --name Priority "
        '--data-type SINGLE_SELECT --single-select-options "' + ",".join(rules.PRIORITIES) + '"'
    )
    lines.append(
        '  gh project field-create <number> --owner <owner> --name "Start date" --data-type DATE'
    )
    lines.append(
        "operator token: board and label work needs the project scope — gh auth refresh -s project"
    )
    lines.append("branch protection: require one approval before merge")
    return lines


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``preflight`` and ``checklist`` command leaves."""
    parser = subparsers.add_parser("preflight", help="check the local adoption toolchain")
    parser.set_defaults(handler=main)
    checklist = subparsers.add_parser(
        "checklist", help="print the Phase 1 label and board enumeration"
    )
    checklist.set_defaults(handler=checklist_main)


def main(args: argparse.Namespace) -> int:  # noqa: ARG001
    """``hdsh adopt preflight`` entry point."""
    failures, notices = preflight(None)
    for notice in notices:
        print(f"{TOOL}: {notice}")
    for failure in failures:
        print(f"{TOOL}: {failure}", file=sys.stderr)
    if failures:
        print(f"{TOOL}: {len(failures)} preflight failure(s)", file=sys.stderr)
        return 1
    print(f"{TOOL}: local toolchain ready (git, gh authenticated, bare hdsh on PATH, rg on PATH)")
    return 0


def checklist_main(_args: argparse.Namespace) -> int:
    """``hdsh adopt checklist`` entry point."""
    for line in checklist_lines():
        print(line)
    return 0
