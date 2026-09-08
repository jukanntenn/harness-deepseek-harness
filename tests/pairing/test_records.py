"""Pair-record paths, parsing, rendering, and CLI anchor normalization."""

from __future__ import annotations

import pytest

from hdsh.pairing.records import (
    PairingRecord,
    PairPaths,
    anchor_of_argument,
    pair_paths,
    pair_paths_from_meta,
    parse_record,
    render_record,
)


class TestRecordPaths:
    def test_derives_pair_paths(self) -> None:
        paths = pair_paths("docs/guide.md")
        assert paths == PairPaths(
            source="docs/guide.md", zh="docs/guide.zh.md", meta="docs/guide.i18n.yaml"
        )

    def test_rejects_non_english_path(self) -> None:
        with pytest.raises(ValueError, match="English Markdown path"):
            pair_paths("docs/guide.zh.md")
        with pytest.raises(ValueError, match="English Markdown path"):
            pair_paths("docs/guide.txt")

    def test_derives_from_meta(self) -> None:
        assert pair_paths_from_meta("docs/guide.i18n.yaml") == pair_paths("docs/guide.md")
        with pytest.raises(ValueError, match="consistency-record path"):
            pair_paths_from_meta("docs/guide.md")


class TestRecordParse:
    def setup_method(self) -> None:
        self.paths = pair_paths("docs/guide.md")

    def test_parses_canonical_record(self) -> None:
        record = parse_record(
            f"# note\nguide.md: {'a' * 40}\nguide.zh.md: {'b' * 40}\n", self.paths
        )
        assert record == PairingRecord("a" * 40, "b" * 40)

    def test_rejects_missing_sibling(self) -> None:
        assert parse_record(f"guide.md: {'a' * 40}\n", self.paths) is None

    def test_rejects_unexpected_key(self) -> None:
        assert (
            parse_record(
                f"guide.md: {'a' * 40}\nguide.zh.md: {'b' * 40}\nother.md: {'c' * 40}\n",
                self.paths,
            )
            is None
        )

    def test_rejects_malformed_hash(self) -> None:
        assert parse_record("guide.md: xyz\nguide.zh.md: x\n", self.paths) is None

    def test_rejects_duplicate(self) -> None:
        assert parse_record(f"guide.md: {'a' * 40}\nguide.md: {'a' * 40}\n", self.paths) is None

    def test_render_round_trips(self) -> None:
        record = PairingRecord("a" * 40, "b" * 40)
        text = render_record(self.paths, record)
        assert text.endswith("\n") and not text.endswith("\n\n")
        assert "hdsh pairing record docs/guide.md" in text
        assert parse_record(text, self.paths) == record


class TestPairAnchor:
    def test_normalizes_every_naming(self) -> None:
        assert anchor_of_argument("docs/guide.md") == "docs/guide.md"
        assert anchor_of_argument("docs/guide.zh.md") == "docs/guide.md"
        assert anchor_of_argument("docs/guide.i18n.yaml") == "docs/guide.md"
        assert anchor_of_argument("docs/guide") == "docs/guide.md"
        assert anchor_of_argument(".\\docs\\guide.zh.md") == "docs/guide.md"
        assert anchor_of_argument("./docs/guide.md") == "docs/guide.md"

    def test_leading_dot_slash_is_stripped_exactly_once(self) -> None:
        # Exactly one strip: `././docs/x` keeps a leading `./` and therefore
        # names no in-scope anchor.
        assert anchor_of_argument("././docs/guide.md") == "./docs/guide.md"
