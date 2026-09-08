"""Generated-region grammar and structural-signature comparison."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from hdsh.pairing.links import LinkContext
from hdsh.pairing.structure import (
    GeneratedRegionPartition,
    StructureSignature,
    parse_markdown,
    partition_generated_regions,
    structure_diff,
    structure_signature,
)


class TestPartitionGeneratedRegions:
    def test_extracts_one_balanced_region(self) -> None:
        marker = "<!-- BEGIN GENERATED catalog -->\ncontent\n<!-- END GENERATED catalog -->"
        partition = partition_generated_regions(f"before\n{marker}\nafter\n")
        assert partition.regions == [
            "<!-- BEGIN GENERATED catalog -->\ncontent\n<!-- END GENERATED catalog -->"
        ]
        assert partition.stripped == "before\nafter\n"

    def test_begin_without_end_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="without an END"):
            partition_generated_regions("<!-- BEGIN GENERATED a -->\nbody")

    def test_end_without_begin_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="without a BEGIN"):
            partition_generated_regions("<!-- END GENERATED a -->")

    def test_nested_begin_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="nested"):
            partition_generated_regions(
                "<!-- BEGIN GENERATED a -->\n"
                "<!-- BEGIN GENERATED b -->\n<!-- END GENERATED b -->\n"
                "<!-- END GENERATED a -->"
            )

    def test_slug_mismatch_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            partition_generated_regions("<!-- BEGIN GENERATED a -->\n<!-- END GENERATED b -->")

    def test_malformed_marker_hint_is_rejected(self) -> None:
        # Matches the loose hint but not the complete marker grammar.
        with pytest.raises(ValueError, match="malformed"):
            partition_generated_regions("<!-- BEGIN GENERATED  -->")

    def test_regionless_document_passes_through(self) -> None:
        partition = partition_generated_regions("plain\ntext\n")
        assert partition == GeneratedRegionPartition(regions=[], stripped="plain\ntext\n")


class TestStructureDiff:
    def test_diff_reports_first_divergence_per_field(self) -> None:
        source = StructureSignature(
            headings=[1, 2], code=[], tables=[], lists=["bullet:items=2"], links=["a"]
        )
        zh = StructureSignature(headings=[1, 3], code=[], tables=[], lists=[], links=[])
        diff = structure_diff(source, zh)
        assert len(diff) == 3
        assert "heading (depth) #2" in diff[0]
        assert "list (kind, start, item count) #1" in diff[1]
        assert "link target #1" in diff[2]

    def test_equal_signatures_diff_empty(self) -> None:
        sig = StructureSignature(
            headings=[1], code=["```py\nx"], tables=["2x3"], lists=[], links=[]
        )
        assert structure_diff(sig, sig) == []


class TestSignatureCollection:
    def test_signature_table_and_ordered_list(self) -> None:
        markdown = (
            "# T\n\n"
            "    indented code\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n"
            "3. third\n4. fourth\n"
        )
        context = LinkContext(
            repo_root=".",
            source_path="docs/x.md",
            is_pair_source=lambda p: False,
            repository_file_exists=lambda p: False,
            markdown=markdown,
        )
        signature = structure_signature(parse_markdown(markdown), ["x"], context)
        assert signature.tables == ["3x2"]
        assert signature.lists == ["ordered:start=3:items=2"]
        assert signature.code == ["```\nindented code\n"]

    def test_diff_reports_code_and_table_fields(self) -> None:
        left = StructureSignature(code=["```py\nx"], tables=["2x2"])
        right = StructureSignature(code=["```js\nx"], tables=["2x3"])
        diff = structure_diff(left, right)
        assert any("code block" in d for d in diff)
        assert any("table" in d for d in diff)

    def test_long_values_truncate_in_diff(self) -> None:
        long_code = "```py\n" + "x" * 200
        left = StructureSignature(code=[long_code])
        right = StructureSignature(code=["other"])
        diff = structure_diff(left, right)
        assert any("…" in d for d in diff)


class TestSignatureLinkSemantics:
    def _signature(self, markdown: str, switcher: Sequence[str] = ()) -> StructureSignature:
        context = LinkContext(
            repo_root=".",
            source_path="docs/x.md",
            is_pair_source=lambda p: False,
            repository_file_exists=lambda p: False,
            markdown=markdown,
        )
        return structure_signature(parse_markdown(markdown), list(switcher), context)

    def test_nested_lists_record_outer_before_inner(self) -> None:
        markdown = "- outer a\n  - inner\n- outer b\n"
        assert self._signature(markdown).lists == ["bullet:items=2", "bullet:items=1"]

    def test_switcher_link_is_excluded_but_body_links_are_kept(self) -> None:
        markdown = "# 指南\n\n[English](guide.md) | 中文\n\n[正文](guide.md)\n"
        context = LinkContext(
            repo_root=".",
            source_path="guide.zh.md",
            is_pair_source=lambda p: False,
            repository_file_exists=lambda p: False,
            markdown=markdown,
        )
        signature = structure_signature(parse_markdown(markdown), ["guide.md"], context)
        assert signature.links == ["guide.md"]

    def test_external_targets_keep_authored_bytes(self) -> None:
        escaped = self._signature("[External](https://example.com/?x=1&amp;y=2)\n")
        literal = self._signature("[External](https://example.com/?x=1&y=2)\n")
        assert escaped.links == ["https://example.com/?x=1&amp;y=2"]
        assert literal.links == ["https://example.com/?x=1&y=2"]
        message = (
            "link target #1 diverges between the pair: "
            "'https://example.com/?x=1&amp;y=2' vs 'https://example.com/?x=1&y=2'"
        )
        assert structure_diff(escaped, literal) == [message]

    def test_angle_autolink_enters_the_signature(self) -> None:
        markdown = "<https://example.com/reference.md>\n"
        assert self._signature(markdown).links == ["https://example.com/reference.md"]

    def test_bare_email_enters_the_signature_with_authored_bytes(self) -> None:
        markdown = "Mail foo@bar.com for details.\n"
        assert self._signature(markdown).links == ["foo@bar.com"]

    def test_reference_links_enter_the_signature_at_reference_order(self) -> None:
        markdown = "[a][one] [b][two]\n\n[one]: x.md\n[two]: y.md\n"
        assert self._signature(markdown).links == ["x.md", "y.md"]

    def test_inline_line_without_map_skips_switcher_compare(self) -> None:
        # An inline token without map never equals the switcher line, so its
        # links still enter the signature.
        markdown = "# T\n\nSee [guide](guide.md).\n"
        context = LinkContext(
            repo_root=".",
            source_path="docs/other.md",
            is_pair_source=lambda p: False,
            repository_file_exists=lambda p: False,
            markdown=markdown,
        )
        signature = structure_signature(parse_markdown(markdown), ["none.md"], context)
        assert signature.links == ["guide.md"]
