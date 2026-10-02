"""Validated pairing manifest and its exclusion semantics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: Configuration file the pairing gate reads, relative to the repository root.
MANIFEST_PATH = ".hdsh/pairing.manifest.json"


def _json_loads(content: str) -> Any:  # noqa: ANN401 - JSON values are Any by nature
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


@dataclass(frozen=True)
class PairingManifest:
    """Validated fields of ``.hdsh/pairing.manifest.json``."""

    excluded: tuple[str, ...]
    generated: tuple[str, ...]
    #: Consumer-governed corpus files: bilingual content the repository
    #: maintains under its own discipline; the gate looks away entirely.
    governed: tuple[str, ...]
    #: Corpus subtree roots extending the standard scope; each ends with ``/``.
    roots: tuple[str, ...]
    #: Absolute-URL prefix accepted before switcher counterparts; ``""`` none.
    public_blob_root: str


def parse_manifest(content: str) -> PairingManifest:
    """Parse and validate the checked-in bilingual manifest.

    ``generated`` names English sources whose generator cannot emit the
    English-side language switcher; it resolves to an empty tuple when absent.
    ``public_blob_root`` names the absolute-URL prefix under which a language
    switcher may address its counterpart outside the repository; it resolves
    to an empty string when absent.

    Args:
        content: Complete manifest file text.

    Returns:
        The validated manifest.

    Raises:
        ValueError: When the manifest is not an object holding exactly an
            ``excluded`` array of strings, an optional ``generated`` array of
            strings, an optional ``governed`` array of strings, an optional
            ``roots`` array of trailing-slash subtree prefixes, and an
            optional ``public_blob_root`` http(s) URL prefix ending in ``/``.
        TypeError: When the manifest is not an object.
    """
    try:
        value: Any = _json_loads(content)
    except ValueError as error:
        msg = f"{MANIFEST_PATH}: {error}"
        raise ValueError(msg) from error
    if not isinstance(value, dict):
        msg = f"{MANIFEST_PATH}: expected an object"
        raise TypeError(msg)
    supported = ("excluded", "generated", "governed", "roots", "public_blob_root")
    unsupported = [key for key in value if key not in supported]
    if unsupported:
        msg = (
            f"{MANIFEST_PATH}: unsupported field(s): {', '.join(unsupported)}; "
            "every in-scope document is required"
        )
        raise ValueError(msg)
    entries = value.get("excluded", [])
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        msg = f"{MANIFEST_PATH}: excluded must be an array of strings"
        raise ValueError(msg)
    generated = value.get("generated", [])
    if not isinstance(generated, list) or not all(isinstance(entry, str) for entry in generated):
        msg = f"{MANIFEST_PATH}: generated must be an array of strings"
        raise ValueError(msg)
    governed = value.get("governed", [])
    if not isinstance(governed, list) or not all(isinstance(entry, str) for entry in governed):
        msg = f"{MANIFEST_PATH}: governed must be an array of strings"
        raise ValueError(msg)
    roots = value.get("roots", [])
    if not isinstance(roots, list) or not all(
        isinstance(entry, str) and entry.endswith("/") and not entry.startswith("/")
        for entry in roots
    ):
        msg = f"{MANIFEST_PATH}: roots must be an array of trailing-slash subtree prefixes"
        raise ValueError(msg)
    root = value.get("public_blob_root", "")
    if not isinstance(root, str):
        msg = f"{MANIFEST_PATH}: public_blob_root must be a string"
        raise TypeError(msg)
    if root and not (root.startswith(("http://", "https://")) and root.endswith("/")):
        msg = f"{MANIFEST_PATH}: public_blob_root must be an http(s) URL prefix ending in /"
        raise ValueError(msg)
    return PairingManifest(
        excluded=tuple(entries),
        generated=tuple(generated),
        governed=tuple(governed),
        roots=tuple(roots),
        public_blob_root=root,
    )


def manifest_excluded(file: str, manifest: PairingManifest) -> bool:
    """Whether a manifest entry excludes one exact file or directory subtree.

    A trailing ``/`` is the path boundary: ``docs/catalog/`` cannot prefix-match
    a sibling like ``docs/catalog-notes/x.md``.

    Args:
        file: Repository-relative path.
        manifest: The parsed manifest.

    Returns:
        True when the file is excluded from pairing.
    """
    return any(
        file.startswith(entry) if entry.endswith("/") else file == entry
        for entry in manifest.excluded
    )


def manifest_governed(file: str, manifest: PairingManifest) -> bool:
    """Whether a manifest entry marks one file or subtree consumer-governed.

    Governed content may keep its translation — the repository maintains it
    under its own discipline — but it leaves the corpus entirely: no
    completeness, consistency, or switcher checks run for it.

    Args:
        file: Repository-relative path.
        manifest: The parsed manifest.

    Returns:
        True when the file is governed elsewhere.
    """
    return any(
        file.startswith(entry) if entry.endswith("/") else file == entry
        for entry in manifest.governed
    )


def manifest_rooted(file: str, manifest: PairingManifest) -> bool:
    """Whether one corpus root subtree contains the file.

    Args:
        file: Repository-relative path.
        manifest: The parsed manifest.

    Returns:
        True when a ``roots`` entry prefixes the file.
    """
    return any(file.startswith(entry) for entry in manifest.roots)
