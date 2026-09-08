"""Pairing-manifest parsing and exclusion semantics."""

from __future__ import annotations

import pytest

from hdsh.pairing.manifest import manifest_excluded, parse_manifest


class TestManifest:
    def test_parses_excluded_only(self) -> None:
        manifest = parse_manifest('{"excluded": ["docs/x.md", "docs/y/"]}')
        assert manifest.excluded == ("docs/x.md", "docs/y/")
        assert manifest_excluded("docs/x.md", manifest)
        assert manifest_excluded("docs/y/z.md", manifest)
        assert not manifest_excluded("docs/y2/z.md", manifest)
        assert not manifest_excluded("docs/other.md", manifest)

    def test_rejects_unsupported_field(self) -> None:
        with pytest.raises(ValueError, match="unsupported field"):
            parse_manifest('{"excluded": [], "rollout": []}')

    def test_parses_generated(self) -> None:
        manifest = parse_manifest('{"excluded": [], "generated": ["docs/catalog.md"]}')
        assert manifest.generated == ("docs/catalog.md",)

    def test_generated_defaults_to_empty(self) -> None:
        assert parse_manifest('{"excluded": []}').generated == ()

    def test_rejects_non_array_generated(self) -> None:
        with pytest.raises(ValueError, match="generated must be an array of strings"):
            parse_manifest('{"excluded": [], "generated": "docs/catalog.md"}')

    def test_rejects_non_array(self) -> None:
        with pytest.raises(ValueError, match="array of strings"):
            parse_manifest('{"excluded": "docs/"}')

    def test_rejects_non_object(self) -> None:
        with pytest.raises(TypeError, match="expected an object"):
            parse_manifest("[]")

    def test_rejects_invalid_json(self) -> None:
        with pytest.raises(ValueError, match="manifest"):
            parse_manifest("{nope")

    def test_rejects_duplicate_keys(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            parse_manifest('{"excluded": [], "excluded": []}')

    def test_rejects_non_string_exclusion_entries(self) -> None:
        with pytest.raises(ValueError, match="array of strings"):
            parse_manifest('{"excluded": [42]}')

    def test_public_blob_root_defaults_to_empty(self) -> None:
        manifest = parse_manifest('{"excluded": []}')
        assert manifest.public_blob_root == ""

    def test_accepts_an_http_url_prefix_ending_in_slash(self) -> None:
        manifest = parse_manifest(
            '{"excluded": [], "public_blob_root": "https://example.com/repo/blob/main/"}'
        )
        assert manifest.public_blob_root == "https://example.com/repo/blob/main/"

    def test_rejects_non_string_public_blob_root(self) -> None:
        with pytest.raises(TypeError, match="public_blob_root must be a string"):
            parse_manifest('{"excluded": [], "public_blob_root": 7}')

    def test_rejects_a_prefix_without_trailing_slash(self) -> None:
        with pytest.raises(ValueError, match="http\\(s\\) URL prefix"):
            parse_manifest('{"excluded": [], "public_blob_root": "https://example.com/repo"}')

    def test_rejects_a_non_http_prefix(self) -> None:
        with pytest.raises(ValueError, match="http\\(s\\) URL prefix"):
            parse_manifest('{"excluded": [], "public_blob_root": "ftp://example.com/repo/"}')
