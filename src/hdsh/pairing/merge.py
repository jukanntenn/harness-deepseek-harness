"""Fail-closed composition of bilingual pairing records during Git merges.

This module owns both the merge-driver entry (``hdsh pairing merge
<ancestor> <current> <other> <repository-path>``, registered by the worktree
installer) and the explicit post-conflict resolver (``hdsh pairing merge
--resolve``).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hdsh.pairing import links as pairing_links
from hdsh.pairing.corpus import is_scope_file, pair_source_predicate
from hdsh.pairing.git import (
    GitError,
    blob_hash,
    git_merge_input_paths,
    read_git_index_blob,
    run_git,
    store_git_blob,
)
from hdsh.pairing.manifest import MANIFEST_PATH, PairingManifest, parse_manifest
from hdsh.pairing.records import (
    PairingRecord,
    PairPaths,
    pair_paths_from_meta,
    parse_record,
    render_record,
)
from hdsh.pairing.structure import (
    parse_markdown,
    structure_diff,
    structure_signature,
)

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh pairing merge"

_UNMERGED_ENTRY = re.compile(r"^(\d+) ([0-9a-f]+) ([123])\t(.+)$", re.DOTALL)
_GIT_MERGE_CONFLICT_MAX_STATUS = 127
_DRIVER_ARG_COUNT = 4

PairSourcePredicate = Callable[[str], bool]


@dataclass(frozen=True)
class PairingMergeResult(PairingRecord):
    """A mechanically composed record and the merged owner contents it names."""

    #: Canonical generated sidecar text.
    record_text: str
    #: Clean three-way merge of the English owner.
    source_content: bytes
    #: Clean three-way merge of the Simplified Chinese owner.
    zh_content: bytes


def _read_git_blob(root: str, object_id: str, owner: str) -> bytes:
    content = run_git(root, ["cat-file", "blob", object_id], f"reading {owner} blob {object_id}")
    if blob_hash(content) != object_id:
        msg = f"{owner} record names {object_id}, which is not its SHA-1 git blob hash"
        raise ValueError(msg)
    return content


def _read_merge_default(root: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", root, "config", "--get", "merge.default"],
            capture_output=True,
            check=False,
        )
    except OSError as error:
        msg = f"reading merge.default failed: {error}"
        raise GitError(msg) from error
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        msg = f"reading merge.default failed with status {result.returncode}: {detail}"
        raise GitError(msg)
    return result.stdout.decode("utf-8").strip()


def _assert_default_text_merge(root: str, paths: PairPaths) -> None:
    output = run_git(
        root,
        ["check-attr", "-z", "merge", "--", paths.source, paths.zh],
        "checking bilingual owner merge attributes",
    ).decode("utf-8")
    fields = output.split("\0")
    fields.pop()
    merge_default: str | None = None
    for index in range(0, len(fields), 3):
        path = fields[index]
        value = fields[index + 2]
        if value not in ("unspecified", "set", "text"):
            msg = (
                f"{path} uses merge={value}; the pairing driver only composes "
                "Git's default text merge"
            )
            raise ValueError(msg)
        if value == "unspecified":
            if merge_default is None:
                merge_default = _read_merge_default(root)
            if merge_default is not None and merge_default != "text":
                msg = (
                    f"{path} inherits merge.default={merge_default}; "
                    "the pairing driver only composes Git's default text merge"
                )
                raise ValueError(msg)


def _run_text_merge(
    root: str,
    label: str,
    ancestor: bytes | str,
    current: bytes | str,
    other: bytes | str,
) -> tuple[bytes, int | None]:
    """Merge three texts with ``git merge-file`` and return output plus status."""
    temporary = tempfile.mkdtemp(prefix="hdsh-pairing-merge-")
    try:
        ancestor_path = os.path.join(temporary, "ancestor")
        current_path = os.path.join(temporary, "current")
        other_path = os.path.join(temporary, "other")
        Path(ancestor_path).write_bytes(_as_bytes(ancestor))
        Path(current_path).write_bytes(_as_bytes(current))
        Path(other_path).write_bytes(_as_bytes(other))
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    root,
                    "merge-file",
                    "-p",
                    "-L",
                    f"{label}:current",
                    "-L",
                    f"{label}:ancestor",
                    "-L",
                    f"{label}:other",
                    current_path,
                    ancestor_path,
                    other_path,
                ],
                capture_output=True,
                check=False,
            )
        except OSError as error:
            msg = f"merging {label} failed: {error}"
            raise GitError(msg) from error
        return result.stdout, result.returncode
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _as_bytes(content: bytes | str) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content


def _merge_blob_triplet(
    root: str, owner: str, ancestor: bytes, current: bytes, other: bytes
) -> bytes:
    output, status = _run_text_merge(root, owner, ancestor, current, other)
    if status != 0:
        kind = (
            "has content conflicts"
            if status is not None and 0 < status <= _GIT_MERGE_CONFLICT_MAX_STATUS
            else f"failed with status {status}"
        )
        raise ValueError(f"{owner} {kind}")
    return output


def _load_record_owners(
    root: str, label: str, content: str, paths: PairPaths
) -> tuple[bytes, bytes]:
    record = parse_record(content, paths)
    if record is None:
        msg = f"{label} {paths.meta} is not a valid two-hash pairing record"
        raise ValueError(msg)
    return (
        _read_git_blob(root, record.source_hash, f"{label} {paths.source}"),
        _read_git_blob(root, record.zh_hash, f"{label} {paths.zh}"),
    )


def _assert_merged_pair_structure(
    root: str,
    paths: PairPaths,
    source: bytes,
    zh: bytes,
    *,
    is_pair_source: PairSourcePredicate,
    generated: tuple[str, ...],
    public_blob_root: str,
) -> None:
    source_text = source.decode("utf-8")
    zh_text = zh.decode("utf-8")
    index_files = git_merge_input_paths(root)

    def repository_file_exists(path: str) -> bool:
        return path in index_files

    en_switcher = pairing_links.language_switcher_targets(paths.zh, public_blob_root)
    zh_switcher = pairing_links.language_switcher_targets(paths.source, public_blob_root)
    if pairing_links.requires_source_language_switcher(paths.source, generated) and not (
        pairing_links.has_language_switcher(source_text, en_switcher)
    ):
        msg = (
            f"{paths.source} clean merge lost its language-switcher link to "
            f"{os.path.basename(paths.zh)}"
        )
        raise ValueError(msg)
    if not pairing_links.has_language_switcher(zh_text, zh_switcher):
        msg = (
            f"{paths.zh} clean merge lost its language-switcher link to "
            f"{os.path.basename(paths.source)}"
        )
        raise ValueError(msg)

    def context_for(source_path: str, markdown: str) -> pairing_links.LinkContext:
        return pairing_links.LinkContext(
            repo_root=root,
            source_path=source_path,
            is_pair_source=is_pair_source,
            repository_file_exists=repository_file_exists,
            markdown=markdown,
        )

    locale_violations = [
        *pairing_links.link_locale_violations(
            source_text, context_for(paths.source, source_text), en_switcher
        ),
        *pairing_links.link_locale_violations(zh_text, context_for(paths.zh, zh_text), zh_switcher),
    ]
    if locale_violations:
        violation = locale_violations[0]
        raise ValueError(
            f"{violation.source_path}:{violation.line} clean merge uses "
            f"{violation.url!r}; expected {violation.expected_url!r}"
        )
    source_context = context_for(paths.source, source_text)
    zh_context = context_for(paths.zh, zh_text)
    divergences = structure_diff(
        structure_signature(parse_markdown(source_text), en_switcher, source_context),
        structure_signature(parse_markdown(zh_text), zh_switcher, zh_context),
    )
    if divergences:
        detail = "; ".join(divergences)
        msg = f"{paths.source} and {paths.zh} clean merges diverge structurally: {detail}"
        raise ValueError(msg)


def _normalize_meta_path(root: str, meta: str) -> str:
    if Path(meta).is_absolute():
        msg = f"pairing record must be repository-relative: {meta!r}"
        raise ValueError(msg)
    absolute = Path(root, meta).resolve()
    repository_relative = os.path.relpath(absolute, Path(root).resolve())
    if repository_relative in {"", ".."} or repository_relative.startswith(f"..{os.sep}"):
        msg = f"pairing record escapes the repository: {meta!r}"
        raise ValueError(msg)
    return repository_relative.replace(os.sep, "/")


def merge_records(
    root: str,
    meta_path: str,
    ancestor_record: str,
    current_record: str,
    other_record: str,
    *,
    is_pair_source: PairSourcePredicate,
    generated: tuple[str, ...],
    public_blob_root: str,
) -> PairingMergeResult:
    """Compose one generated sidecar from the ancestor, current, and other records.

    Each input record is already a confirmation of its two owner blobs. The
    result exists only when Git's default text merge succeeds independently
    for both languages and the composed documents retain the pairing
    structure.

    Args:
        root: Repository root containing the referenced Git objects.
        meta_path: Repository-relative sidecar path.
        ancestor_record: Common-ancestor sidecar text.
        current_record: Current-side sidecar text.
        other_record: Other-side sidecar text.
        is_pair_source: Active bilingual-source predicate.
        generated: Manifest-listed generated English sources, exempt from the
            English-side switcher requirement.
        public_blob_root: Manifest-configured absolute-URL prefix accepted
            before switcher counterparts.

    Returns:
        The canonical record and exact merged owner contents.

    Raises:
        ValueError: When the input is not mechanically composable.
    """
    normalized_meta = _normalize_meta_path(root, meta_path)
    if not is_scope_file(normalized_meta):
        msg = f"{normalized_meta} is outside the active bilingual documentation corpus"
        raise ValueError(msg)
    paths = pair_paths_from_meta(normalized_meta)
    if not is_pair_source(paths.source):
        msg = f"{normalized_meta} is excluded from the active bilingual documentation corpus"
        raise ValueError(msg)
    _assert_default_text_merge(root, paths)
    ancestor = _load_record_owners(root, "ancestor", ancestor_record, paths)
    current = _load_record_owners(root, "current", current_record, paths)
    other = _load_record_owners(root, "other", other_record, paths)
    source_content = _merge_blob_triplet(root, paths.source, ancestor[0], current[0], other[0])
    zh_content = _merge_blob_triplet(root, paths.zh, ancestor[1], current[1], other[1])
    _assert_merged_pair_structure(
        root,
        paths,
        source_content,
        zh_content,
        is_pair_source=is_pair_source,
        generated=generated,
        public_blob_root=public_blob_root,
    )
    source_hash = store_git_blob(root, source_content)
    zh_hash = store_git_blob(root, zh_content)
    return PairingMergeResult(
        source_hash=source_hash,
        zh_hash=zh_hash,
        record_text=render_record(paths, PairingRecord(source_hash=source_hash, zh_hash=zh_hash)),
        source_content=source_content,
        zh_content=zh_content,
    )


def pairing_manifest(root: str) -> PairingManifest:
    """Read and parse the repository's pairing manifest.

    Args:
        root: Repository root.

    Returns:
        The validated manifest.

    Raises:
        ValueError: When the manifest is missing or invalid.
        GitError: When the index cannot be read.
    """
    staged = read_git_index_blob(root, MANIFEST_PATH)
    content = staged[1] if staged is not None else Path(root, MANIFEST_PATH).read_bytes()
    return parse_manifest(content.decode("utf-8"))


def pairing_source(root: str) -> PairSourcePredicate:
    """Read the repository manifest and return its bilingual-source predicate.

    Args:
        root: Repository root.

    Returns:
        The active corpus predicate.

    Raises:
        ValueError: When the manifest is missing or invalid.
        GitError: When the index cannot be read.
    """
    return pair_source_predicate(pairing_manifest(root))


def _unmerged_sidecars(root: str) -> dict[str, dict[str, str]]:
    output = run_git(
        root, ["ls-files", "--unmerged", "-z"], "listing unresolved merge entries"
    ).decode("utf-8")
    records: dict[str, dict[str, str]] = {}
    for entry in output.split("\0"):
        if entry == "":
            continue
        match = _UNMERGED_ENTRY.match(entry)
        if match is None:
            msg = f"git ls-files returned a malformed unmerged entry: {entry!r}"
            raise GitError(msg)
        path = match.group(4)
        if not path.endswith(".i18n.yaml"):
            continue
        field = {"1": "ancestor", "2": "current", "3": "other"}[match.group(3)]
        records.setdefault(path, {})[field] = match.group(2)
    return records


def _assert_unedited_sidecar(
    root: str,
    meta_path: str,
    ancestor_record: str,
    current_record: str,
    other_record: str,
) -> None:
    worktree_record = Path(root, meta_path).read_text(encoding="utf-8")
    if worktree_record in (current_record, other_record):
        return
    output, status = _run_text_merge(root, meta_path, ancestor_record, current_record, other_record)
    if status == 0 and output.decode("utf-8") == worktree_record:
        return
    stage_data_lines = [
        line
        for record in (current_record, other_record)
        for line in re.split(r"\r?\n", record)
        if line != "" and not line.startswith("#")
    ]
    has_unedited_conflict = (
        "<<<<<<<" in worktree_record
        and "=======" in worktree_record
        and ">>>>>>>" in worktree_record
        and all(line in worktree_record for line in stage_data_lines)
    )
    if not has_unedited_conflict:
        msg = f"{meta_path} has edited conflict content; refusing to overwrite manual work"
        raise ValueError(msg)


def resolve_conflicts(
    root: str,
    is_pair_source: PairSourcePredicate,
    *,
    generated: tuple[str, ...],
    public_blob_root: str,
) -> list[str]:
    """Resolve every mechanically composable ``.i18n.yaml`` conflict in the index.

    The command first proves that Git's already-staged owner merges match the
    independently composed contents, then writes and stages all sidecars as
    one batch. Other conflicts remain untouched; after staging the safe
    records, an aggregate error reports any pairing conflicts that still need
    manual work.

    Args:
        root: Repository root with an in-progress merge-like operation.
        is_pair_source: Active bilingual-source predicate.
        generated: Manifest-listed generated English sources, exempt from the
            English-side switcher requirement.
        public_blob_root: Manifest-configured absolute-URL prefix accepted
            before switcher counterparts.

    Returns:
        Repository-relative sidecar paths resolved and staged.

    Raises:
        ValueError: When at least one pairing conflict remains unresolved.
    """
    resolutions: list[tuple[str, str]] = []
    failures: list[tuple[str, str]] = []
    for meta_path, stages in sorted(_unmerged_sidecars(root).items()):
        try:
            if not {"ancestor", "current", "other"} <= set(stages):
                msg = "is an add/delete or incomplete-stage conflict and requires manual resolution"
                raise ValueError(msg)
            ancestor_record = _read_git_blob(
                root, stages["ancestor"], f"ancestor {meta_path}"
            ).decode("utf-8")
            current_record = _read_git_blob(root, stages["current"], f"current {meta_path}").decode(
                "utf-8"
            )
            other_record = _read_git_blob(root, stages["other"], f"other {meta_path}").decode(
                "utf-8"
            )
            _assert_unedited_sidecar(root, meta_path, ancestor_record, current_record, other_record)
            result = merge_records(
                root,
                meta_path,
                ancestor_record,
                current_record,
                other_record,
                is_pair_source=is_pair_source,
                generated=generated,
                public_blob_root=public_blob_root,
            )
            paths = pair_paths_from_meta(meta_path)
            staged_source = read_git_index_blob(root, paths.source)
            if staged_source is None or staged_source[0] != result.source_hash:
                msg = f"{paths.source} staged merge does not match the pairing driver's clean merge"
                raise ValueError(msg)
            staged_zh = read_git_index_blob(root, paths.zh)
            if staged_zh is None or staged_zh[0] != result.zh_hash:
                msg = f"{paths.zh} staged merge does not match the pairing driver's clean merge"
                raise ValueError(msg)
            for path, expected in (
                (paths.source, result.source_hash),
                (paths.zh, result.zh_hash),
            ):
                if blob_hash(Path(root, path).read_bytes()) != expected:
                    msg = (
                        f"{path} has unstaged content; refusing to confirm bytes "
                        "outside the merge result"
                    )
                    raise ValueError(msg)
            resolutions.append((meta_path, result.record_text))
        except (ValueError, GitError, OSError) as error:
            failures.append((meta_path, str(error)))
    for meta_path, record in resolutions:
        Path(root, meta_path).write_text(record, encoding="utf-8")
    if resolutions:
        run_git(
            root,
            ["add", "--", *[path for path, _ in resolutions]],
            "staging resolved pairing records",
        )
    if failures:
        resolved_note = (
            ""
            if not resolutions
            else f"resolved and staged {', '.join(path for path, _ in resolutions)}; "
        )
        details = "\n".join(f"- {path}: {reason}" for path, reason in failures)
        msg = f"{resolved_note}left {len(failures)} pairing conflict(s) unresolved:\n{details}"
        raise ValueError(msg)
    return [path for path, _ in resolutions]


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``merge`` command leaf."""
    parser = subparsers.add_parser("merge", help="merge driver and conflict resolver")
    parser.add_argument("--probe", action="store_true", help="check runtime availability")
    parser.add_argument("--resolve", action="store_true", help="resolve staged pairing conflicts")
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="driver form: <ancestor> <current> <other> <repository-path>",
    )
    parser.set_defaults(handler=main)


