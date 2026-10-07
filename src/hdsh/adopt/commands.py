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
import posixpath
import re
import subprocess
import sys
import tomllib
import zoneinfo
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hdsh import __version__
from hdsh.adopt import corpus, wizard
from hdsh.adopt.corpus import AdoptParameters
from hdsh.adopt.manifest import (
    MANIFEST_PATH,
    AdoptManifest,
    ManifestError,
    file_digest,
    load_manifest,
    save_manifest,
)
from hdsh.docs.config import effective_scope, parse_docs_manifest
from hdsh.docs.corpus import discover_corpus_files
from hdsh.docs.markdown import document_anchors, hard_wrapped_paragraphs
from hdsh.pairing import verify as pairing_verify
from hdsh.pairing.corpus import corpus_file_predicate
from hdsh.pairing.manifest import parse_manifest as parse_pairing_manifest
from hdsh.policy.config import PolicyConfig

if TYPE_CHECKING:
    from hdsh import cliargs

TOOL = "hdsh adopt"

ACCOUNT_TYPES = ("user", "organization")
SHARED_DESTINATIONS = frozenset({".gitattributes", "prek.toml"})
STANDING_ORDERS_DESTINATIONS = frozenset({"AGENTS.md", "docs/AGENTS.md"})
PLACEHOLDER_MARKER = "TODO(adopt):"
_PENDING_LINK = re.compile(r"\]\(([^)\s]+)\)")
_PENDING_FENCE = re.compile(r"^\s*(?:```|~~~)")

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
    "hdsh-adopt-verify",
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
    #: Adoption date in ``yyyy-mm-dd`` form: derived from the Project time
    #: zone at first apply, reused from the adopt manifest afterwards.
    date: str
    #: Every file write, in installation order.
    writes: tuple[PlannedWrite, ...]
    #: Pair anchors to record in the consumer repository after writing.
    records: tuple[str, ...]
    #: Destinations deliberately not installed, with the reason.
    skipped: tuple[str, ...]
    #: Destinations skipped because a consumer file pre-existed; the manual
    #: merge stays tracked in the manifest until the harness anchors resolve.
    pending_merges: tuple[str, ...]
    #: Per destination and slot, the digest of the guidance this plan
    #: installs — the reset baseline for the next apply.
    slot_guidance: dict[str, dict[str, str]]
    #: Human-readable status lines for plan and apply output.
    notes: tuple[str, ...]


def _blockers_error(blockers: list[Blocker], notes: Iterable[str] = ()) -> AdoptError:
    """Render every blocker into one loud, per-blocker diagnostic.

    Args:
        blockers: The collected blockers.
        notes: The lines already resolved when the blockers struck — parameter
            echoes above all — carried ahead of the diagnostics so a
            blocker-rejected run still shows what the parameters resolved to.

    Returns:
        The error whose message opens with the notes, then the diagnostics.
    """
    details = "\n".join(
        f"- {blocker.subject}: {blocker.reason} {blocker.suggestion}" for blocker in blockers
    )
    prefix = "".join(f"{line}\n" for line in notes)
    return AdoptError(f"{prefix}{len(blockers)} blocker(s) prevent adoption:\n{details}")


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
    """The adopt-managed prek block pinned at one hdsh ref.

    Every managed hook carries the ``hdsh`` group: prek's ``--group``
    filtering excludes ungrouped hooks, so an ungrouped managed block would
    silently vanish from any filtered CI run.
    """
    hooks = ",\n".join(f'  {{ id = "{hook}", groups = ["hdsh"] }}' for hook in _PREK_HOOK_IDS)
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


def _existing_issue_config(root: str, blockers: list[Blocker]) -> PolicyConfig | None:
    """Load a hand-authored or previously adopted ``config.json``.

    Args:
        root: Consumer repository root.
        blockers: Collected blockers; a malformed file appends here.

    Returns:
        The validated configuration, or ``None`` when absent or malformed
        (the appended blocker aborts the run before any write).
    """
    path = Path(root, ".github/issue-management/config.json")
    if not path.exists():
        return None
    try:
        return PolicyConfig.from_json(path.read_text(encoding="utf-8"))
    except ValueError as error:
        blockers.append(
            Blocker(
                ".github/issue-management/config.json",
                f"the existing file is malformed ({error}).",
                "Repair the file or remove it so adopt can render it, then rerun.",
            )
        )
        return None


