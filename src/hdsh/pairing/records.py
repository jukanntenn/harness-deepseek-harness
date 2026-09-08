"""Canonical paths, parsing, and rendering for bilingual pairing records."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_META_LINE = re.compile(r"^([^:#]+\.md): ([0-9a-f]{40})$")
_PAIR_SIDES = 2


@dataclass(frozen=True)
class PairPaths:
    """The three repository-relative paths that form one bilingual pair."""

    #: English document path.
    source: str
    #: Simplified Chinese document path.
    zh: str
    #: Generated consistency-record path.
    meta: str


@dataclass(frozen=True)
class PairingRecord:
    """The two content hashes recorded for a bilingual pair."""

    #: Git blob hash of the English document.
    source_hash: str
    #: Git blob hash of the Simplified Chinese document.
    zh_hash: str


def pair_paths(source: str) -> PairPaths:
    """Derive the counterpart and consistency-record paths from an English document.

    Args:
        source: Repository-relative English Markdown path.

    Returns:
        The complete three-path pair.

    Raises:
        ValueError: When the path is not an English ``.md`` path.
    """
    if not source.endswith(".md") or source.endswith(".zh.md"):
        msg = f"expected an English Markdown path, received {source!r}"
        raise ValueError(msg)
    return PairPaths(
        source=source,
        zh=f"{source[: -len('.md')]}.zh.md",
        meta=f"{source[: -len('.md')]}.i18n.yaml",
    )


def pair_paths_from_meta(meta: str) -> PairPaths:
    """Derive one pair from its consistency-record path.

    Args:
        meta: Repository-relative ``foo.i18n.yaml`` path.

    Returns:
        The complete three-path pair.

    Raises:
        ValueError: When the path is not a pairing-record path.
    """
    if not meta.endswith(".i18n.yaml"):
        msg = f"expected a bilingual consistency-record path, received {meta!r}"
        raise ValueError(msg)
    return pair_paths(f"{meta[: -len('.i18n.yaml')]}.md")


def anchor_of_argument(argument: str) -> str:
    """Normalize one CLI pair argument to its English anchor path.

    Any of the pair's three files (``foo.md``, ``foo.zh.md``,
    ``foo.i18n.yaml``) or the bare ``foo`` stem names the same pair.

    Args:
        argument: Repository-relative path as passed on a command line.

    Returns:
        The pair's ``foo.md`` anchor path with ``/`` separators.
    """
    normalized = argument.replace("\\", "/")
    normalized = normalized.removeprefix("./")
    if normalized.endswith(".zh.md"):
        return f"{normalized[: -len('.zh.md')]}.md"
    if normalized.endswith(".i18n.yaml"):
        return f"{normalized[: -len('.i18n.yaml')]}.md"
    if normalized.endswith(".md"):
        return normalized
    return f"{normalized}.md"


def parse_record(content: str, paths: PairPaths) -> PairingRecord | None:
    """Parse a consistency record for its expected sibling names.

    Args:
        content: Complete sidecar text.
        paths: Expected sibling paths.

    Returns:
        The two hashes, or ``None`` for malformed, duplicate, or unexpected keys.
    """
    hashes: dict[str, str] = {}
    for line in content.split("\n"):
        if line == "" or line.startswith("#"):
            continue
        match = _META_LINE.match(line)
        if match is None or match.group(1) in hashes:
            return None
        hashes[match.group(1)] = match.group(2)
    source_name = os.path.basename(paths.source)
    zh_name = os.path.basename(paths.zh)
    if len(hashes) != _PAIR_SIDES or source_name not in hashes or zh_name not in hashes:
        return None
    return PairingRecord(source_hash=hashes[source_name], zh_hash=hashes[zh_name])


def render_record(paths: PairPaths, record: PairingRecord) -> str:
    """Render the canonical consistency record for a pair.

    Args:
        paths: Pair paths written into the record and its recovery command.
        record: Confirmed content hashes.

    Returns:
        Canonical YAML text with exactly one trailing newline.
    """
    return "\n".join(
        [
            "# Bilingual-pair consistency record (docs/i18n/README.md): the git blob",
            "# hash of each side as of the last confirmed-consistent state. Both",
            "# languages carry equal authority;",
            "# after editing either side, bring the other along and re-record with:",
            f"#   hdsh pairing record {paths.source}",
            f"{os.path.basename(paths.source)}: {record.source_hash}",
            f"{os.path.basename(paths.zh)}: {record.zh_hash}",
            "",
        ]
    )