def main(args: argparse.Namespace) -> int:
    """Git merge-driver and explicit conflict-resolver entry point.

    Args:
        args: Parsed leaf namespace; ``--probe`` checks runtime availability,
            ``--resolve`` resolves staged pairing conflicts, and the driver
            form takes the four paths Git passes.

    Returns:
        The exit code: 0 composed or resolved, 1 composition failure, 2 usage.
    """
    modes = [args.probe, args.resolve, bool(args.paths)]
    if modes.count(True) != 1 or (args.paths and len(args.paths) != _DRIVER_ARG_COUNT):
        print(
            f"{TOOL}: usage: --probe | --resolve | <ancestor> <current> <other> <repository-path>",
            file=sys.stderr,
        )
        return 2
    try:
        if args.probe:
            return 0
        root = (
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                check=True,
            )
            .stdout.decode("utf-8")
            .strip()
        )
        if args.resolve:
            manifest = pairing_manifest(root)
            resolved = resolve_conflicts(
                root,
                pair_source_predicate(manifest),
                generated=manifest.generated,
                public_blob_root=manifest.public_blob_root,
            )
            if not resolved:
                print(f"{TOOL}: no unresolved pairing records")
            else:
                for path in resolved:
                    print(f"{TOOL}: resolved {path}")
            return 0
        ancestor_path, current_path, other_path, meta_path = args.paths
        manifest = pairing_manifest(root)
        result = merge_records(
            root,
            meta_path,
            Path(ancestor_path).read_text(encoding="utf-8"),
            Path(current_path).read_text(encoding="utf-8"),
            Path(other_path).read_text(encoding="utf-8"),
            is_pair_source=pairing_source(root),
            generated=manifest.generated,
            public_blob_root=manifest.public_blob_root,
        )
        Path(current_path).write_text(result.record_text, encoding="utf-8")
    except (ValueError, GitError, OSError, subprocess.CalledProcessError) as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        print(
            f"{TOOL}: resolve owner conflicts, then confirm the pair with "
            "`hdsh pairing record <pair>`; rerun `hdsh pairing merge --resolve` "
            "for other safe records",
            file=sys.stderr,
        )
        return 1
    return 0
