"""Scope predicates selecting the repository's bilingual pairing corpus."""

from __future__ import annotations

import re
from collections.abc import Callable

from hdsh.pairing.manifest import (
    PairingManifest,
    manifest_excluded,
    manifest_governed,
    manifest_rooted,
)

_README_ARTIFACT = re.compile(r"(?:^|/)readme(?:\.md|\.zh\.md|\.i18n\.yaml)$", re.IGNORECASE)
_ROOT_PAIRED_DOCUMENT_ARTIFACT = re.compile(
    r"^(?:adopt|brand_guidelines|contributing|safety)(?:\.md|\.zh\.md|\.i18n\.yaml)?$",
    re.IGNORECASE,
)
#: Packaged adoption mirrors are distribution data, not repository prose; like
#: the frozen archive they are a discovery exclusion rather than manifest
#: entries, because they carry the mirrored language files by design.
_PACKAGED_DATA_PREFIXES = ("src/hdsh/adopt/templates/mirrors/",)
#: Non-hidden directories that are never prose sources. Hidden directories
#: are excluded as a class — any dot-prefixed path segment marks machine-owned
#: territory — with the explicit corpus prefixes below the only exception.
_NON_SOURCE_DIRECTORIES = frozenset(
    {
        "node_modules",
        "lib",
        "venv",
        "coverage",
        "build",
        "dist",
        "tmp",
        "__pycache__",
        "vendor",
    }
)
_EXPLICIT_CORPUS_PREFIXES = (".agents/rfcs/",)
#: Corpus files the harness itself keeps English-only — agent instructions
#: and the translation-memory references. These are corpus constants, not
#: manifest entries: every adopter ships the same standard corpus, so the
#: seeds moved out of the consumer-owned manifest into the scope predicate.
_ENGLISH_ONLY_FILES = frozenset(
    {
        ".agents/rfcs/AGENTS.md",
        ".agents/rfcs/implemented/AGENTS.md",
        ".agents/rfcs/archived/AGENTS.md",
        "docs/AGENTS.md",
        "docs/i18n/terminology.md",
        "docs/i18n/style-samples.md",
    }
)


def _is_excluded_path(file: str) -> bool:
    if file.startswith(_EXPLICIT_CORPUS_PREFIXES):
        return False
    segments = file.split("/")
    return any(
        segment in _NON_SOURCE_DIRECTORIES or (segment.startswith(".") and segment != ".")
        for segment in segments
    )


def is_scope_file(file: str) -> bool:
    """Whether one repository-relative path belongs to the standard bilingual corpus.

    Args:
        file: Repository-relative path with ``/`` separators.

    Returns:
        True when the path is an in-scope pairing artifact of the standard
        corpus — before any consumer manifest extension or exclusion.
    """
    return (
        not file.startswith(".agents/rfcs/archived/")
        and not file.startswith(_PACKAGED_DATA_PREFIXES)
        and not _is_excluded_path(file)
        and file not in _ENGLISH_ONLY_FILES
        and (
            _README_ARTIFACT.search(file) is not None
            or _ROOT_PAIRED_DOCUMENT_ARTIFACT.match(file) is not None
            or file.startswith((".agents/rfcs/", "docs/"))
        )
    )


def corpus_file_predicate(manifest: PairingManifest) -> Callable[[str], bool]:
    """Build the active corpus membership predicate for one manifest.

    The active corpus is the standard scope plus the manifest's ``roots``
    subtrees, minus its ``excluded`` and ``governed`` entries; it drives
    discovery, named-anchor validation, and link-source semantics alike.

    Args:
        manifest: The parsed pairing manifest.

    Returns:
        A predicate over repository-relative paths.
    """

    def is_corpus_file(file: str) -> bool:
        return (is_scope_file(file) or manifest_rooted(file, manifest)) and not (
            manifest_excluded(file, manifest) or manifest_governed(file, manifest)
        )

    return is_corpus_file


def pair_source_predicate(manifest: PairingManifest) -> Callable[[str], bool]:
    """Build the active bilingual-source predicate shared by link consumers.

    Args:
        manifest: The parsed pairing manifest.

    Returns:
        A predicate over repository-relative English Markdown paths.
    """
    return corpus_file_predicate(manifest)
