"""Enforce complete English/Chinese pairs for every in-scope document.

The gate checks pair completeness, recorded git blob hashes, language
switchers, link locales, generated-region equality, and structural
signatures. ``hdsh pairing list`` reports state; ``hdsh pairing record
<pairs...>`` records the named confirmed pairs (``hdsh pairing record --all``
records every complete pair); ``hdsh pairing verify --cached <pairs...>``
checks exact index bytes for hooks. A verify named with pair paths touches
only those pairs, so update iteration does not pay for a corpus scan.
Translation quality remains a review responsibility. See
``docs/i18n/README.md`` for the owning contract.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from hdsh.pairing import links as pairing_links
from hdsh.pairing.corpus import is_scope_file
from hdsh.pairing.git import blob_hash, git_index_paths, read_git_index_blob, store_git_blob
from hdsh.pairing.manifest import MANIFEST_PATH, manifest_excluded, parse_manifest
from hdsh.pairing.records import (
    PairingRecord,
    anchor_of_argument,
    pair_paths,
    parse_record,
    render_record,
)
from hdsh.pairing.structure import (
    parse_markdown,
    partition_generated_regions,
    structure_diff,
    structure_signature,
)

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh pairing"

_STATUS_ORDER = {"out-of-sync": 0, "missing": 1, "ok": 2}

#: Directory names never traversed, wherever they appear in the tree.
_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        ".cache",
        "coverage",
        "build",
        "dist",
        "tmp",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
)
#: Repository-root prefixes never traversed.
_EXCLUDED_ROOT_PREFIXES = (".local/", ".hdsh-env/", ".prek/", "vendor/")

ReadFile = Callable[[str], "bytes | None"]
FileExists = Callable[[str], bool]
LineSink = Callable[[str], None]


def _print_stderr(line: str) -> None:
    """Write one gate line to the process's standard error stream."""
    print(line, file=sys.stderr)


class RepositoryPlane(Protocol):
    """The content-plane surface the pair check consumes."""

    #: Absolute repository root.
    root: str

    def read_repository_file(self, file: str) -> bytes | None:
        """Read one repository path from the selected content plane."""
        ...

    def repository_file_exists(self, file: str) -> bool:
        """Whether one path exists in the selected content plane."""
        ...