def _resolve_parameters(
    root: str,
    arguments: argparse.Namespace,
    blockers: list[Blocker],
    echoes: list[str],
) -> AdoptParameters:
    """Validate the flag inputs and derive the resolved parameters.

    An existing ``config.json`` is a binding input: its values become the
    parameters, every passed flag contradicting a file value is a blocker —
    adopt never guesses precedence — and its standard-set statuses are
    checked rather than overwritten. Absent flags derive through the wizard
    (account type and lifecycle actor from the gh identity, the ref from the
    latest upstream release tag, the time zone from the local system zone);
    each resolution is echoed so a default the operator never saw cannot
    pass silently, and a fully flagged run never touches the network.

    Args:
        root: Consumer repository root.
        arguments: Parsed leaf namespace with the adoption parameters.
        blockers: Collected blockers; invalid inputs append here.
        echoes: Resolution echo lines for the plan and apply output.

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
    if arguments.account_type is not None and arguments.account_type not in ACCOUNT_TYPES:
        blockers.append(
            Blocker(
                "--account-type",
                f"{arguments.account_type!r} is not one of {list(ACCOUNT_TYPES)}.",
                "Pass --account-type user or --account-type organization.",
            )
        )
    if arguments.time_zone is not None:
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
    existing = _existing_issue_config(root, blockers)
    if existing is not None:
        echoes.append("parameters resolved from the existing config.json (binding input)")
        for flag, field, flag_value, file_value in (
            ("--account-type", "accountType", arguments.account_type, existing.account_type),
            (
                "--project-number",
                "projectNumber",
                str(arguments.project_number),
                str(existing.project_number),
            ),
            ("--project-title", "projectTitle", arguments.project_title, existing.project_title),
            (
                "--lifecycle-actor",
                "lifecycleActor",
                arguments.lifecycle_actor,
                existing.lifecycle_actor,
            ),
            ("--time-zone", "projectTimeZone", arguments.time_zone, existing.project_time_zone),
            (
                "--priority-field",
                "priorityField",
                arguments.priority_field,
                existing.priority_field,
            ),
            (
                "--start-date-field",
                "startDateField",
                arguments.start_date_field,
                existing.start_date_field,
            ),
        ):
            if flag_value is not None and flag_value != file_value:
                blockers.append(
                    Blocker(
                        flag,
                        f"{flag_value!r} contradicts the existing config.json "
                        f"{field} value {file_value!r}.",
                        "Edit the file or drop the flag; adopt never guesses precedence.",
                    )
                )
        if tuple(existing.statuses) != corpus.STANDARD_STATUSES:
            blockers.append(
                Blocker(
                    ".github/issue-management/config.json",
                    "statuses differ from the standard set the harness governs.",
                    "Align the file with the seven standard statuses, then rerun.",
                )
            )
        return AdoptParameters(
            hdsh_ref=arguments.hdsh_ref,
            owner=owner,
            repository=repository,
            account_type=existing.account_type,
            project_number=existing.project_number,
            project_title=existing.project_title,
            lifecycle_actor=existing.lifecycle_actor,
            time_zone=existing.project_time_zone,
            priority_field=existing.priority_field,
            start_date_field=existing.start_date_field,
            allow_unassigned_owner=existing.allow_unassigned_owner,
            public_blob_root=arguments.public_blob_root
            or f"https://github.com/{owner}/{repository}/blob/main/",
        )
    hdsh_ref = _resolve_or_block(
        lambda: wizard.resolve_hdsh_ref(arguments.hdsh_ref, None), "--hdsh-ref", blockers, echoes
    )
    account_type = _resolve_or_block(
        lambda: wizard.resolve_account_type(arguments.account_type, owner, repository, None),
        "--account-type",
        blockers,
        echoes,
    )
    lifecycle_actor = _resolve_or_block(
        lambda: wizard.resolve_lifecycle_actor(arguments.lifecycle_actor, None),
        "--lifecycle-actor",
        blockers,
        echoes,
    )
    time_zone = _resolve_or_block(
        lambda: wizard.resolve_time_zone(arguments.time_zone),
        "--time-zone",
        blockers,
        echoes,
    )
    return AdoptParameters(
        hdsh_ref=hdsh_ref,
        owner=owner,
        repository=repository,
        account_type=account_type,
        project_number=arguments.project_number,
        project_title=arguments.project_title,
        lifecycle_actor=lifecycle_actor,
        time_zone=time_zone,
        priority_field=arguments.priority_field,
        start_date_field=arguments.start_date_field,
        allow_unassigned_owner=arguments.allow_unassigned_owner,
        public_blob_root=arguments.public_blob_root
        or f"https://github.com/{owner}/{repository}/blob/main/",
    )


def _resolve_or_block(
    resolve: Callable[[], wizard.Resolution], flag: str, blockers: list[Blocker], echoes: list[str]
) -> str:
    """Resolve one parameter, converting wizard failure into a blocker.

    Args:
        resolve: The wizard resolution to run.
        flag: The flag named in the blocker diagnostic.
        blockers: Collected blockers; a failed derivation appends here.
        echoes: Resolution echoes, appended on success.

    Returns:
        The resolved value, or ``""`` when the derivation failed (the
        appended blocker aborts the run before any write).
    """
    try:
        resolution = resolve()
    except wizard.WizardError as error:
        blockers.append(Blocker(flag, f"the parameter could not be derived ({error}).", str(error)))
        return ""
    echoes.append(f"resolved {resolution.echo}")
    return resolution.value


def _pair_writes(anchor: str, installed: frozenset[str], hdsh_ref: str) -> list[PlannedWrite]:
    """Load and transplant one mirrored bilingual pair by its English anchor."""
    writes: list[PlannedWrite] = []
    for source in (anchor, f"{anchor[: -len('.md')]}.zh.md"):
        text = (_MIRRORS_ROOT / source).read_text(encoding="utf-8")
        transplanted = corpus.transplant_markdown(
            text, dest=source, installed=installed, hdsh_ref=hdsh_ref
        )
        writes.append(PlannedWrite(dest=source, content=transplanted.encode("utf-8")))
    return writes


def _adoption_date(time_zone: str, *, now: Callable[[datetime.tzinfo], datetime.datetime]) -> str:
    """The adoption date in the Project's time zone, ``yyyy-mm-dd`` form.

    The first apply derives the date once from the same zone the Project
    uses — never from UTC alone, which can sit a day behind the operator —
    and apply records it in the adopt manifest; re-application reuses the
    recorded date instead of calling here. The clock is injected so the
    hermetic suite can sit one instant on two calendars.

    Args:
        time_zone: The resolved Project time zone.
        now: The clock, returning the current instant in the given zone.

    Returns:
        Today in the Project's zone.
    """
    try:
        zone = zoneinfo.ZoneInfo(time_zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        # An unknown zone already carries a --time-zone blocker that aborts
        # the run; this discarded date only has to stay computable until
        # the blockers surface, so nothing else reaches this handler.
        zone = datetime.UTC
    return now(zone).date().isoformat()


def _preflight(root: str, arguments: argparse.Namespace) -> AdoptionPlan:
    """Validate every precondition and compute the complete write plan.

    Args:
        root: Consumer repository root.
        arguments: Parsed leaf namespace with the adoption parameters.

    Returns:
        The validated plan.

    Raises:
        AdoptError: With one diagnostic per blocker when adoption cannot
            proceed safely.
    """
    blockers: list[Blocker] = []
    notes: list[str] = []
    previous = _load_previous_manifest(root, blockers)
    parameters = _resolve_parameters(root, arguments, blockers, notes)
    if previous is not None and previous.adopt_date:
        today = previous.adopt_date
        notes.append(
            f"adoption date {today} reused from the adopt manifest — the RFC anchor "
            "stays stable across re-application"
        )
    else:
        today = _adoption_date(parameters.time_zone, now=datetime.datetime.now)
    installed = corpus.installed_destinations(today)
    writes: list[PlannedWrite] = []
    records: list[str] = []
    skipped: list[str] = []
    pending_merges: list[str] = []

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
            content = corpus.transplant_markdown(
                content.decode("utf-8"),
                dest=dest,
                installed=installed,
                hdsh_ref=parameters.hdsh_ref,
            ).encode("utf-8")
        writes.append(PlannedWrite(dest=dest, content=content))

    for anchor in corpus.MIRRORED_PAIRS:
        writes.extend(_pair_writes(anchor, installed, parameters.hdsh_ref))
        records.append(anchor)

    consumer_owned: set[str] = set()
    for anchor in corpus.TEMPLATE_PAIRS:
        sides = (anchor, f"{anchor[: -len('.md')]}.zh.md")
        if _consumer_owned_template_pair(root, sides, previous):
            consumer_owned.update(sides)
            notes.append(
                f"{anchor}: a pre-existing document was left untouched together with "
                "its counterpart and its pair record — translate the counterpart from "
                "the real content, then hdsh pairing record after review"
            )

    for template, dest in corpus.TEMPLATE_FILES:
        if dest in consumer_owned:
            continue
        rendered = corpus.map_invocations(
            corpus.render_tokens(
                (_TEMPLATES_ROOT / template).read_text(encoding="utf-8"), parameters, today
            )
        )
        writes.append(PlannedWrite(dest=dest, content=rendered.encode("utf-8")))
        if dest in corpus.TEMPLATE_PAIRS:
            records.append(dest)

    slot_guidance = _plan_slot_templates(root, writes, notes, blockers, previous)

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

    writes, skipped, pending_merges = _plan_clobbers(
        root, writes, skipped, blockers, pending_merges
    )
    if blockers:
        raise _blockers_error(blockers, notes)
    sizing = _pairing_sizing_note(root, writes, records)
    if sizing is not None:
        notes.append(sizing)
    wrap_sizing = _wrap_sizing_note(root, writes)
    if wrap_sizing is not None:
        notes.append(wrap_sizing)
    notes.append(
        "the managed prek hooks carry group 'hdsh'; a CI that filters prek with "
        "--group must include it"
    )
    notes.append(
        "a CI that runs no prek wires the gates itself: prek run --all-files, or "
        "a pinned hdsh install plus the managed gate commands — adopt verify "
        "flags a gate-less CI"
    )
    return AdoptionPlan(
        parameters=parameters,
        date=today,
        writes=tuple(writes),
        records=tuple(records),
        skipped=tuple(skipped),
        pending_merges=tuple(pending_merges),
        slot_guidance=slot_guidance,
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


def _pairing_sizing_note(root: str, writes: list[PlannedWrite], records: list[str]) -> str | None:
    """Summarize the pairing workload the adoption leaves behind.

    Discovery runs over the post-apply corpus: the disk tree plus the
    planned writes, under the pairing manifest this apply installs or finds.
    The count exists because "pair the README" undersells the real corpus —
    every README pair at any depth is auto-discovered and manifest ``roots``
    pull whole subtrees in — and an operator sizing the work from one pair
    discovers the rest only when the gate turns red.

    Args:
        root: Consumer repository root.
        writes: The final planned writes.
        records: English anchors this apply records after writing.

    Returns:
        The sizing note, or ``None`` when no readable pairing manifest
        exists (the consumer-structure checks own that failure elsewhere).
    """
    manifest_write = next(
        (write for write in writes if write.dest == ".hdsh/pairing.manifest.json"), None
    )
    if manifest_write is not None:
        text = manifest_write.content.decode("utf-8")
    else:
        path = Path(root, ".hdsh/pairing.manifest.json")
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
    try:
        manifest = parse_pairing_manifest(text)
    except (TypeError, ValueError):
        return None
    is_corpus_file = corpus_file_predicate(manifest)
    corpus_files = pairing_verify.PairingRepository(root).discover_scope_files(is_corpus_file)
    corpus_files |= {write.dest for write in writes if is_corpus_file(write.dest)}
    sources = {
        file for file in corpus_files if file.endswith(".md") and not file.endswith(".zh.md")
    }
    unpaired = sorted(
        source
        for source in sources
        if f"{source[: -len('.md')]}.zh.md" not in corpus_files and source not in records
    )
    return (
        f"pairing corpus after apply: {len(sources)} English document(s) in scope, "
        f"{len(unpaired)} still need a Chinese counterpart and a record — "
        "hdsh pairing list enumerates them"
    )


def _wrap_sizing_note(root: str, writes: list[PlannedWrite]) -> str | None:
    """Count the reflow work the wrap gate will demand of the pre-existing corpus.

    The wrap rule covers every in-scope document, and an adopted scope cannot
    shrink — a consumer corpus that hard-wraps prose must reflow once, after
    apply. The count exists so that cost is budgeted as one mechanical commit
    instead of discovered as a wall of red after apply.

    Args:
        root: Consumer repository root.
        writes: The final planned writes; their destinations are skipped
            because adoption renders its own bytes already reflowed.

    Returns:
        The sizing note, or ``None`` when no readable docs manifest exists or
        nothing in the pre-existing corpus is hard-wrapped.
    """
    manifest_write = next(
        (write for write in writes if write.dest == ".hdsh/docs.manifest.json"), None
    )
    if manifest_write is not None:
        text = manifest_write.content.decode("utf-8")
    else:
        path = Path(root, ".hdsh/docs.manifest.json")
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
    try:
        manifest = parse_docs_manifest(text)
    except (TypeError, ValueError):
        return None
    planned = {write.dest for write in writes}
    paragraphs = 0
    documents = 0
    for file in discover_corpus_files(Path(root), effective_scope(manifest.markdown_wrap)):
        if file.path in planned:
            continue
        wrapped = list(hard_wrapped_paragraphs(file.abs_path.read_text(encoding="utf-8")))
        if wrapped:
            paragraphs += len(wrapped)
            documents += 1
    if not paragraphs:
        return None
    return (
        f"wrap gate after apply: {paragraphs} hard-wrapped paragraph(s) across "
        f"{documents} pre-existing file(s) must reflow to one physical line per "
        "paragraph — budget one mechanical reflow commit"
    )


def _load_previous_manifest(root: str, blockers: list[Blocker]) -> AdoptManifest | None:
    """Load a previous adoption's manifest, if any, for slot baselines.

    Args:
        root: Consumer repository root.
        blockers: Collected blockers; a malformed manifest appends here.

    Returns:
        The previous manifest, or ``None`` when absent or malformed.
    """
    if not Path(root, MANIFEST_PATH).exists():
        return None
    try:
        return load_manifest(root)
    except ManifestError as error:
        blockers.append(
            Blocker(
                MANIFEST_PATH,
                f"the previous adopt manifest is malformed ({error}).",
                "Repair or remove it, then rerun.",
            )
        )
        return None


def _consumer_owned_template_pair(
    root: str, sides: tuple[str, str], previous: AdoptManifest | None
) -> bool:
    """Whether a template pair collides with documents adoption never wrote.

    Args:
        root: Consumer repository root.
        sides: The pair's English and Chinese destinations.
        previous: The previous adoption's manifest, or ``None`` fresh.

    Returns:
        True when either side exists on disk without a previous adoption
        having installed it — consumer-authored content that a fresh
        counterpart template and a consistency record would immediately
        contradict.
    """
    installed = set(previous.editable) if previous is not None else set()
    return any(Path(root, side).exists() and side not in installed for side in sides)


def _plan_slot_templates(
    root: str,
    writes: list[PlannedWrite],
    notes: list[str],
    blockers: list[Blocker],
    previous: AdoptManifest | None,
) -> dict[str, dict[str, str]]:
    """Plan every slot-template write, preserving or resetting slot values.

    Args:
        root: Consumer repository root.
        writes: Planned writes, appended here.
        notes: Status lines, appended here for preserved and reset slots.
        blockers: Collected blockers; malformed slot text appends here.
        previous: The previous adoption's manifest, or ``None`` fresh.

    Returns:
        The guidance digests this plan installs, per destination and slot.
    """
    recorded = previous.slot_guidance if previous is not None else {}
    guidance_out: dict[str, dict[str, str]] = {}
    for template, dest in corpus.SLOT_TEMPLATE_FILES:
        rendered = corpus.map_invocations((_TEMPLATES_ROOT / template).read_text(encoding="utf-8"))
        target = Path(root, dest)
        try:
            fresh = corpus.parse_slots(rendered)
            existing = (
                corpus.parse_slots(target.read_text(encoding="utf-8")) if target.exists() else {}
            )
        except ValueError as error:
            blockers.append(
                Blocker(
                    dest,
                    f"slot text is malformed ({error}).",
                    "Repair the installed slot markers, then rerun.",
                )
            )
            continue
        values: dict[str, str] = {}
        resets: list[str] = []
        preserved = 0
        for name, guidance in fresh.items():
            digest = file_digest(guidance.encode("utf-8"))
            guidance_out.setdefault(dest, {})[name] = digest
            value = existing.get(name)
            if value is not None and value != guidance:
                if recorded.get(dest, {}).get(name) == digest:
                    values[name] = value
                    preserved += 1
                else:
                    resets.append(name)
                    values[name] = guidance
            else:
                values[name] = guidance
        writes.append(
            PlannedWrite(dest=dest, content=corpus.splice_slots(rendered, values).encode("utf-8"))
        )
        if target.exists():
            if preserved:
                notes.append(f"{dest}: {preserved} consumer slot value(s) preserved")
            if resets:
                notes.append(
                    f"{dest}: upstream changed the {', '.join(sorted(resets))} slot "
                    "guidance; the slot resets — re-fill it"
                )
    return guidance_out


def _plan_clobbers(
    root: str,
    writes: list[PlannedWrite],
    skipped: list[str],
    blockers: list[Blocker],
    pending_merges: list[str],
) -> tuple[list[PlannedWrite], list[str], list[str]]:
    """Refuse to overwrite consumer-owned files; skip an existing root AGENTS.md.

    Args:
        root: Consumer repository root.
        writes: The planned writes, filtered in place by the return value.
        skipped: Skipped-destination notes, appended here.
        blockers: Collected blockers; clobbering files append here.
        pending_merges: Destinations left untouched behind a consumer file,
            appended here for manifest tracking.

    Returns:
        The ``(kept writes, skipped notes, pending merges)`` triple.
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
        if write.dest in corpus.SLOT_TEMPLATE_DESTINATIONS:
            kept.append(write)
            continue
        if write.dest in corpus.CONSUMER_CONFIG_DESTINATIONS:
            skipped.append(
                f"{write.dest}: existing consumer-owned configuration left untouched; "
                "verify checks its structure instead of its bytes"
            )
            continue
        if write.dest in STANDING_ORDERS_DESTINATIONS:
            pending_merges.append(write.dest)
            skipped.append(
                f"{write.dest}: an existing standing-orders file was left untouched; merge the "
                "harness pointers (skills paths, command inventory) into it manually — adopt "
                "verify names the required harness anchors until the merge lands"
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
    return kept, skipped, pending_merges


def _previous_digests(root: str, blockers: list[Blocker]) -> dict[str, str]:
    """Read the installed digests of a previous adoption, if any."""
    previous = _load_previous_manifest(root, blockers)
    return previous.files if previous is not None else {}


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
        else:
            parser.add_argument(
                "--hook",
                action="store_true",
                help="prek-hook mode: a repository without an adoption manifest is a no-op",
            )
        parser.set_defaults(handler=handler)


def _add_adopt_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the shared adoption parameters."""
    parser.add_argument(
        "--hdsh-ref",
        metavar="<ref>",
        default=None,
        help="pinned git ref of harness-deepseek-harness (tag or full SHA)",
    )
    parser.add_argument(
        "--account-type",
        metavar="<flavor>",
        default=None,
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
        default=None,
        help="the identity whose Project mutations the lifecycle trusts",
    )
    parser.add_argument(
        "--time-zone",
        metavar="<zone>",
        default=None,
        help=(
            "IANA time zone of the Project; also fixes the adoption date "
            "(for example Asia/Shanghai)"
        ),
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
    try:
        plan = _preflight(root, args)
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
    try:
        plan = _preflight(root, args)
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
                and write.dest not in corpus.CONSUMER_CONFIG_DESTINATIONS
                and write.dest not in corpus.SLOT_TEMPLATE_DESTINATIONS
            },
            editable=tuple(
                sorted(
                    write.dest
                    for write in plan.writes
                    if write.dest in corpus.EDITABLE_DESTINATIONS
                )
            ),
            pending_merges=plan.pending_merges,
            consumer_config=tuple(sorted(corpus.CONSUMER_CONFIG_DESTINATIONS)),
            slot_templates=tuple(sorted(corpus.SLOT_TEMPLATE_DESTINATIONS)),
            slot_guidance=plan.slot_guidance,
            project_anchor=plan.parameters.project_number,
            adopt_date=plan.date,
        ),
    )
    for line in (*plan.skipped, *plan.notes):
        print(f"{TOOL}: {line}")
    print(f"{TOOL}: installed {len(plan.writes)} file(s); recorded {len(plan.records)} pair(s)")
    print(f"{TOOL}: next: complete the TODO(adopt) placeholders, then run hdsh adopt verify")
    return 0


def _required_anchors(root: str, destination: str, sources: tuple[str, ...]) -> tuple[str, ...]:
    """Every fragment the installed corpus links into one pending destination.

    Args:
        root: Consumer repository root.
        destination: Repository-relative path of the pending merge target.
        sources: Installed corpus files whose links are scanned; fenced code
            blocks are examples, not references, and are skipped.

    Returns:
        The sorted anchor names the manual merge must provide.
    """
    required: set[str] = set()
    for source in sources:
        path = Path(root, source)
        if not path.exists():
            continue
        fenced = False
        for line in path.read_text(encoding="utf-8").split("\n"):
            if _PENDING_FENCE.match(line):
                fenced = not fenced
                continue
            if fenced:
                continue
            for target in _PENDING_LINK.findall(line):
                if "://" in target or target.startswith(("#", "/", "mailto:")):
                    continue
                link_path, separator, fragment = target.partition("#")
                if not separator or not link_path:
                    continue
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), link_path))
                if resolved == destination and fragment:
                    required.add(fragment)
    return tuple(sorted(required))


def _consumer_config_drift(root: str, manifest: AdoptManifest) -> list[str]:
    """Structurally validate every consumer-owned configuration file.

    Byte pinning would defeat the point — the consumer edits these files — so
    verify checks that each loads, that the issue-management configuration
    still names this repository and the standard status set, and lets the
    owning parsers reject everything else at load.

    Args:
        root: Consumer repository root.
        manifest: The recorded adoption state.

    Returns:
        Drift entries for missing or structurally invalid files.
    """
    problems: list[str] = []
    for dest in sorted(manifest.consumer_config):
        path = Path(root, dest)
        if not path.exists():
            problems.append(f"{dest}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        if dest == ".github/issue-management/config.json":
            try:
                config = PolicyConfig.from_json(text)
            except ValueError as error:
                problems.append(f"{dest}: invalid ({error})")
                continue
            slug = _resolve_slug(root)
            if slug is not None and (config.owner, config.repository) != slug:
                problems.append(
                    f"{dest}: owner/repository {config.owner}/{config.repository} "
                    f"does not match the origin remote {slug[0]}/{slug[1]}"
                )
            if tuple(config.statuses) != corpus.STANDARD_STATUSES:
                problems.append(f"{dest}: statuses differ from the standard set")
            if manifest.project_anchor and config.project_number != manifest.project_anchor:
                problems.append(
                    f"{dest}: projectNumber {config.project_number} no longer matches the "
                    f"bound board {manifest.project_anchor}; if the board moved deliberately, "
                    "rerun hdsh adopt apply with the new number to rebind"
                )
        elif dest == ".hdsh/pairing.manifest.json":
            try:
                parse_pairing_manifest(text)
            except (TypeError, ValueError) as error:
                problems.append(f"{dest}: invalid ({error})")
        else:
            try:
                parse_docs_manifest(text)
            except (TypeError, ValueError) as error:
                problems.append(f"{dest}: invalid ({error})")
    return problems


_PREK_GROUP = re.compile(r"--group(?:[= ])(\S+)")
#: One CI line that runs the gates: prek's runner, or a bare hdsh command.
#: Workflow input names like ``hdsh-ref:`` name the tool without invoking it.
_GATE_INVOCATION = re.compile(r"\b(?:prek run|hdsh \w)")


def _workflow_files(root: str) -> list[Path]:
    """List every CI workflow file, empty when the repository has none.

    Args:
        root: Consumer repository root.

    Returns:
        The sorted ``.github/workflows`` YAML paths.
    """
    workflows = Path(root, ".github", "workflows")
    if not workflows.is_dir():
        return []
    return sorted({*workflows.glob("*.yml"), *workflows.glob("*.yaml")})


def _workflow_group_drift(root: str) -> list[str]:
    """Flag ``prek run`` workflow commands whose ``--group`` filter omits ``hdsh``.

    prek's ``--group`` filtering silently drops every hook whose group is not
    listed, so a filtered CI command without the managed ``hdsh`` group never
    runs the adopted gates — the exact silent failure mode the harness exists
    to eliminate. Trailing ``#`` comments are not part of the command.

    Args:
        root: Consumer repository root.

    Returns:
        Drift entries naming each offending workflow line.
    """
    drift: list[str] = []
    for path in _workflow_files(root):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            command = line.split("#", 1)[0]
            if "prek run" not in command or "--group" not in command:
                continue
            if "hdsh" not in _PREK_GROUP.findall(command):
                drift.append(
                    f".github/workflows/{path.name}:{number}: prek run filters --group "
                    "without 'hdsh'; add --group hdsh or drop the filter, or every "
                    "managed gate silently drops out of this command"
                )
    return drift


def _skills_mirror_hint(root: str, manifest: AdoptManifest) -> str | None:
    """The advisory for a skills-mirror layout missing installed skills.

    hdsh owns only ``.agents/skills/``; a consumer tool that mirrors skills
    into another agent's directory direction-agnostically reads the absent
    far side as a deletion, so an unmirrored install is one mirror run away
    from losing every skill. The hint is advisory — the mirror tree is
    consumer-owned, and a missing counterpart is not drift in hdsh's files.

    Args:
        root: Consumer repository root.
        manifest: The adopt manifest naming the installed skill paths.

    Returns:
        The advisory naming the unmirrored skills and the remedy, or
        ``None`` when no mirror directory exists or every installed skill
        has its mirror counterpart.
    """
    if not Path(root, ".claude", "skills").is_dir():
        return None
    installed = sorted(
        path
        for path in (*manifest.files, *manifest.editable, *manifest.slot_templates)
        if path.startswith(".agents/skills/")
    )
    missing = [
        path
        for path in installed
        if not Path(root, ".claude", path.removeprefix(".agents/")).exists()
    ]
    if not missing:
        return None
    return (
        f"a skills mirror exists at .claude/skills/ but {len(missing)} of "
        f"{len(installed)} installed skill file(s) have no counterpart there "
        f"(for example {missing[0]}); a mirror tool that reads the absent far "
        "side as deletion removes them — copy .agents/skills/ to the mirror "
        "side before running it"
    )


def _ci_gate_drift(root: str) -> list[str]:
    """Flag CI workflows that never run an hdsh gate.

    A repository whose CI invokes neither prek nor hdsh enforces nothing
    server-side: the gates run only on machines that installed the worktree
    hooks. Any workflow line naming either tool passes the check — including
    the pinned-install form ``uv tool install … && hdsh pairing verify …``.

    Args:
        root: Consumer repository root.

    Returns:
        One drift entry naming the wiring gap, or empty when the repository
        has no CI at all (a posture choice, not drift).
    """
    paths = _workflow_files(root)
    if not paths:
        return []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if _GATE_INVOCATION.search(line.split("#", 1)[0]):
                return []
    return [
        (
            "CI runs no hdsh gate; wire `prek run --all-files` (with --group hdsh when "
            "filtered) or a pinned hdsh install plus the managed gate commands — "
            "until then the gates run only locally"
        )
    ]


def _invocation_drift(root: str, sources: tuple[str, ...]) -> list[str]:
    """Flag transplanted files still carrying the source invocation form.

    Args:
        root: Consumer repository root.
        sources: Every installed destination adoption owns.

    Returns:
        Drift entries naming each leftover ``uv run hdsh`` line.
    """
    drift: list[str] = []
    for dest in sources:
        path = Path(root, dest)
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if corpus.SOURCE_INVOCATION in line:
                drift.append(
                    f"{dest}:{number}: carries `{corpus.SOURCE_INVOCATION.strip()}` — "
                    "transplanted files run the bare command; rerun hdsh adopt apply"
                )
    return drift


def verify_main(args: argparse.Namespace) -> int:
    """``hdsh adopt verify`` entry point.

    With ``--hook``, a repository without an adoption manifest is a no-op
    success — the always-run hook must not fail where nothing was adopted.
    """
    try:
        root = _repository_root()
    except AdoptError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    try:
        manifest = load_manifest(root)
    except ManifestError as error:
        if args.hook and not Path(root, MANIFEST_PATH).exists():
            print(f"{TOOL}: no adoption manifest; nothing to verify")
            return 0
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 1
    drift: list[str] = _consumer_config_drift(root, manifest)
    drift.extend(_workflow_group_drift(root))
    drift.extend(_ci_gate_drift(root))
    if not _workflow_files(root):
        print(f"{TOOL}: no CI workflows found; the gates run only locally until CI wires them")
    mirror_hint = _skills_mirror_hint(root, manifest)
    if mirror_hint is not None:
        print(f"{TOOL}: {mirror_hint}")
    placeholders: list[str] = []
    pending: list[str] = []
    sources = tuple(
        sorted(manifest.files.keys() | set(manifest.editable) | set(manifest.slot_templates))
    )
    drift.extend(_invocation_drift(root, sources))
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
    for dest in manifest.slot_templates:
        path = Path(root, dest)
        if not path.exists():
            drift.append(f"{dest}: missing")
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if PLACEHOLDER_MARKER in line:
                placeholders.append(f"{dest}:{number}: {line.strip()}")
    for dest in manifest.pending_merges:
        path = Path(root, dest)
        if not path.exists():
            drift.append(f"{dest}: missing")
            continue
        anchors = document_anchors(path.read_text(encoding="utf-8"))
        missing = [
            anchor for anchor in _required_anchors(root, dest, sources) if anchor not in anchors
        ]
        if missing:
            pending.append(
                f"{dest}: manual merge pending — missing harness anchors: "
                + ", ".join(f"#{anchor}" for anchor in missing)
            )
    for line in drift:
        print(f"{TOOL}: {line}", file=sys.stderr)
    for line in placeholders:
        print(f"{TOOL}: {line}")
    for line in pending:
        print(f"{TOOL}: {line}")
    summary = (
        f"{TOOL}: {len(manifest.files)} managed file(s) against hdsh {manifest.hdsh_version} "
        f"({manifest.hdsh_ref})"
    )
    if drift or placeholders or pending:
        print(
            f"{summary}: {len(drift)} drift item(s), {len(placeholders)} placeholder(s), "
            f"{len(pending)} pending merge(s) remain",
            file=sys.stderr,
        )
        return 1
    print(summary)
    return 0
