"""The ``hdsh adopt`` command leaves: ``plan``, ``apply``, and ``verify``.

Adoption is preflight-then-write: every check runs before any byte lands, and
any blocker aborts the whole run with one diagnostic per blocker — which
file, why it blocks, and the suggested resolution. Generated files are
upstream-owned; a consumer-modified generated file refuses re-application
instead of being overwritten.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import tomllib
import zoneinfo
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hdsh import __version__
from hdsh.adopt import corpus
from hdsh.adopt.corpus import AdoptParameters
from hdsh.adopt.manifest import (
    MANIFEST_PATH,
    AdoptManifest,
    ManifestError,
    file_digest,
    load_manifest,
    save_manifest,
)
from hdsh.pairing import verify as pairing_verify

if TYPE_CHECKING:
    from hdsh import cliargs

TOOL = "hdsh adopt"

ACCOUNT_TYPES = ("user", "organization")
SHARED_DESTINATIONS = frozenset({".gitattributes", "prek.toml"})
PLACEHOLDER_MARKER = "TODO(adopt):"

_MIRRORS_ROOT = Path(__file__).parent / "templates" / "mirrors"
_TEMPLATES_ROOT = Path(__file__).parent / "templates" / "templates"
_GITATTRIBUTES_MAPPING = re.compile(r"^\s*\*\.i18n\.yaml\s+merge=(\S+)")
_HTTPS_REMOTE = re.compile(r"github\.com[/:]([^/:]+)/([^/]+?)(?:\.git)?/?$")
_PREK_HOOK_IDS = (
    "hdsh-pairing-verify",
    "hdsh-rfc-verify",
    "hdsh-rfc-archive",
    "hdsh-docs-wrap",
    "hdsh-docs-links",
    "hdsh-docs-budgets",
)


class AdoptError(ValueError):
    """Adoption cannot proceed; the message carries per-blocker diagnostics."""


@dataclass(frozen=True)
class Blocker:
    """One reason adoption cannot proceed, with the suggested resolution."""

    #: The file or subject the blocker names.
    subject: str
    #: Why adoption cannot proceed.
    reason: str
    #: The suggested resolution.
    suggestion: str


@dataclass(frozen=True)
class PlannedWrite:
    """One file adoption will create or replace."""

    #: Consumer destination path, relative to the repository root.
    dest: str
    #: The exact bytes that will land.
    content: bytes


@dataclass(frozen=True)
class AdoptionPlan:
    """A fully validated installation waiting to be written."""

    #: Resolved parameters every rendered asset derived from.
    parameters: AdoptParameters
    #: Adoption date in ``yyyy-mm-dd`` form.
    date: str
    #: Every file write, in installation order.
    writes: tuple[PlannedWrite, ...]
    #: Pair anchors to record in the consumer repository after writing.
    records: tuple[str, ...]
    #: Destinations deliberately not installed, with the reason.
    skipped: tuple[str, ...]
    #: Human-readable status lines for plan and apply output.
    notes: tuple[str, ...]


def _blockers_error(blockers: list[Blocker]) -> AdoptError:
    """Render every blocker into one loud, per-file diagnostic."""
    details = "\n".join(
        f"- {blocker.subject}: {blocker.reason} {blocker.suggestion}" for blocker in blockers
    )
    return AdoptError(f"{len(blockers)} blocker(s) prevent adoption:\n{details}")


def _run_git(root: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one read-only git query in the repository."""
    return subprocess.run(
        ["git", "-C", root, *arguments], capture_output=True, text=True, check=False
    )


def _repository_root() -> str:
    """Return the absolute work-tree root for the process directory.

    Raises:
        AdoptError: When the process directory is not a git work tree.
    """
    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        error = _blockers_error(
            [
                Blocker(
                    "repository",
                    "the working directory is not a git work tree.",
                    "Run hdsh adopt from the consumer repository root.",
                )
            ]
        )
        raise error
    return probe.stdout.strip()


