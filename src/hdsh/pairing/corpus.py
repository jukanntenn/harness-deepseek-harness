"""Scope predicates selecting the repository's bilingual pairing corpus."""

from __future__ import annotations

import re
from collections.abc import Callable

from hdsh.pairing.manifest import PairingManifest, manifest_excluded

_README_ARTIFACT = re.compile(r"(?:^|/)readme(?:\.md|\.zh\.md|\.i18n\.yaml)$", re.IGNORECASE)
_ROOT_PAIRED_DOCUMENT_ARTIFACT = re.compile(
    r"^(?:brand_guidelines|contributing|safety)(?:\.md|\.zh\.md|\.i18n\.yaml)$",
    re.IGNORECASE,
)
_NON_SOURCE_DIRECTORIES = frozenset(
    {
        "node_modules",
        "lib",
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
        ".local",
        ".hdsh-env",
        ".prek",
        "vendor",
    }
)


def _is_excluded_path(file: str) -> bool:
    segments = file.split("/")
    return any(segment in _NON_SOURCE_DIRECTORIES for segment in segments)


def is_scope_file(file: str) -> bool:
    """Whether one repository-relative path belongs to the bilingual source corpus.

    Args:
        file: Repository-relative path with ``/`` separators.

    Returns:
        True when the path is an in-scope pairing artifact.
    """
    return (
        not file.startswith(".agents/rfcs/archived/")
        and not _is_excluded_path(file)
        and (
            _README_ARTIFACT.search(file) is not None
            or _ROOT_PAIRED_DOCUMENT_ARTIFACT.match(file) is not None
            or file.startswith((".agents/rfcs/", "docs/"))
        )
    )


def pair_source_predicate(manifest: PairingManifest) -> Callable[[str], bool]:
    """Build the active bilingual-source predicate shared by link consumers.

    Args:
        manifest: The parsed pairing manifest.

    Returns:
        A predicate over repository-relative English Markdown paths.
    """

    def is_pair_source(source_path: str) -> bool:
        return is_scope_file(source_path) and not manifest_excluded(source_path, manifest)

    return is_pair_source
