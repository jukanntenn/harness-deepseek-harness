"""Validated configuration for the documentation gates.

The three documentation gates read their deployment-varying choices — corpus
globs and word ceilings — from ``.hdsh/docs.manifest.json`` in the consuming
repository. The manifest may carry any subset of the three sections; each
gate fails loudly when its own section is absent, so an installed hook can
never pass by silently checking nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Configuration file every documentation gate reads, relative to the repository root.
MANIFEST_PATH = ".hdsh/docs.manifest.json"

#: Sections a manifest may carry; anything else is rejected.
SECTION_KEYS = ("markdownWrap", "markdownLinks", "docBudgets")


class DocsConfigError(Exception):
    """Raised when the docs manifest is absent, unreadable, or invalid."""


@dataclass(frozen=True)
class CorpusScope:
    """Include/exclude glob pair selecting one gate's Markdown corpus.

    Patterns are repository-relative pathlib globs; ``exclude`` is matched
    with the same semantics, so ``.agents/rfcs/archived/**`` removes a whole
    frozen subtree.
    """

    #: Repository-relative glob patterns; a file is selected by any of them.
    include: tuple[str, ...]
    #: Repository-relative glob patterns removing matched files from the corpus.
    exclude: tuple[str, ...]


@dataclass(frozen=True)
class DocsManifest:
    """Validated fields of ``.hdsh/docs.manifest.json``.

    Each section is ``None`` when the manifest omits it; the gate owning that
    section refuses to run instead of checking nothing.
    """

    markdown_wrap: CorpusScope | None
    markdown_links: CorpusScope | None
    doc_budgets: dict[str, int] | None


def _loads_rejecting_duplicates(content: str) -> Any:  # noqa: ANN401 - JSON values are Any by nature
    """Parse JSON text rejecting duplicate object keys."""

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                msg = f"duplicate object key: {key}"
                raise ValueError(msg)
            obj[key] = value
        return obj

    return json.loads(content, object_pairs_hook=hook)


def _validate_pattern(section: str, pattern: str) -> None:
    if pattern.startswith(("/", "\\")) or any(part == ".." for part in pattern.split("/")):
        msg = f"{section}: pattern {pattern!r} must stay inside the repository"
        raise ValueError(msg)


def _parse_scope(section: str, value: Any) -> CorpusScope:  # noqa: ANN401 - validated JSON value
    if not isinstance(value, dict) or set(value) != {"include", "exclude"}:
        msg = f"{section} must be an object with exactly the fields include and exclude"
        raise ValueError(msg)
    include = value["include"]
    exclude = value["exclude"]
    if (
        not isinstance(include, list)
        or not include
        or not all(isinstance(pattern, str) and pattern for pattern in include)
    ):
        msg = f"{section}.include must be a non-empty array of non-empty glob strings"
        raise ValueError(msg)
    if not isinstance(exclude, list) or not all(
        isinstance(pattern, str) and pattern for pattern in exclude
    ):
        msg = f"{section}.exclude must be an array of non-empty glob strings"
        raise ValueError(msg)
    for pattern in (*include, *exclude):
        _validate_pattern(section, pattern)
    return CorpusScope(include=tuple(include), exclude=tuple(exclude))


def _parse_budgets(section: str, value: Any) -> dict[str, int]:  # noqa: ANN401 - validated JSON value
    if not isinstance(value, dict) or not value:
        msg = f"{section} must be a non-empty object mapping document paths to word ceilings"
        raise ValueError(msg)
    out: dict[str, int] = {}
    for path, ceiling in value.items():
        if not isinstance(path, str) or not path:
            msg = f"{section}: budgeted paths must be non-empty strings"
            raise ValueError(msg)
        if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling <= 0:
            msg = f"{section}.{path}: ceiling must be a positive integer, got {ceiling!r}"
            raise ValueError(msg)
        out[path] = ceiling
    return out


def parse_docs_manifest(content: str) -> DocsManifest:
    """Parse and validate the checked-in docs manifest.

    Args:
        content: Complete manifest file text.

    Returns:
        The validated manifest with ``None`` for every omitted section.

    Raises:
        TypeError: When the manifest is not an object.
        ValueError: When the manifest carries unknown sections or any
            present section is malformed.
    """
    value: Any = _loads_rejecting_duplicates(content)
    if not isinstance(value, dict):
        msg = "expected an object"
        raise TypeError(msg)
    unknown = sorted(set(value) - set(SECTION_KEYS))
    if unknown:
        msg = (
            f"unsupported section(s): {', '.join(unknown)}; "
            f"expected any of {', '.join(SECTION_KEYS)}"
        )
        raise ValueError(msg)
    return DocsManifest(
        markdown_wrap=(
            _parse_scope("markdownWrap", value["markdownWrap"]) if "markdownWrap" in value else None
        ),
        markdown_links=(
            _parse_scope("markdownLinks", value["markdownLinks"])
            if "markdownLinks" in value
            else None
        ),
        doc_budgets=(
            _parse_budgets("docBudgets", value["docBudgets"]) if "docBudgets" in value else None
        ),
    )


def load_docs_manifest(root: Path) -> DocsManifest:
    """Load and validate the manifest of the repository at ``root``.

    Args:
        root: Absolute repository root.

    Returns:
        The validated manifest.

    Raises:
        DocsConfigError: When the manifest is missing, unreadable, or
            invalid.
    """
    path = root / MANIFEST_PATH
    if not path.is_file():
        msg = f"{MANIFEST_PATH} not found — the documentation gates read their scope from it"
        raise DocsConfigError(msg)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        msg = f"{MANIFEST_PATH}: cannot be read: {error}"
        raise DocsConfigError(msg) from error
    try:
        return parse_docs_manifest(content)
    except (TypeError, ValueError) as error:
        msg = f"{MANIFEST_PATH}: {error}"
        raise DocsConfigError(msg) from error


def missing_section_error(section: str, tool: str) -> DocsConfigError:
    """Build the loud failure a gate raises when its manifest section is absent.

    Args:
        section: The required manifest section name.
        tool: The gate's CLI name for the diagnostic.

    Returns:
        The error to raise; the gate never runs over an implicit empty corpus.
    """
    return DocsConfigError(
        f"{MANIFEST_PATH}: {section} section is required by {tool}; add it or uninstall the hook"
    )