def _resolve_slug(root: str) -> tuple[str, str] | None:
    """Parse the owner and repository name from the origin remote.

    Returns:
        The ``(owner, repository)`` pair, or ``None`` when the origin remote
        is missing or is not a github.com URL.
    """
    probe = _run_git(root, "remote", "get-url", "origin")
    if probe.returncode != 0:
        return None
    match = _HTTPS_REMOTE.search(probe.stdout.strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


def _managed_prek_block(hdsh_ref: str) -> str:
    """The adopt-managed prek block pinned at one hdsh ref."""
    hooks = ",\n".join(f'  {{ id = "{hook}" }}' for hook in _PREK_HOOK_IDS)
    return (
        f"{corpus.MANAGED_PREK_BEGIN}\n"
        "[[repos]]\n"
        f'repo = "https://github.com/{corpus.HDSH_REPOSITORY}"\n'
        f'rev = "{hdsh_ref}"\n'
        f"hooks = [\n{hooks},\n]\n"
        f"{corpus.MANAGED_PREK_END}"
    )


def _apply_prek_block(existing: str | None, block: str) -> str:
    """Insert or replace the managed block inside the consumer prek.toml."""
    if existing is None:
        return f"{block}\n"
    if corpus.MANAGED_PREK_BEGIN in existing:
        pattern = re.compile(
            re.escape(corpus.MANAGED_PREK_BEGIN) + r".*?" + re.escape(corpus.MANAGED_PREK_END),
            re.DOTALL,
        )
        return pattern.sub(block, existing)
    separator = "" if existing.endswith("\n") or existing == "" else "\n"
    return f"{existing}{separator}{block}\n"


def _gitattributes_driver(existing: str | None) -> str | None:
    """Return the driver ``*.i18n.yaml`` is mapped to, if any mapping exists."""
    if existing is None:
        return None
    for line in existing.splitlines():
        match = _GITATTRIBUTES_MAPPING.match(line)
        if match is not None:
            return match.group(1)
    return None


def _gitattributes_content(existing: str | None) -> str:
    """Return the updated ``.gitattributes`` text, appending the line when absent."""
    if existing is None:
        return f"{corpus.GITATTRIBUTES_DRIVER_LINE}\n"
    if _gitattributes_driver(existing) is not None:
        return existing if existing.endswith("\n") else f"{existing}\n"
    separator = "" if existing.endswith("\n") else "\n"
    return f"{existing}{separator}{corpus.GITATTRIBUTES_DRIVER_LINE}\n"


def _resolve_parameters(
    root: str, arguments: argparse.Namespace, blockers: list[Blocker]
) -> AdoptParameters:
    """Validate the flag inputs and derive the resolved parameters.

    Args:
        root: Consumer repository root.
        arguments: Parsed leaf namespace with the adoption parameters.
        blockers: Collected blockers; invalid inputs append here.

    Returns:
        The parameters, carrying placeholder slugs when the origin remote is
        unusable (the appended blocker aborts the run before any write).
    """
    slug = _resolve_slug(root)
    if slug is None:
        blockers.append(
            Blocker(
                "origin remote",
                "the origin remote is missing or not a github.com URL.",
                "Add a github.com origin remote so adopt can derive owner and repository.",
            )
        )
    owner, repository = slug if slug is not None else ("UNKNOWN", "UNKNOWN")
    if arguments.account_type not in ACCOUNT_TYPES:
        blockers.append(
            Blocker(
                "--account-type",
                f"{arguments.account_type!r} is not one of {list(ACCOUNT_TYPES)}.",
                "Pass --account-type user or --account-type organization.",
            )
        )
    try:
        zoneinfo.ZoneInfo(arguments.time_zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        blockers.append(
            Blocker(
                "--time-zone",
                f"{arguments.time_zone!r} is not a known IANA zone.",
                "Pass the Project time zone, for example Asia/Shanghai.",
            )
        )
    if arguments.project_number < 1:
        blockers.append(
            Blocker(
                "--project-number",
                f"{arguments.project_number} is not a positive project number.",
                "Pass the GitHub Project number backing issue management.",
            )
        )
    return AdoptParameters(
        hdsh_ref=arguments.hdsh_ref,
        owner=owner,
        repository=repository,
        account_type=arguments.account_type,
        project_number=arguments.project_number,
        project_title=arguments.project_title,
        lifecycle_actor=arguments.lifecycle_actor,
        time_zone=arguments.time_zone,
        priority_field=arguments.priority_field,
        start_date_field=arguments.start_date_field,
        allow_unassigned_owner=arguments.allow_unassigned_owner,
        public_blob_root=arguments.public_blob_root
        or f"https://github.com/{owner}/{repository}/blob/main/",
    )


def _pair_writes(anchor: str, installed: frozenset[str], hdsh_ref: str) -> list[PlannedWrite]:
    """Load and rewrite one mirrored bilingual pair by its English anchor."""
    writes: list[PlannedWrite] = []
    for source in (anchor, f"{anchor[: -len('.md')]}.zh.md"):
        text = (_MIRRORS_ROOT / source).read_text(encoding="utf-8")
        rewritten = corpus.rewrite_upstream_links(
            text, dest=source, installed=installed, hdsh_ref=hdsh_ref
        )
        writes.append(PlannedWrite(dest=source, content=rewritten.encode("utf-8")))
    return writes


def _preflight(root: str, arguments: argparse.Namespace, today: str) -> AdoptionPlan:
    """Validate every precondition and compute the complete write plan.

    Args:
        root: Consumer repository root.
        arguments: Parsed leaf namespace with the adoption parameters.
        today: Adoption date in ``yyyy-mm-dd`` form.

    Returns:
        The validated plan.

    Raises:
        AdoptError: With one diagnostic per blocker when adoption cannot
            proceed safely.
    """
    blockers: list[Blocker] = []
    parameters = _resolve_parameters(root, arguments, blockers)
    installed = corpus.installed_destinations(today)
    writes: list[PlannedWrite] = []
    records: list[str] = []
    skipped: list[str] = []
    notes: list[str] = []

    status = _run_git(root, "status", "--porcelain")
    if status.stdout.strip():
        blockers.append(
            Blocker(
                "worktree",
                f"the worktree is dirty ({len(status.stdout.splitlines())} changed path(s)).",
                "Commit or stash, then rerun; adoption never mixes with uncommitted work.",
            )
        )

    _plan_prek(root, parameters.hdsh_ref, blockers, writes)
    _plan_gitattributes(root, blockers, writes, notes)

    for source, dest in corpus.MIRRORED_FILES:
        content = (_MIRRORS_ROOT / source).read_bytes()
        if source.endswith((".md", ".zh.md")):
            content = corpus.rewrite_upstream_links(
                content.decode("utf-8"),
                dest=dest,
                installed=installed,
                hdsh_ref=parameters.hdsh_ref,
            ).encode("utf-8")
        writes.append(PlannedWrite(dest=dest, content=content))

    for anchor in corpus.MIRRORED_PAIRS:
        writes.extend(_pair_writes(anchor, installed, parameters.hdsh_ref))
        records.append(anchor)

    for template, dest in corpus.TEMPLATE_FILES:
        rendered = corpus.render_tokens(
            (_TEMPLATES_ROOT / template).read_text(encoding="utf-8"), parameters, today
        )
        writes.append(PlannedWrite(dest=dest, content=rendered.encode("utf-8")))
        if dest in corpus.TEMPLATE_PAIRS:
            records.append(dest)

    adopt_anchor = corpus.ADOPT_RFC_ANCHOR.format(date=today)
    for template, dest in (
        ("agents/adopt-rfc.md", adopt_anchor),
        ("agents/adopt-rfc.zh.md", f"{adopt_anchor[: -len('.md')]}.zh.md"),
    ):
        rendered = corpus.render_tokens(
            (_TEMPLATES_ROOT / template).read_text(encoding="utf-8"), parameters, today
        )
        writes.append(PlannedWrite(dest=dest, content=rendered.encode("utf-8")))
    records.append(adopt_anchor)

    config = {
        "owner": parameters.owner,
        "accountType": parameters.account_type,
        "repository": parameters.repository,
        "projectNumber": parameters.project_number,
        "projectTitle": parameters.project_title,
        "lifecycleActor": parameters.lifecycle_actor,
        "priorityField": parameters.priority_field,
        "startDateField": parameters.start_date_field,
        "projectTimeZone": parameters.time_zone,
        "allowUnassignedOwner": parameters.allow_unassigned_owner,
        "statuses": list(corpus.STANDARD_STATUSES),
    }
    writes.append(
        PlannedWrite(
            dest=".github/issue-management/config.json",
            content=(json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
    )

    writes, skipped = _plan_clobbers(root, writes, skipped, blockers)
    if blockers:
        raise _blockers_error(blockers)
    return AdoptionPlan(
        parameters=parameters,
        date=today,
        writes=tuple(writes),
        records=tuple(records),
        skipped=tuple(skipped),
        notes=tuple(notes),
    )


def _plan_prek(
    root: str, hdsh_ref: str, blockers: list[Blocker], writes: list[PlannedWrite]
) -> None:
    """Plan the prek configuration change, refusing ambiguity."""
    prek_toml = Path(root, "prek.toml")
    if Path(root, ".pre-commit-config.yaml").exists():
        blockers.append(
            Blocker(
                ".pre-commit-config.yaml",
                "adopt manages prek.toml only; a legacy pre-commit config would fork the gate set.",
                "Migrate .pre-commit-config.yaml to prek.toml, then rerun.",
            )
        )
        return
    existing = prek_toml.read_text(encoding="utf-8") if prek_toml.exists() else None
    if existing is not None:
        try:
            parsed = tomllib.loads(existing)
        except tomllib.TOMLDecodeError as error:
            blockers.append(
                Blocker(
                    "prek.toml",
                    f"not valid TOML ({error}).",
                    "Fix the syntax error, then rerun.",
                )
            )
            return
        repos = parsed.get("repos", [])
        if not isinstance(repos, list):
            blockers.append(
                Blocker(
                    "prek.toml",
                    "the repos key is not an array of repository tables.",
                    "Move the repos entries into [[repos]] table form so the adopt-managed "
                    "block can join them, then rerun.",
                )
            )
            return
        hand_pinned = any(
            isinstance(entry, dict)
            and entry.get("repo") == f"https://github.com/{corpus.HDSH_REPOSITORY}"
            for entry in repos
        )
        if hand_pinned and corpus.MANAGED_PREK_BEGIN not in existing:
            blockers.append(
                Blocker(
                    "prek.toml",
                    "a hand-pinned harness-deepseek-harness entry exists outside the "
                    "adopt-managed block.",
                    "Remove the hand-pinned [[repos]] entry so hdsh adopt can own it, then rerun.",
                )
            )
            return
    updated = _apply_prek_block(existing, _managed_prek_block(hdsh_ref))
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as error:
        blockers.append(
            Blocker(
                "prek.toml",
                f"the managed block would produce invalid TOML ({error}).",
                "Report this as a bug together with your prek.toml contents.",
            )
        )
        return
    writes.append(PlannedWrite(dest="prek.toml", content=updated.encode("utf-8")))


def _plan_gitattributes(
    root: str, blockers: list[Blocker], writes: list[PlannedWrite], notes: list[str]
) -> None:
    """Plan the merge-driver attribute line, refusing foreign mappings."""
    path = Path(root, ".gitattributes")
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    driver = _gitattributes_driver(existing)
    if driver is not None and driver != "hdsh-pairing":
        blockers.append(
            Blocker(
                ".gitattributes",
                f"the pairing record attribute is already mapped to another driver ({driver!r}).",
                "Remove or integrate that mapping, then rerun.",
            )
        )
        return
    if driver is not None:
        notes.append("the .gitattributes pairing driver line is already present")
    writes.append(
        PlannedWrite(
            dest=".gitattributes", content=_gitattributes_content(existing).encode("utf-8")
        )
    )


def _plan_clobbers(
    root: str, writes: list[PlannedWrite], skipped: list[str], blockers: list[Blocker]
) -> tuple[list[PlannedWrite], list[str]]:
    """Refuse to overwrite consumer-owned files; skip an existing root AGENTS.md.

    Args:
        root: Consumer repository root.
        writes: The planned writes, filtered in place by the return value.
        skipped: Skipped-destination notes, appended here.
        blockers: Collected blockers; clobbering files append here.

    Returns:
        The ``(kept writes, skipped notes)`` pair.
    """
    digests = _previous_digests(root, blockers)
    kept: list[PlannedWrite] = []
    for write in writes:
        if write.dest in SHARED_DESTINATIONS:
            kept.append(write)
            continue
        path = Path(root, write.dest)
        if not path.exists():
            kept.append(write)
            continue
        if write.dest == "AGENTS.md":
            skipped.append(
                "AGENTS.md: an existing root AGENTS.md was left untouched; merge the harness "
                "pointers (skills paths, command inventory) into it manually"
            )
            continue
        if write.dest in corpus.EDITABLE_DESTINATIONS:
            skipped.append(
                f"{write.dest}: an installed placeholder template was left untouched; "
                "completing it is consumer-owned work"
            )
            continue
        current = file_digest(path.read_bytes())
        if current == file_digest(write.content):
            kept.append(write)
            continue
        if write.dest in digests and current == digests[write.dest]:
            kept.append(write)
            continue
        suggestion = (
            "Revert the local changes and rerun to take the update, or redirect the change "
            "upstream."
            if write.dest in digests
            else "Move it aside or align it with the planned content, then rerun; adopt never "
            "overwrites consumer-owned files."
        )
        blockers.append(
            Blocker(
                write.dest,
                "the file already exists with content adoption did not write.",
                suggestion,
            )
        )
    return kept, skipped


def _previous_digests(root: str, blockers: list[Blocker]) -> dict[str, str]:
    """Read the installed digests of a previous adoption, if any."""
    if not Path(root, MANIFEST_PATH).exists():
        return {}
    try:
        return load_manifest(root).files
    except ManifestError as error:
        blockers.append(
            Blocker(
                MANIFEST_PATH,
                f"the previous adopt manifest is malformed ({error}).",
                "Repair or remove it, then rerun.",
            )
        )
        return {}


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``plan``, ``apply``, and ``verify`` command leaves."""
    for name, handler, help_text in (
        ("plan", plan_main, "preflight and print the adoption plan"),
        ("apply", apply_main, "write the adoption into this repository"),
        ("verify", verify_main, "check installed files and remaining placeholders"),
    ):
        parser = subparsers.add_parser(name, help=help_text)
        if name != "verify":
            _add_adopt_arguments(parser)
        parser.set_defaults(handler=handler)


def _add_adopt_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the shared adoption parameters."""
    parser.add_argument(
        "--hdsh-ref",
        metavar="<ref>",
        required=True,
        help="pinned git ref of harness-deepseek-harness (tag or full SHA)",
    )
    parser.add_argument(
        "--account-type",
        metavar="<flavor>",
        required=True,
        help="deployment flavor: user or organization",
    )
    parser.add_argument(
        "--project-number",
        metavar="<n>",
        type=int,
        required=True,
        help="GitHub Project number backing issue management",
    )
    parser.add_argument(
        "--project-title",
        metavar="<title>",
        required=True,
        help="GitHub Project title backing issue management",
    )
    parser.add_argument(
        "--lifecycle-actor",
        metavar="<login>",
        required=True,
        help="the identity whose Project mutations the lifecycle trusts",
    )
    parser.add_argument(
        "--time-zone",
        metavar="<zone>",
        required=True,
        help="IANA time zone of the Project (for example Asia/Shanghai)",
    )
    parser.add_argument(
        "--priority-field",
        metavar="<name>",
        default="Priority",
        help="Project field name holding the priority (default: Priority)",
    )
    parser.add_argument(
        "--start-date-field",
        metavar="<name>",
        default="Start date",
        help="Project field name holding the start date (default: Start date)",
    )
    parser.add_argument(
        "--allow-unassigned-owner",
        action="store_true",
        help="allow resolving Issues to be unassigned",
    )
    parser.add_argument(
        "--public-blob-root",
        metavar="<url>",
        default="",
        help="absolute-URL prefix for switcher counterparts (default: derived from origin)",
    )


def plan_main(args: argparse.Namespace) -> int:
    """``hdsh adopt plan`` entry point."""
    try:
        root = _repository_root()
    except AdoptError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    try:
        plan = _preflight(root, args, today)
    except AdoptError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    for write in plan.writes:
        print(f"{TOOL}: would write {write.dest} ({len(write.content)} bytes)")
    for anchor in plan.records:
        print(f"{TOOL}: would record pair {anchor}")
    for line in (*plan.skipped, *plan.notes):
        print(f"{TOOL}: {line}")
    print(f"{TOOL}: {len(plan.writes)} file(s) planned; run hdsh adopt apply to install")
    return 0


def apply_main(args: argparse.Namespace) -> int:
    """``hdsh adopt apply`` entry point."""
    try:
        root = _repository_root()
    except AdoptError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    try:
        plan = _preflight(root, args, today)
    except AdoptError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    for write in plan.writes:
        path = Path(root, write.dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(write.content)
        print(f"{TOOL}: wrote {write.dest}")
    for anchor in plan.records:
        request = pairing_verify.record_request(argparse.Namespace(all=False, anchors=[anchor]))
        if pairing_verify.run_gate(request, root) != 0:
            print(f"{TOOL}: recording {anchor} failed", file=sys.stderr)
            return 1
    save_manifest(
        root,
        AdoptManifest(
            hdsh_version=__version__,
            hdsh_ref=plan.parameters.hdsh_ref,
            files={
                write.dest: file_digest(write.content)
                for write in plan.writes
                if write.dest not in SHARED_DESTINATIONS
                and write.dest not in corpus.EDITABLE_DESTINATIONS
            },
            editable=tuple(
                sorted(
                    write.dest
                    for write in plan.writes
                    if write.dest in corpus.EDITABLE_DESTINATIONS
                )
            ),
        ),
    )
    for line in (*plan.skipped, *plan.notes):
        print(f"{TOOL}: {line}")
    print(f"{TOOL}: installed {len(plan.writes)} file(s); recorded {len(plan.records)} pair(s)")
    print(f"{TOOL}: next: complete the TODO(adopt) placeholders, then run hdsh adopt verify")
    return 0


def verify_main(_args: argparse.Namespace) -> int:
    """``hdsh adopt verify`` entry point."""
    try:
        root = _repository_root()
    except AdoptError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    try:
        manifest = load_manifest(root)
    except ManifestError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    drift: list[str] = []
    placeholders: list[str] = []
    for dest, digest in sorted(manifest.files.items()):
        path = Path(root, dest)
        if not path.exists():
            drift.append(f"{dest}: missing")
            continue
        if file_digest(path.read_bytes()) != digest:
            drift.append(f"{dest}: content differs from the adopted bytes")
    for dest in manifest.editable:
        path = Path(root, dest)
        if not path.exists():
            drift.append(f"{dest}: missing")
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if PLACEHOLDER_MARKER in line:
                placeholders.append(f"{dest}:{number}: {line.strip()}")
    for line in drift:
        print(f"{TOOL}: {line}", file=sys.stderr)
    for line in placeholders:
        print(f"{TOOL}: {line}")
    summary = (
        f"{TOOL}: {len(manifest.files)} managed file(s) against hdsh {manifest.hdsh_version} "
        f"({manifest.hdsh_ref})"
    )
    if drift or placeholders:
        print(
            f"{summary}: {len(drift)} drift item(s), {len(placeholders)} placeholder(s) remain",
            file=sys.stderr,
        )
        return 1
    print(summary)
    return 0