@dataclass(frozen=True)
class PairingRequest:
    """A parsed ``hdsh pairing`` subcommand invocation."""

    #: Content plane read by the check; writes always use the working tree.
    input: str
    mode: str
    #: ``corpus`` runs discovery over the whole tree; ``pairs`` names anchors.
    scope: str
    #: English anchor paths, empty for corpus scope.
    anchors: tuple[str, ...] = field(default=())


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``verify``, ``record``, and ``list`` command leaves."""
    verify = subparsers.add_parser("verify", help="bilingual pairing gate")
    verify.add_argument(
        "--cached", action="store_true", help="check the Git index instead of the worktree"
    )
    verify.add_argument(
        "anchors", nargs="*", metavar="<pair>", help="any file of each pair to check"
    )
    verify.set_defaults(handler=verify_main)
    record = subparsers.add_parser("record", help="re-record confirmed pairs")
    record.add_argument(
        "--all",
        action="store_true",
        help="re-record every complete pair (an explicit bulk re-record)",
    )
    record.add_argument(
        "anchors", nargs="*", metavar="<pair>", help="any file of each confirmed pair"
    )
    record.set_defaults(handler=record_main)
    listing = subparsers.add_parser("list", help="pairing state per document")
    listing.set_defaults(handler=list_main)


def _anchors(raw: Sequence[str]) -> tuple[str, ...]:
    """Normalize anchor arguments to sorted, deduplicated pair anchors."""
    return tuple(sorted({anchor_of_argument(anchor) for anchor in raw}))


def verify_request(args: argparse.Namespace) -> PairingRequest:
    """Build the ``verify`` request from parsed arguments.

    Args:
        args: Parsed leaf namespace with ``cached`` and ``anchors``.

    Returns:
        The validated request.

    Raises:
        ValueError: When the flag and path combination is invalid.
    """
    anchors = _anchors(args.anchors)
    if args.cached and not anchors:
        raise ValueError("--cached requires the staged pair paths to check")
    return PairingRequest(
        input="index" if args.cached else "worktree",
        mode="check",
        scope="pairs" if anchors else "corpus",
        anchors=anchors,
    )


def record_request(args: argparse.Namespace) -> PairingRequest:
    """Build the ``record`` request from parsed arguments.

    Recording requires either pair paths or ``--all`` so a bulk re-record is
    always an explicit choice — a bare record would silently bless every
    drifted pair in the tree.

    Args:
        args: Parsed leaf namespace with ``all`` and ``anchors``.

    Returns:
        The validated request.

    Raises:
        ValueError: When the flag and path combination is invalid.
    """
    anchors = _anchors(args.anchors)
    if anchors and args.all:
        raise ValueError("record takes either pair paths or --all, not both")
    if not anchors and not args.all:
        raise ValueError(
            "record requires the pair(s) you confirmed (any file of a pair), or "
            "--all to re-record every complete pair; recording pairs you did not "
            "review blesses unconfirmed content"
        )
    return PairingRequest(
        input="worktree",
        mode="write",
        scope="corpus" if args.all else "pairs",
        anchors=anchors,
    )


def list_request(_args: argparse.Namespace) -> PairingRequest:
    """Build the ``list`` request: the whole corpus, never filtered."""
    return PairingRequest(input="worktree", mode="list", scope="corpus")


class PairingRepository:
    """One repository content plane plus corpus discovery for the gate."""

    root: str
    index_mode: bool

    def __init__(self, root: str, *, index_mode: bool = False) -> None:
        """Bind the gate to a repository root and content plane.

        Args:
            root: Absolute repository root.
            index_mode: Read staged bytes from the Git index instead of the
                working tree.
        """
        self.root = root
        self.index_mode = index_mode
        # Empty in worktree mode; populated once in index mode.
        self._index_files: set[str] = git_index_paths(root) if index_mode else set()
        self._content_cache: dict[str, bytes | None] = {}

    def read_repository_file(self, file: str) -> bytes | None:
        """Read one repository path from the selected content plane.

        Args:
            file: Repository-relative path.

        Returns:
            Exact file bytes, or ``None`` when absent.
        """
        if file in self._content_cache:
            return self._content_cache[file]
        content: bytes | None
        if self.index_mode:
            staged = read_git_index_blob(self.root, file) if file in self._index_files else None
            content = staged[1] if staged is not None else None
        else:
            path = Path(self.root, file)
            content = path.read_bytes() if path.is_file() else None
        self._content_cache[file] = content
        return content

    def repository_file_exists(self, file: str) -> bool:
        """Whether one path exists in the selected content plane.

        Args:
            file: Repository-relative path.

        Returns:
            True when present.
        """
        if self.index_mode:
            return file in self._index_files
        return self.read_repository_file(file) is not None

    def discover_scope_files(self) -> set[str]:
        """Enumerate every in-scope Markdown and pairing sidecar in the tree.

        Returns:
            Repository-relative paths that pass the corpus predicate.
        """
        files: set[str] = set()
        root_path = Path(self.root)
        for pattern in ("*.md", "*.i18n.yaml"):
            for path in root_path.rglob(pattern):
                relative = path.relative_to(root_path).as_posix()
                if any(segment in _EXCLUDED_DIRECTORY_NAMES for segment in relative.split("/")):
                    continue
                if relative.startswith(_EXCLUDED_ROOT_PREFIXES):
                    continue
                if is_scope_file(relative):
                    files.add(relative)
        return files


def _context(
    source_path: str,
    markdown: str,
    is_pair_source: Callable[[str], bool],
    repository: RepositoryPlane,
) -> pairing_links.LinkContext:
    """Build the link-resolution context for one document."""
    return pairing_links.LinkContext(
        repo_root=repository.root,
        source_path=source_path,
        is_pair_source=is_pair_source,
        repository_file_exists=repository.repository_file_exists,
        markdown=markdown,
    )


def run_gate(
    request: PairingRequest,
    root: str,
    *,
    stdout: LineSink = print,
    stderr: LineSink = _print_stderr,
) -> int:
    """Execute one ``hdsh pairing`` gate request.

    Args:
        request: The parsed subcommand request.
        root: Absolute repository root the gate operates on.
        stdout: Status-line sink.
        stderr: Error-line sink.

    Returns:
        The process exit code: 0 green, 1 gate violation, 2 usage error.
    """
    repository = PairingRepository(root, index_mode=request.input == "index")
    manifest_content = repository.read_repository_file(MANIFEST_PATH)
    if manifest_content is None:
        stderr(f"{TOOL}: {MANIFEST_PATH} is missing from the selected content plane")
        return 2
    try:
        manifest = parse_manifest(manifest_content.decode("utf-8"))
    except (TypeError, ValueError) as error:
        stderr(f"{TOOL}: {error}")
        return 2

    def excluded(file: str) -> bool:
        return manifest_excluded(file, manifest)

    def is_pair_source(path: str) -> bool:
        return is_scope_file(path) and not excluded(path)

    files: set[str] = set()
    if request.scope == "pairs":
        for anchor in request.anchors:
            paths = pair_paths(anchor)
            for file in (paths.source, paths.zh, paths.meta):
                if repository.repository_file_exists(file):
                    files.add(file)
            if not repository.index_mode and not repository.repository_file_exists(anchor):
                files.add(anchor)
    else:
        files = repository.discover_scope_files()

    translations = sorted(f for f in files if f.endswith(".zh.md"))
    metas = sorted(f for f in files if f.endswith(".i18n.yaml"))
    sources = sorted(f for f in files if f.endswith(".md") and not f.endswith(".zh.md"))

    if request.scope == "pairs":
        rejected = [a for a in request.anchors if not is_scope_file(a) or excluded(a)]
        absent = [
            a
            for a in request.anchors
            if not any(
                repository.repository_file_exists(f)
                for f in (
                    pair_paths(a).source,
                    pair_paths(a).zh,
                    pair_paths(a).meta,
                )
            )
        ]
        if rejected or (not repository.index_mode and absent):
            for anchor in rejected:
                stderr(
                    f"{TOOL}: {anchor} is not an in-scope pair "
                    "(excluded or outside the documentation corpus; see docs/i18n/README.md)"
                )
            for anchor in absent:
                stderr(f"{TOOL}: {anchor} names no pair on disk (none of its three files exist)")
            return 2

    if request.mode == "write":
        return _write_records(
            repository, request, sources, excluded=excluded, stdout=stdout, stderr=stderr
        )

    errors: list[str] = []
    state: dict[str, str] = {}

    for source in sources:
        if excluded(source):
            continue
        if not repository.repository_file_exists(pair_paths(source).zh):
            errors.append(
                f"{source}: in-scope documentation must merge bilingual "
                "(docs/i18n/README.md); add the counterpart and record the pair"
            )
            state[source] = "missing"

    pair_anchors: set[str] = set()
    for zh in translations:
        pair_anchors.add(f"{zh[: -len('.zh.md')]}.md")
    for meta in metas:
        pair_anchors.add(f"{meta[: -len('.i18n.yaml')]}.md")

    for source in sorted(pair_anchors):
        _check_pair(
            source,
            repository,
            is_pair_source,
            excluded=excluded,
            generated=manifest.generated,
            public_blob_root=manifest.public_blob_root,
            errors=errors,
            state=state,
        )

    for source in sources:
        if not excluded(source) and source not in state:
            state[source] = "missing"

    if request.mode == "list":
        rows = sorted(state.items(), key=lambda item: (_STATUS_ORDER[item[1]], item[0]))
        for file, status in rows:
            suffix = "  (required)" if status == "missing" else ""
            stdout(f"{status:<11} {file}{suffix}")
        counts = {"ok": 0, "out-of-sync": 0, "missing": 0}
        for status in state.values():
            counts[status] += 1
        stdout(
            f"{TOOL}: {counts['ok']} ok, "
            f"{counts['out-of-sync']} out-of-sync, {counts['missing']} missing "
            f"(of {len(state)} in scope)"
        )
        return 0

    if not errors:
        plane = "staged " if repository.index_mode else ""
        if request.scope == "pairs":
            stdout(
                f"{TOOL}: {len(pair_anchors)} named {plane}pair(s) "
                "consistent; the corpus-wide check still runs in CI."
            )
        else:
            stdout(
                f"{TOOL}: {len(pair_anchors)} pair(s) checked "
                "across all in-scope documentation, all consistent."
            )
        return 0

    stderr(f"{TOOL}: bilingual pairing rules violated (see docs/i18n/README.md):")
    for message in errors:
        stderr(f"  {message}")
    return 1


def _write_records(
    repository: PairingRepository,
    request: PairingRequest,
    sources: list[str],
    *,
    excluded: Callable[[str], bool],
    stdout: LineSink,
    stderr: LineSink,
) -> int:
    """Record both hashes for the requested complete pairs, creating records.

    Args:
        repository: Bound content plane (writes always use the working tree).
        request: The parsed CLI request carrying ``scope``.
        sources: Discovered English sources.
        excluded: Manifest exclusion predicate.
        stdout: Status-line sink.
        stderr: Error-line sink.

    Returns:
        The process exit code.
    """
    scope = request.scope
    written = 0
    for source in sources:
        if excluded(source):
            continue
        paths = pair_paths(source)
        source_exists = repository.repository_file_exists(paths.source)
        zh_exists = repository.repository_file_exists(paths.zh)
        if not source_exists or not zh_exists:
            if scope == "pairs":
                missing = paths.source if not source_exists else paths.zh
                stderr(f"{TOOL}: cannot record {source}: missing {missing}")
                return 2
            continue
        source_content = repository.read_repository_file(paths.source)
        zh_content = repository.read_repository_file(paths.zh)
        if source_content is None or zh_content is None:
            stderr(f"{TOOL}: {source}: complete pair became unreadable")
            return 2
        # A consistency record is also a recovery pointer: persist both
        # snapshots even when the sidecar text is already current, because the
        # bytes may exist only in this working tree.
        record = render_record(
            paths,
            PairingRecord(
                source_hash=store_git_blob(repository.root, source_content),
                zh_hash=store_git_blob(repository.root, zh_content),
            ),
        )
        meta_path = Path(repository.root, paths.meta)
        if meta_path.is_file() and meta_path.read_text(encoding="utf-8") == record:
            continue
        meta_path.write_text(record, encoding="utf-8")
        stdout(f"{TOOL}: recorded {paths.meta}")
        written += 1
    stdout(f"{TOOL}: {written} record(s) written; run the check to validate the pairs.")
    return 0


def _check_pair(
    source: str,
    repository: RepositoryPlane,
    is_pair_source: Callable[[str], bool],
    *,
    excluded: Callable[[str], bool],
    generated: tuple[str, ...],
    public_blob_root: str,
    errors: list[str],
    state: dict[str, str],
) -> None:
    """Check one pair anchor for completeness and consistency.

    Args:
        source: English anchor path.
        repository: Bound content plane.
        is_pair_source: Active corpus predicate.
        excluded: Manifest exclusion predicate.
        generated: Manifest-listed generated English sources, exempt from the
            English-side switcher requirement.
        public_blob_root: Manifest-configured absolute-URL prefix accepted
            before switcher counterparts.
        errors: Accumulated gate violations.
        state: ``list`` state map.
    """
    paths = pair_paths(source)
    have = {
        "source": repository.repository_file_exists(paths.source),
        "zh": repository.repository_file_exists(paths.zh),
        "meta": repository.repository_file_exists(paths.meta),
    }
    if excluded(source):
        if have["zh"]:
            errors.append(
                f"{paths.zh}: {source} is excluded from pairing "
                "(generated or bilingual-by-construction); this translation must not exist"
            )
        if have["meta"]:
            errors.append(
                f"{paths.meta}: {source} is excluded from pairing; "
                "this consistency record must not exist"
            )
        return
    missing = [
        paths.source if key == "source" else paths.zh if key == "zh" else paths.meta
        for key, present in have.items()
        if not present
    ]
    if missing:
        errors.append(
            f"{source}: incomplete pair — missing {', '.join(missing)} "
            "(pairs merge whole: both languages plus the .i18n.yaml record)"
        )
        return

    source_content = repository.read_repository_file(paths.source)
    zh_content = repository.read_repository_file(paths.zh)
    meta_content = repository.read_repository_file(paths.meta)
    if source_content is None or zh_content is None or meta_content is None:
        message = f"{source}: complete pair became unreadable"
        raise RuntimeError(message)

    record = parse_record(meta_content.decode("utf-8"), paths)
    if record is None:
        errors.append(
            f"{paths.meta}: malformed consistency record (expected exactly "
            f"`{Path(paths.source).name}: <40-hex>` and "
            f"`{Path(paths.zh).name}: <40-hex>`)"
        )
        return

    consistent = True
    for file, content, recorded in (
        (paths.source, source_content, record.source_hash),
        (paths.zh, zh_content, record.zh_hash),
    ):
        if blob_hash(content) != recorded:
            errors.append(
                f"{file}: out of sync — content no longer matches the pair's last "
                f"confirmed-consistent state in {paths.meta} (bring the other side "
                "along, then re-record with `hdsh pairing record`)"
            )
            consistent = False
    if not consistent:
        state[source] = "out-of-sync"
        return

    source_text = source_content.decode("utf-8")
    zh_text = zh_content.decode("utf-8")
    # English-side switcher links to the zh basename; the zh side reciprocates.
    en_switcher_targets = pairing_links.language_switcher_targets(paths.zh, public_blob_root)
    zh_switcher_targets = pairing_links.language_switcher_targets(paths.source, public_blob_root)
    for violation in [
        *pairing_links.link_locale_violations(
            source_text,
            _context(source, source_text, is_pair_source, repository),
            en_switcher_targets,
        ),
        *pairing_links.link_locale_violations(
            zh_text,
            _context(paths.zh, zh_text, is_pair_source, repository),
            zh_switcher_targets,
        ),
    ]:
        errors.append(
            f"{violation.source_path}:{violation.line}: link target {violation.url!r} uses "
            f"the wrong locale; expected {violation.expected_url!r}"
        )
        state[source] = "out-of-sync"

    try:
        source_regions = partition_generated_regions(source_text)
        zh_regions = partition_generated_regions(zh_text)
    except ValueError as error:
        errors.append(f"{source} ↔ {paths.zh}: {error}")
        state[source] = "out-of-sync"
        return
    # Generated regions must stay byte-identical after each side's
    # paired-document locale paths normalize to one semantic target; any
    # prose, ordering, code, marker, or non-locale URL drift is a divergence.
    # No switcher is skipped here: a switcher-shaped line inside a region
    # normalizes like any corpus link.
    normalized_source_regions = [
        pairing_links.normalize_translation_markdown_links(
            region, _context(source, source_text, is_pair_source, repository)
        )
        for region in source_regions.regions
    ]
    normalized_zh_regions = [
        pairing_links.normalize_translation_markdown_links(
            region, _context(paths.zh, zh_text, is_pair_source, repository)
        )
        for region in zh_regions.regions
    ]
    if normalized_source_regions != normalized_zh_regions:
        errors.append(
            f"{source} ↔ {paths.zh}: generated regions differ beyond "
            "paired-document locale paths — regenerate both sides"
        )
        state[source] = "out-of-sync"

    if not pairing_links.has_language_switcher(zh_text, zh_switcher_targets):
        errors.append(
            f"{paths.zh}: missing language switcher — no link to {Path(paths.source).name}"
        )
    if pairing_links.requires_source_language_switcher(source, generated) and not (
        pairing_links.has_language_switcher(source_text, en_switcher_targets)
    ):
        errors.append(
            f"{source}: missing language switcher — no link back to {Path(paths.zh).name}"
        )
    source_tree = parse_markdown(source_text)
    zh_tree = parse_markdown(zh_text)
    source_signature = structure_signature(
        source_tree,
        en_switcher_targets,
        _context(source, source_text, is_pair_source, repository),
    )
    zh_signature = structure_signature(
        zh_tree,
        zh_switcher_targets,
        _context(paths.zh, zh_text, is_pair_source, repository),
    )
    errors.extend(
        f"{source} ↔ {paths.zh}: {divergence}"
        for divergence in structure_diff(source_signature, zh_signature)
    )
    if source not in state:
        state[source] = "ok"


def _repository_root() -> str:
    """Locate the repository root of the current working directory.

    Returns:
        The absolute path printed by ``git rev-parse --show-toplevel``.

    Raises:
        SystemExit: When the working directory is inside no repository.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, check=False
        )
    except OSError as error:
        print(f"{TOOL}: cannot locate repository root: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    if completed.returncode != 0:
        print(f"{TOOL}: working directory is inside no Git repository", file=sys.stderr)
        raise SystemExit(2)
    return completed.stdout.decode("utf-8").strip()


def _gate_main(
    build: Callable[[argparse.Namespace], PairingRequest], args: argparse.Namespace
) -> int:
    """Validate one subcommand request and run its gate."""
    try:
        request = build(args)
    except ValueError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 2
    return run_gate(request, _repository_root())


def verify_main(args: argparse.Namespace) -> int:
    """``hdsh pairing verify`` entry point."""
    return _gate_main(verify_request, args)


def record_main(args: argparse.Namespace) -> int:
    """``hdsh pairing record`` entry point."""
    return _gate_main(record_request, args)


def list_main(args: argparse.Namespace) -> int:
    """``hdsh pairing list`` entry point."""
    return _gate_main(list_request, args)
