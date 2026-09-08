"""Verify that relative Markdown links, images, and definitions resolve.

The target file must exist AND a ``#fragment`` onto a Markdown target —
including a same-file ``#anchor`` — must name a real heading slug or explicit
``<a id>``. URL and root-absolute targets are excluded; query strings do not
affect resolution against the source file. The checker never rewrites;
symlinked instruction files are deduped.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hdsh.docs.config import (
    DocsConfigError,
    load_docs_manifest,
    missing_section_error,
)
from hdsh.docs.corpus import CorpusFile, discover_corpus_files, find_repository_root
from hdsh.docs.markdown import (
    document_anchors,
    document_destinations,
    fragment_part,
    is_external_url,
    path_part,
)

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh docs links"


@dataclass(frozen=True)
class BrokenLinkViolation:
    """One broken relative cross-link: a missing target or a missing anchor."""

    #: Repository-relative file containing the link.
    file: str
    #: 1-based line of the link, image, or definition.
    line: int
    #: Destination URL as authored.
    url: str
    #: What failed: ``target`` or ``anchor``.
    reason: str


class AnchorCache:
    """Lazily collect and memoize the anchor set of any existing file.

    Shared across all scanned sources so a target parses once.
    """

    def __init__(self) -> None:
        """Start with an empty absolute-path to anchor-set cache."""
        self._cache: dict[Path, set[str]] = {}

    def anchors(self, path: Path) -> set[str]:
        """Return every anchor the Markdown file at ``path`` exposes.

        Args:
            path: Absolute path of an existing Markdown target.

        Returns:
            The memoized anchor set.
        """
        hit = self._cache.get(path)
        if hit is not None:
            return hit
        anchors = document_anchors(path.read_text(encoding="utf-8"))
        self._cache[path] = anchors
        return anchors


def find_violations(
    source: str,
    file: CorpusFile,
    anchors_of: AnchorCache,
) -> list[BrokenLinkViolation]:
    """Find every broken relative cross-link in one Markdown document.

    A relative target that does not exist is reported against the target; a
    fragment onto a Markdown file (same-file ``#anchor`` links included) that
    names no heading slug or explicit ``<a id>`` there is reported against the
    anchor. Fragments onto non-Markdown targets (``file.ts#L10``) carry
    renderer-owned semantics and are not judged.

    Args:
        source: Complete document text of ``file``.
        file: The corpus file being scanned, for paths and diagnostics.
        anchors_of: Anchor lookup shared across files for cross-link checks.

    Returns:
        Violations in document order.
    """
    out: list[BrokenLinkViolation] = []
    for destination in document_destinations(source):
        url = destination.url
        if is_external_url(url):
            continue
        target = path_part(url)
        resolved = file.abs_path if target == "" else file.abs_path.parent / target
        if not resolved.exists():
            out.append(BrokenLinkViolation(file.path, destination.line, url, "target"))
            continue
        fragment = fragment_part(url)
        if fragment is None or not resolved.name.endswith(".md"):
            continue
        if fragment not in anchors_of.anchors(resolved):
            out.append(BrokenLinkViolation(file.path, destination.line, url, "anchor"))
    return out


def run(root: Path) -> int:
    """Check the configured Markdown corpus for broken relative cross-links.

    Args:
        root: Absolute repository root.

    Returns:
        The exit code: 0 green, 1 violations found.
    """
    manifest = load_docs_manifest(root)
    if manifest.markdown_links is None:
        raise missing_section_error("markdownLinks", TOOL)
    files = discover_corpus_files(root, manifest.markdown_links)
    anchors_of = AnchorCache()
    violations: list[BrokenLinkViolation] = []
    for file in files:
        source = file.abs_path.read_text(encoding="utf-8")
        violations.extend(find_violations(source, file, anchors_of))
    if not violations:
        print(
            f"{TOOL}: {len(files)} file(s) checked, all relative cross-links and fragments resolve."
        )
        return 0
    print(f"{TOOL}: broken relative cross-links found:", file=sys.stderr)
    for violation in violations:
        reason = (
            "target does not exist" if violation.reason == "target" else "no such anchor in target"
        )
        print(f"  {violation.file}:{violation.line}  {violation.url}  ({reason})", file=sys.stderr)
    return 1


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``links`` command leaf."""
    parser = subparsers.add_parser("links", help="relative cross-links resolve")
    parser.set_defaults(handler=main)


def main(_args: argparse.Namespace) -> int:
    """``hdsh docs links`` entry point."""
    root = find_repository_root(TOOL)
    try:
        return run(root)
    except DocsConfigError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 2
