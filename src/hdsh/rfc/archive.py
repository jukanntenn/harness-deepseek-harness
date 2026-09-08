"""Verify and append-seal the frozen RFC archive under ``.agents/rfcs/archived/``.

The seal contract lives in ``.agents/rfcs/README.md``: complete
English/Chinese/sidecar triplets inside the closed class tree, sealed
headers, sidecar hashes that match the archived bytes, and an append-only
content manifest whose sealed entries never change. ``hdsh rfc archive``
verifies; ``hdsh rfc seal`` proves every existing seal unchanged and appends
hashes for newly archived artifacts only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from hdsh.rfc.tree import ARCHIVED_LIFECYCLE, CLASS_FOLDERS, NOTES_ROOT

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh rfc"

#: Environment variable carrying CI's trusted pre-change commit; local runs
#: compare against ``HEAD``.
BASE_REF_ENVIRONMENT = "HDSH_ARCHIVE_BASE_REF"
DEFAULT_BASE_REF = "HEAD"

MANIFEST_NAME = "manifest.json"
_ALLOWED_ROOT_FILES = frozenset({"AGENTS.md", MANIFEST_NAME})

SEALED_TITLE = re.compile(r"^# RFC: \S")
SEALED_DATE = re.compile(r"^Archived: (\d{4})-(\d{2})-(\d{2})$", re.MULTILINE)
ARTIFACT_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2}-[a-z0-9-]+)(\.zh\.md|\.i18n\.yaml|\.md)$")
_SIDECAR_LINE = re.compile(r"^([^:#]+\.md): ([0-9a-f]{40})$")
_SEALED_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_SIDECAR_SIDES = 2


@dataclass(frozen=True)
class ArchiveManifest:
    """The versioned frozen-content manifest of the archive."""

    #: Manifest schema version; only 1 exists.
    version: int
    #: Content hash per archive-relative artifact path.
    files: dict[str, str] = field(default_factory=dict)


def archive_content_hash(content: bytes) -> str:
    """Hash one archived artifact independently of Git's object format.

    Args:
        content: Exact artifact bytes.

    Returns:
        The ``sha256:<hex>`` content hash recorded in the manifest.
    """
    digest = hashlib.sha256()
    digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def blob_hash(content: bytes) -> str:
    """Compute the full git blob hash of archived bytes (``git hash-object``).

    Args:
        content: Exact artifact bytes.

    Returns:
        The 40-hex-digit SHA-1 blob hash the consistency sidecar records.
    """
    digest = hashlib.sha1()  # noqa: S324 - SHA-1 is the git object-hash format
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return digest.hexdigest()


def parse_manifest(content: str) -> ArchiveManifest:
    """Parse the archive manifest and reject anything outside its closed schema.

    Args:
        content: Complete manifest file text.

    Returns:
        The parsed manifest.

    Raises:
        ValueError: When the text is not valid JSON or violates the schema.
    """
    try:
        value: object = json.loads(content)
    except json.JSONDecodeError as error:
        msg = f"invalid JSON ({error})"
        raise ValueError(msg) from error
    if not isinstance(value, dict):
        msg = "expected a JSON object"
        raise TypeError(msg)
    if set(value) != {"version", "files"}:
        msg = "expected exactly the fields `version` and `files`"
        raise ValueError(msg)
    if type(value["version"]) is not int or value["version"] != 1:
        msg = "unsupported manifest version (expected 1)"
        raise ValueError(msg)
    files_value = value["files"]
    if not isinstance(files_value, dict):
        msg = "`files` must be an object"
        raise TypeError(msg)
    files: dict[str, str] = {}
    for path, digest in files_value.items():
        if not isinstance(digest, str) or _SEALED_HASH.match(digest) is None:
            msg = f"invalid content hash for {path}"
            raise ValueError(msg)
        files[str(path)] = digest
    return ArchiveManifest(version=1, files=files)


def render_manifest(manifest: ArchiveManifest) -> str:
    """Render the manifest with deterministic path ordering.

    Args:
        manifest: The manifest to render.

    Returns:
        Canonical JSON text with exactly one trailing newline.
    """
    payload = {"version": manifest.version, "files": dict(sorted(manifest.files.items()))}
    return f"{json.dumps(payload, indent=2)}\n"


def manifest_extension_errors(baseline: ArchiveManifest, current: ArchiveManifest) -> list[str]:
    """Reject changes or removals of entries sealed by a prior manifest.

    Args:
        baseline: The manifest at the trusted pre-change commit.
        current: The manifest as read from the working tree.

    Returns:
        Violation messages; an empty list means the manifest only extends.
    """
    errors: list[str] = []
    for path, expected in baseline.files.items():
        actual = current.files.get(path)
        if actual is None:
            errors.append(f"{path}: sealed manifest entry is missing")
        elif actual != expected:
            errors.append(f"{path}: sealed manifest hash changed")
    return errors


def _valid_date(year: str, month: str, day: str) -> bool:
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        return False
    return True


@dataclass
class _Triplet:
    source: bytes | None = None
    zh: bytes | None = None
    meta: bytes | None = None


def _is_regular_file(path: Path) -> bool:
    """Whether the entry itself is a regular file; a symlink is not."""
    return stat.S_ISREG(path.lstat().st_mode)


def _is_directory(path: Path) -> bool:
    """Whether the entry itself is a directory; a symlink is not."""
    return stat.S_ISDIR(path.lstat().st_mode)


def collect_artifacts(archive_root: Path) -> tuple[dict[str, bytes], list[str]]:
    """Walk the archive tree and apply its closed structural rules.

    Regular-file and directory membership is decided on the directory entry
    itself, so symlinks fail both checks whatever they point at. Absent class
    directories stay green: git cannot track the empty ones, and a
    repository's archive starts empty (the sealed-archive RFC records that
    adaptation).

    Args:
        archive_root: The ``archived/`` directory.

    Returns:
        The artifact bytes keyed by archive-relative path, and structural
        violation messages.
    """
    errors: list[str] = []
    if not (archive_root / "AGENTS.md").exists():
        errors.append("archived/AGENTS.md is required")
    artifacts: dict[str, bytes] = {}
    for entry in sorted(archive_root.iterdir()):
        if _is_regular_file(entry):
            if entry.name not in _ALLOWED_ROOT_FILES:
                errors.append(f"archived/{entry.name}: unexpected root file")
            continue
        if not _is_directory(entry):
            errors.append(f"archived/{entry.name}: only regular files and class directories")
            continue
        if entry.name not in CLASS_FOLDERS:
            errors.append(f"archived/{entry.name}/: unknown RFC class")
            continue
        for child in sorted(entry.iterdir()):
            relative = f"{entry.name}/{child.name}"
            if not _is_regular_file(child):
                errors.append(f"{relative}: archived class directories contain regular files only")
                continue
            artifacts[relative] = child.read_bytes()
    return artifacts, errors


def _sidecar_entries(content: str) -> dict[str, str] | None:
    entries: dict[str, str] = {}
    for line in content.split("\n"):
        if line == "" or line.startswith("#"):
            continue
        match = _SIDECAR_LINE.match(line)
        if match is None:
            return None
        entries[match.group(1)] = match.group(2)
    return entries


def _sealed_header_errors(
    path: str, content: bytes, source_base: str, *, chinese: bool
) -> list[str]:
    errors: list[str] = []
    lines = (content.decode("utf-8").split("\n") + [""] * 6)[:6]
    if SEALED_TITLE.match(lines[0]) is None:
        errors.append(f"{path}: line 1 must be `# RFC: <title>`")
    if lines[1] != "":
        errors.append(f"{path}: line 2 must be blank")
    if lines[2] != "Status: implemented":
        errors.append(f"{path}: line 3 must be `Status: implemented`")
    archived = SEALED_DATE.match(lines[3])
    if archived is None or not _valid_date(archived.group(1), archived.group(2), archived.group(3)):
        errors.append(f"{path}: line 4 must be `Archived: YYYY-MM-DD` with a valid date")
    else:
        archived_date = "-".join(archived.groups())
        if archived_date < source_base[:10]:
            errors.append(f"{path}: archive date {archived_date} predates the RFC filename")
    if lines[4] != "":
        errors.append(f"{path}: line 5 must be blank")
    if chinese:
        switcher = f"[English]({source_base}.md) | 中文"
    else:
        switcher = f"English | [中文]({source_base}.zh.md)"
    if lines[5] != switcher:
        errors.append(f"{path}: line 6 must be {switcher!r}")
    return errors


def validate_artifacts(artifacts: dict[str, bytes]) -> list[str]:
    """Validate sealed headers and complete triplets over collected artifacts.

    Args:
        artifacts: Artifact bytes keyed by ``{class}/yyyy-mm-dd-topic.…``.

    Returns:
        Violation messages; an empty list means every triplet is sealed well.
    """
    errors: list[str] = []
    triplets: dict[str, _Triplet] = {}
    for path, content in artifacts.items():
        match = ARTIFACT_NAME.match(path.rsplit("/", 1)[-1])
        if match is None:
            errors.append(f"{path}: expected {{class}}/yyyy-mm-dd-topic.{{md,zh.md,i18n.yaml}}")
            continue
        note_class = path.split("/", 1)[0]
        if note_class not in CLASS_FOLDERS:
            errors.append(f"{path}: unknown RFC class {note_class!r}")
            continue
        key = f"{note_class}/{match.group(1)}"
        triplet = triplets.setdefault(key, _Triplet())
        suffix = match.group(2)
        if suffix == ".md":
            triplet.source = content
        elif suffix == ".zh.md":
            triplet.zh = content
        else:
            triplet.meta = content

    for key in sorted(triplets):
        source_path, zh_path, meta_path = f"{key}.md", f"{key}.zh.md", f"{key}.i18n.yaml"
        triplet = triplets[key]
        if triplet.source is None or triplet.zh is None or triplet.meta is None:
            missing = ", ".join(
                name
                for name, side in (
                    (source_path, triplet.source),
                    (zh_path, triplet.zh),
                    (meta_path, triplet.meta),
                )
                if side is None
            )
            errors.append(f"{key}: incomplete archived triplet; missing {missing}")
            continue
        source, zh, meta = triplet.source, triplet.zh, triplet.meta
        source_base = key.rsplit("/", 1)[-1]
        errors.extend(_sealed_header_errors(source_path, source, source_base, chinese=False))
        errors.extend(_sealed_header_errors(zh_path, zh, source_base, chinese=True))
        source_date = SEALED_DATE.search(source.decode("utf-8"))
        zh_date = SEALED_DATE.search(zh.decode("utf-8"))
        if (
            source_date is not None
            and zh_date is not None
            and (source_date.groups() != zh_date.groups())
        ):
            errors.append(
                f"{key}: English and Chinese archive dates differ "
                f"({'-'.join(source_date.groups())} vs {'-'.join(zh_date.groups())})"
            )
        entries = _sidecar_entries(meta.decode("utf-8"))
        if (
            entries is None
            or len(entries) != _SIDECAR_SIDES
            or entries.get(f"{source_base}.md") != blob_hash(source)
            or entries.get(f"{source_base}.zh.md") != blob_hash(zh)
        ):
            errors.append(
                f"{meta_path}: consistency record must contain the current Git blob hashes "
                "of both archived sides"
            )
    return errors


def seal_state(
    manifest: ArchiveManifest, artifacts: dict[str, bytes]
) -> tuple[ArchiveManifest, list[str], list[str]]:
    """Preserve every sealed path/hash and append hashes for new artifacts.

    Args:
        manifest: The manifest as read from the working tree.
        artifacts: Artifact bytes keyed by archive-relative path.

    Returns:
        The extended manifest, newly sealed paths, and violation messages
        for changed or missing sealed artifacts.
    """
    errors: list[str] = []
    files = dict(manifest.files)
    for path, expected in sorted(manifest.files.items()):
        content = artifacts.get(path)
        if content is None:
            errors.append(f"{path}: sealed artifact is missing")
        elif archive_content_hash(content) != expected:
            errors.append(f"{path}: sealed content hash changed")
    added = [path for path in sorted(artifacts) if path not in files]
    for path in added:
        files[path] = archive_content_hash(artifacts[path])
    return ArchiveManifest(version=1, files=files), added, errors


def _git(root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"git exited with status {completed.returncode}"
        raise RuntimeError(detail)
    return completed.stdout


def _head_is_unborn(root: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode != 0


def read_baseline_manifest(root: Path, ref: str, manifest_path: str) -> ArchiveManifest:
    """Read the manifest at one trusted pre-change commit.

    Args:
        root: Repository root path.
        ref: The commit-referring revision to read from.
        manifest_path: Repository-relative manifest path.

    Returns:
        The baseline manifest; empty when the ref predates the manifest, and
        empty for ``HEAD`` on an unborn branch — the first commit cannot
        violate a baseline that does not exist yet.

    Raises:
        RuntimeError: When Git cannot resolve the ref or read the object.
        TypeError: When the baseline manifest root is not a JSON object.
        ValueError: When the baseline manifest violates the schema.
    """
    if ref == DEFAULT_BASE_REF and _head_is_unborn(root):
        return ArchiveManifest(version=1)
    _git(root, ["cat-file", "-e", f"{ref}^{{commit}}"])
    listed = _git(root, ["ls-tree", "--name-only", ref, "--", manifest_path]).strip()
    if listed == "":
        return ArchiveManifest(version=1)
    return parse_manifest(_git(root, ["show", f"{ref}:{manifest_path}"]))


def run(root: Path, *, seal: bool) -> int:
    """Verify — or extend and write — the frozen archive's seal state.

    Args:
        root: Repository root path.
        seal: ``True`` appends new seals after proving existing ones unchanged;
            ``False`` requires every artifact to be sealed already.

    Returns:
        The exit code: 0 green, 1 seal violations found.
    """
    archive_root = root / NOTES_ROOT / ARCHIVED_LIFECYCLE
    manifest_path = archive_root / MANIFEST_NAME
    manifest_repo_path = f"{NOTES_ROOT}/{ARCHIVED_LIFECYCLE}/{MANIFEST_NAME}"
    if not archive_root.is_dir():
        print(f"{TOOL}: no frozen archive")
        return 0

    artifacts, errors = collect_artifacts(archive_root)
    errors.extend(validate_artifacts(artifacts))

    manifest = ArchiveManifest(version=1)
    if manifest_path.is_file():
        try:
            manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))
        except (TypeError, ValueError) as error:
            errors.append(f"archived/{MANIFEST_NAME}: {error}")
    elif not seal:
        errors.append(
            f"archived/{MANIFEST_NAME} is required; seal new artifacts with `{TOOL} seal`"
        )

    baseline_ref = os.environ.get(BASE_REF_ENVIRONMENT, DEFAULT_BASE_REF)
    try:
        baseline = read_baseline_manifest(root, baseline_ref, manifest_repo_path)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        errors.append(f"archived/{MANIFEST_NAME}: cannot read baseline {baseline_ref!r}: {error}")
    else:
        errors.extend(manifest_extension_errors(baseline, manifest))

    extended, added, seal_errors = seal_state(manifest, artifacts)
    errors.extend(seal_errors)
    if not seal:
        unsealed = (f"{path}: archived artifact is not sealed in {MANIFEST_NAME}" for path in added)
        errors.extend(unsealed)
    if errors:
        print(f"{TOOL}: archive rules violated:")
        for error in errors:
            print(f"  {error}")
        return 1

    rendered = render_manifest(extended)
    if seal and (
        not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != rendered
    ):
        manifest_path.write_text(rendered, encoding="utf-8")
    summary = (
        f"sealed {len(added)} new artifact(s); existing seals unchanged."
        if seal
        else f"{len(artifacts)} frozen artifact(s) checked."
    )
    print(f"{TOOL}: {summary}")
    return 0


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``archive`` and ``seal`` command leaves."""
    archive = subparsers.add_parser("archive", help="frozen archive gate")
    archive.set_defaults(handler=main, seal=False)
    seal = subparsers.add_parser("seal", help="append seals for newly archived triplets")
    seal.set_defaults(handler=main, seal=True)


def main(args: argparse.Namespace) -> int:
    """``hdsh rfc archive`` and ``hdsh rfc seal`` entry point."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        )
    except OSError as error:
        print(f"{TOOL}: cannot locate repository root: {error}", file=sys.stderr)
        return 2
    if completed.returncode != 0:
        print(f"{TOOL}: working directory is inside no Git repository", file=sys.stderr)
        return 2
    return run(Path(completed.stdout.strip()), seal=args.seal)
