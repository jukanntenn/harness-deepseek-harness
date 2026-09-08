"""Markdown parsing helpers shared by the documentation gates."""

from __future__ import annotations

from hdsh.docs.markdown import (
    document_anchors,
    document_destinations,
    fragment_part,
    github_slug,
    hard_wrapped_paragraphs,
    is_external_url,
    mask_non_paragraph_structure,
    path_part,
)


class TestMasking:
    def test_frontmatter_is_masked(self) -> None:
        masked = mask_non_paragraph_structure("---\ntitle: wrapped\n  across lines\n---\n\nbody\n")
        assert hard_wrapped_paragraphs(masked) == []

    def test_unclosed_frontmatter_is_left_alone(self) -> None:
        source = "---\nstill prose\n"
        assert mask_non_paragraph_structure(source) == source

    def test_vitepress_container_lines_are_masked(self) -> None:
        source = "::: warning\ncontent\n:::\n"
        assert mask_non_paragraph_structure(source) == "\ncontent\n\n"


class TestHardWrappedParagraphs:
    def test_single_line_paragraphs_pass(self) -> None:
        assert hard_wrapped_paragraphs("# Title\n\none line per paragraph.\n") == []

    def test_multi_line_paragraph_is_reported_with_line_and_text(self) -> None:
        source = "# Title\n\nfirst line of prose\ncontinues here\n"
        violations = hard_wrapped_paragraphs(source)
        assert [(v.line, v.text) for v in violations] == [(3, "first line of prose")]

    def test_wrapped_prose_inside_lists_and_quotes_is_reported(self) -> None:
        source = "- item text\n  wrapped further\n\n> quoted text\n> wrapped too\n"
        violations = hard_wrapped_paragraphs(source)
        assert [v.line for v in violations] == [1, 4]

    def test_fenced_code_and_tables_never_violate(self) -> None:
        source = (
            "```md\nhard wrapped\nsample text\n```\n\n| a | b |\n|---|---|\n| one | two words |\n"
        )
        assert hard_wrapped_paragraphs(source) == []

    def test_frontmattered_document_passes_whole_pipeline(self) -> None:
        source = "---\nkeys:\n  - wrapped\n  - values\n---\n\n# Title\n\none line.\n"
        assert hard_wrapped_paragraphs(source) == []


class TestUrlHelpers:
    def test_external_and_absolute_targets_are_recognized(self) -> None:
        assert is_external_url("https://example.com/")
        assert is_external_url("mailto:a@b.example")
        assert is_external_url("//host/path")
        assert is_external_url("/root/absolute.md")
        assert not is_external_url("docs/README.md")
        assert not is_external_url("#fragment")

    def test_path_part_strips_and_decodes(self) -> None:
        assert path_part("My%20File.md#head?not=query") == "My File.md"
        assert path_part("READ%4DE.md?query") == "README.md"
        assert path_part("%zz-broken.md") == "%zz-broken.md"
        assert path_part("%ff-invalid-utf8.md") == "%ff-invalid-utf8.md"

    def test_fragment_part_decodes_or_absent(self) -> None:
        assert fragment_part("a.md#showcase") == "showcase"
        assert fragment_part("a.md#frag?kept-out") == "frag"
        assert fragment_part("a.md#%e6%8e%a8%e8%bf%9f") == "推迟"
        assert fragment_part("a.md#%zz") == "%zz"
        assert fragment_part("a.md") is None


class TestDocumentAnchors:
    def test_slugs_rendered_text_suffixes_repeats_and_reads_explicit_anchors(self) -> None:
        anchors = document_anchors(
            '# My Doc\n## Live `events` — mode!\n## Repeat\n## Repeat\n<a id="hand-anchor"></a>\n'
        )
        assert anchors == {"my-doc", "live-events--mode", "repeat", "repeat-1", "hand-anchor"}
        assert github_slug("Security and authority are non-goals") == (
            "security-and-authority-are-non-goals"
        )

    def test_underscores_survive_the_way_github_keeps_them(self) -> None:
        assert github_slug("Showcase: web_fetch") == "showcase-web_fetch"
        assert document_anchors("## Showcase: web_fetch\n") == {"showcase-web_fetch"}

    def test_cjk_headings_keep_their_characters(self) -> None:
        assert document_anchors("## 推迟工作\n") == {"推迟工作"}

    def test_linked_heading_slugs_from_rendered_text(self) -> None:
        assert document_anchors("## [Install](setup.md)\n") == {"install"}

    def test_image_heading_slugs_from_alt_text(self) -> None:
        assert document_anchors("## ![flow diagram](flow.png)\n") == {"flow-diagram"}

    def test_multiline_setext_heading_slugs_with_breaks(self) -> None:
        assert document_anchors("foo\nbar\n===\n") == {"foo-bar"}

    def test_repeat_suffixes_bump_past_occupied_slugs(self) -> None:
        anchors = document_anchors("## Repeat\n## Repeat-1\n## Repeat\n")
        assert anchors == {"repeat", "repeat-1", "repeat-2"}

    def test_explicit_anchors_ignored_inside_code_and_comments(self) -> None:
        anchors = document_anchors(
            "# Doc\n"
            "```md\n"
            '<a id="fenced"></a>\n'
            "```\n"
            'Inline `<a id="inline"></a>` sample.\n'
            '<!-- <a id="commented"></a> -->\n'
            '<a id="real"></a>\n'
        )
        assert anchors == {"doc", "real"}


class TestDocumentDestinations:
    def test_links_images_and_definitions_carry_lines(self) -> None:
        source = (
            "# Doc\n\n[text](rel.md#a) and ![alt](img.png)\n\n[ref]: other.md#b\n\nuse [ref] now\n"
        )
        destinations = document_destinations(source)
        # markdown-it resolves reference uses at their use site rather than
        # only at the definition, so the same destination is checked at both
        # lines, in document order.
        assert [(d.line, d.url) for d in destinations] == [
            (3, "rel.md#a"),
            (3, "img.png"),
            (5, "other.md#b"),
            (7, "other.md#b"),
        ]

    def test_shadowed_duplicate_definitions_are_still_collected(self) -> None:
        destinations = document_destinations("# T\n\n[lbl]: a.md\n\n[lbl]: broken.md\n")
        assert [(d.line, d.url) for d in destinations] == [(3, "a.md"), (5, "broken.md")]

    def test_links_in_wrapped_blocks_report_their_own_lines(self) -> None:
        source = "para one\nsecond [link](x.md)\nthird ![img](y.png)\n"
        assert [(d.line, d.url) for d in document_destinations(source)] == [
            (2, "x.md"),
            (3, "y.png"),
        ]

    def test_destinations_keep_authored_text(self) -> None:
        source = "# T\n\n[a](%zz-file.md) [b](<My File.md>) [c](推迟.md)\n"
        assert [d.url for d in document_destinations(source)] == [
            "%zz-file.md",
            "My File.md",
            "推迟.md",
        ]
