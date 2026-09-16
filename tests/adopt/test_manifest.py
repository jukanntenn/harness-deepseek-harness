"""The adopt manifest: digests, loading, and saving."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hdsh.adopt.manifest import (
    AdoptManifest,
    ManifestError,
    file_digest,
    load_manifest,
    save_manifest,
)


class TestFileDigest:
    def test_digest_is_stable_and_hexadecimal(self) -> None:
        digest = file_digest(b"adopt")
        assert digest == file_digest(b"adopt")
        assert digest != file_digest(b"adopt2")
        assert len(digest) == 64
        int(digest, 16)


class TestLoadManifest:
    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ManifestError, match="missing or unreadable"):
            load_manifest(str(tmp_path))

    def test_non_object_manifest_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".hdsh").mkdir()
        (tmp_path / ".hdsh" / "adopt.manifest.json").write_text("[]", encoding="utf-8")
        with pytest.raises(ManifestError, match="must be a JSON object"):
            load_manifest(str(tmp_path))

    def test_missing_header_fields_raise(self, tmp_path: Path) -> None:
        path = tmp_path / ".hdsh" / "adopt.manifest.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"files": {}}), encoding="utf-8")
        with pytest.raises(ManifestError, match="hdshVersion and hdshRef"):
            load_manifest(str(tmp_path))

    def test_malformed_editable_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / ".hdsh" / "adopt.manifest.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps({"hdshVersion": "0.1.0", "hdshRef": "v0.1.0", "files": {}, "editable": 3}),
            encoding="utf-8",
        )
        with pytest.raises(ManifestError, match="editable list"):
            load_manifest(str(tmp_path))

    def test_malformed_files_object_raises(self, tmp_path: Path) -> None:
        path = tmp_path / ".hdsh" / "adopt.manifest.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps({"hdshVersion": "0.1.0", "hdshRef": "v0.1.0", "files": {"a": 1}}),
            encoding="utf-8",
        )
        with pytest.raises(ManifestError, match="files object"):
            load_manifest(str(tmp_path))

    def test_round_trip_preserves_state(self, tmp_path: Path) -> None:
        save_manifest(
            str(tmp_path),
            AdoptManifest(
                hdsh_version="0.1.0",
                hdsh_ref="v0.1.0",
                files={"a.md": "d1"},
                editable=("AGENTS.md",),
            ),
        )
        loaded = load_manifest(str(tmp_path))
        assert loaded.hdsh_version == "0.1.0"
        assert loaded.hdsh_ref == "v0.1.0"
        assert loaded.files == {"a.md": "d1"}
        assert loaded.editable == ("AGENTS.md",)
