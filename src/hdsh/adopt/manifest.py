"""The adopt manifest: what was installed, from which hdsh, at which bytes.

The manifest is the upgrade contract. ``hdsh adopt apply`` writes it after
every installation; ``hdsh adopt verify`` compares the working tree against
it and counts the remaining ``TODO(adopt):`` placeholders. Generated files
are upstream-owned — consumers redirect changes upstream, and ``apply`` under
a newer hdsh refuses consumer-modified files instead of overwriting them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

MANIFEST_PATH = ".hdsh/adopt.manifest.json"


@dataclass(frozen=True)
class AdoptManifest:
    """The recorded state of one adoption."""

    #: Version of the installed hdsh package that wrote the manifest.
    hdsh_version: str
    #: Pinned harness-deepseek-harness ref the installation rendered from.
    hdsh_ref: str
    #: Upstream-owned destination path to the SHA-256 digest of the installed
    #: bytes; drift here refuses re-application until reverted.
    files: dict[str, str]
    #: Consumer-completable destinations installed as placeholder templates;
    #: verify counts their ``TODO(adopt):`` markers instead of digests.
    editable: tuple[str, ...] = ()


class ManifestError(ValueError):
    """The adopt manifest is missing or malformed."""


def file_digest(content: bytes) -> str:
    """Return the SHA-256 digest used by the adopt manifest.

    Args:
        content: Installed file bytes.

    Returns:
        The lowercase hexadecimal digest.
    """
    return hashlib.sha256(content).hexdigest()


def load_manifest(root: str) -> AdoptManifest:
    """Read and validate the repository's adopt manifest.

    Args:
        root: Consumer repository root.

    Returns:
        The recorded adoption state.

    Raises:
        ManifestError: When the manifest is missing or malformed.
    """
    path = Path(root, MANIFEST_PATH)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        msg = f"{MANIFEST_PATH} is missing or unreadable ({error}); run hdsh adopt apply first"
        raise ManifestError(msg) from error
    if not isinstance(value, dict):
        msg = f"{MANIFEST_PATH} must be a JSON object"
        raise ManifestError(msg)
    hdsh_version = value.get("hdshVersion")
    hdsh_ref = value.get("hdshRef")
    files = value.get("files")
    editable = value.get("editable", [])
    if not isinstance(hdsh_version, str) or not isinstance(hdsh_ref, str):
        msg = f"{MANIFEST_PATH} requires string hdshVersion and hdshRef fields"
        raise ManifestError(msg)
    if not isinstance(files, dict) or not all(
        isinstance(key, str) and isinstance(digest, str) for key, digest in files.items()
    ):
        msg = f"{MANIFEST_PATH} requires a files object mapping paths to digests"
        raise ManifestError(msg)
    if not isinstance(editable, list) or not all(isinstance(path, str) for path in editable):
        msg = f"{MANIFEST_PATH} requires an editable list of paths"
        raise ManifestError(msg)
    return AdoptManifest(
        hdsh_version=hdsh_version,
        hdsh_ref=hdsh_ref,
        files=dict(files),
        editable=tuple(editable),
    )


def save_manifest(root: str, manifest: AdoptManifest) -> None:
    """Write the adopt manifest.

    Args:
        root: Consumer repository root.
        manifest: The adoption state to record.
    """
    payload = {
        "hdshVersion": manifest.hdsh_version,
        "hdshRef": manifest.hdsh_ref,
        "files": dict(sorted(manifest.files.items())),
        "editable": sorted(manifest.editable),
    }
    path = Path(root, MANIFEST_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
