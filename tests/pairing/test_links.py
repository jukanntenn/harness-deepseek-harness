"""Locale-aware link resolution, authored bytes, and language-switcher detection."""

from __future__ import annotations

import pytest

from hdsh.pairing import links as pairing_links
from hdsh.pairing.links import (
    DocumentLink,
    LinkContext,
    language_switcher_targets,
    split_markdown_url_target,
)

_ROOT = "https://github.com/example/repo/blob/main/"


def _context(
    source_path: str,
    exists: set[str],
    corpus: set[str] | None = None,
    markdown: str = "",
) -> LinkContext:
    known_corpus = corpus if corpus is not None else {"docs/guide.md"}
    return LinkContext(
        repo_root="/repo",
        source_path=source_path,
        is_pair_source=lambda path: path in known_corpus,
        repository_file_exists=lambda path: path in exists,
        markdown=markdown,
    )


class TestSwitcher:
    def test_detects_zh_switcher_after_h1(self) -> None:
        markdown = "# 标题\n\n[English](guide.md) | 中文\n\n正文\n"
        line = pairing_links.language_switcher_line(markdown, ["guide.md"])
        assert line == 2

    def test_detects_en_switcher(self) -> None:
        markdown = "# Title\n\nEnglish | [中文](guide.zh.md)\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.zh.md"]) == 2

    def test_rejects_wrong_target(self) -> None:
        markdown = "# T\n\nEnglish | [中文](other.md)\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.zh.md"]) is None

    def test_scan_stops_at_next_heading(self) -> None:
        markdown = "# T\n\n## Section\n\n[English](guide.md) | 中文\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) is None

    def test_missing_h1(self) -> None:
        assert pairing_links.language_switcher_line("no heading\n", ["x"]) is None

    def test_h2_first_is_not_an_h1_document(self) -> None:
        markdown = "## Sub\n\n[English](guide.md) | 中文\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) is None

    def test_h2_before_h1_does_not_end_the_h1_search(self) -> None:
        markdown = "## Sub\n\n# T\n\n[English](guide.md) | 中文\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) == 4

    def test_setext_h1_anchors_the_scan(self) -> None:
        markdown = "Title\n=====\n\n[English](guide.md) | 中文\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) == 3

    def test_switcher_line_inside_multiline_paragraph_is_rejected(self) -> None:
        markdown = "# T\n\nfoo\n[English](guide.md) | 中文\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) is None

    def test_bare_empty_h1_anchors_the_scan(self) -> None:
        markdown = "#\n\n[English](guide.md) | 中文\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) == 2

    def test_reference_based_switcher_does_not_count(self) -> None:
        markdown = "# T\n\n[English][back] | 中文\n\n[back]: guide.md\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) is None

    def test_has_language_switcher(self) -> None:
        assert pairing_links.has_language_switcher(
            "# T\n\nEnglish | [中文](g.zh.md)\n", ["g.zh.md"]
        )
        assert not pairing_links.has_language_switcher("# T\nbody\n", ["g.zh.md"])

    def test_accepts_the_configured_public_blob_url(self) -> None:
        markdown = f"# README\n\nEnglish | [中文]({_ROOT}python/sdk/README.zh.md)\n"
        targets = language_switcher_targets("python/sdk/README.zh.md", _ROOT)
        assert pairing_links.language_switcher_line(markdown, targets) == 2

    def test_rejects_a_public_blob_url_of_the_wrong_counterpart(self) -> None:
        markdown = f"# README\n\nEnglish | [中文]({_ROOT}other/README.zh.md)\n"
        targets = language_switcher_targets("python/sdk/README.zh.md", _ROOT)
        assert pairing_links.language_switcher_line(markdown, targets) is None


class TestSwitcherTargets:
    def test_uses_basename_without_a_configured_root(self) -> None:
        assert language_switcher_targets("docs/deep/guide.md", "") == ["guide.md"]

    def test_appends_the_public_blob_url_with_a_configured_root(self) -> None:
        assert language_switcher_targets("docs/guide.zh.md", _ROOT) == [
            "guide.zh.md",
            f"{_ROOT}docs/guide.zh.md",
        ]

    def test_requires_source_language_switcher_defaults_to_true(self) -> None:
        assert pairing_links.requires_source_language_switcher("docs/guide.md", ())

    def test_requires_source_language_switcher_exempts_generated(self) -> None:
        assert not pairing_links.requires_source_language_switcher(
            "docs/guide.md", ("docs/guide.md",)
        )
        assert pairing_links.requires_source_language_switcher("docs/other.md", ("docs/guide.md",))


class TestUrlSplitting:
    def test_splits_fragment(self) -> None:
        assert split_markdown_url_target("a.md#section") == ("a.md", "#section")

    def test_splits_query(self) -> None:
        assert split_markdown_url_target("a.md?page=1#s") == ("a.md", "?page=1#s")

    def test_plain_url(self) -> None:
        assert split_markdown_url_target("a.md") == ("a.md", "")


class TestLocaleViolations:
    def test_zh_side_must_link_zh_sibling(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md", "docs/other.md", "docs/other.zh.md"}
        markdown = "# 指南\n\n正文。\n\n[概览](other.md?view=full#overview)\n"
        violations = pairing_links.link_locale_violations(
            markdown,
            _context("docs/guide.zh.md", exists, corpus={"docs/other.md"}, markdown=markdown),
        )
        assert violations == [
            pairing_links.LinkLocaleViolation(
                source_path="docs/guide.zh.md",
                line=5,
                url="other.md?view=full#overview",
                expected_url="other.zh.md?view=full#overview",
            )
        ]

    def test_en_side_must_link_en_sibling(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md"}
        markdown = "See [the guide](guide.zh.md).\n"
        violations = pairing_links.link_locale_violations(
            markdown, _context("docs/guide.md", exists, markdown=markdown)
        )
        assert violations[0].expected_url == "guide.md"

    def test_correct_locale_is_clean(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md"}
        for source, target in (
            ("docs/guide.md", "guide.md"),
            ("docs/guide.zh.md", "guide.zh.md"),
        ):
            markdown = f"See [the guide]({target}).\n"
            assert pairing_links.link_locale_violations(markdown, _context(source, exists)) == []

    def test_switcher_line_is_exempt(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md"}
        markdown = "# 标题\n\n[English](guide.md) | 中文\n"
        assert (
            pairing_links.link_locale_violations(
                markdown, _context("docs/guide.zh.md", exists), ["guide.md"]
            )
            == []
        )

    def test_body_link_to_counterpart_is_not_exempt(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md"}
        markdown = "# 标题\n\n[English](guide.md) | 中文\n\n[正文](guide.md)\n"
        violations = pairing_links.link_locale_violations(
            markdown, _context("docs/guide.zh.md", exists, markdown=markdown), ["guide.md"]
        )
        assert violations == [
            pairing_links.LinkLocaleViolation(
                source_path="docs/guide.zh.md",
                line=5,
                url="guide.md",
                expected_url="guide.zh.md",
            )
        ]

    def test_out_of_corpus_target_is_ignored(self) -> None:
        exists = {"docs/guide.zh.md", "docs/plain.md"}
        markdown = "See [plain](plain.md).\n"
        assert (
            pairing_links.link_locale_violations(
                markdown, _context("docs/guide.zh.md", exists, corpus=set())
            )
            == []
        )

    def test_missing_target_is_ignored(self) -> None:
        markdown = "See [missing](gone.md).\n"
        assert (
            pairing_links.link_locale_violations(markdown, _context("docs/guide.zh.md", set()))
            == []
        )

    def test_active_target_without_locale_sibling_does_not_fall_back(self) -> None:
        exists = {"docs/guide.zh.md", "docs/unpaired.md"}
        markdown = "See [missing](unpaired.md).\n"
        violations = pairing_links.link_locale_violations(
            markdown,
            _context("docs/guide.zh.md", exists, corpus={"docs/unpaired.md"}, markdown=markdown),
        )
        assert [(v.url, v.expected_url) for v in violations] == [("unpaired.md", "unpaired.zh.md")]

    def test_directory_target_does_not_infer_an_index_page(self) -> None:
        exists = {"docs/guide.zh.md", "docs/section/index.md", "docs/section/index.zh.md"}
        markdown = "See [section](section/).\n"
        assert (
            pairing_links.link_locale_violations(
                markdown, _context("docs/guide.zh.md", exists, markdown=markdown)
            )
            == []
        )

    def test_fragment_suffix_is_preserved(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md"}
        markdown = "See [x](guide.md#section).\n"
        violations = pairing_links.link_locale_violations(
            markdown, _context("docs/guide.zh.md", exists, markdown=markdown), ["guide.md"]
        )
        assert violations[0].expected_url == "guide.zh.md#section"

    def test_encoded_filename_reports_authored_bytes(self) -> None:
        exists = {"docs/guide.zh.md", "docs/reference.md", "docs/reference.zh.md"}
        markdown = "[概览](reference%2Emd?view=full&amp;mode=all#overview)\n"
        violations = pairing_links.link_locale_violations(
            markdown,
            _context("docs/guide.zh.md", exists, corpus={"docs/reference.md"}, markdown=markdown),
        )
        assert violations == [
            pairing_links.LinkLocaleViolation(
                source_path="docs/guide.zh.md",
                line=1,
                url="reference%2Emd?view=full&amp;mode=all#overview",
                expected_url="reference.zh.md?view=full&amp;mode=all#overview",
            )
        ]

    def test_expected_paths_encode_only_rfc3986_unreserved_characters(self) -> None:
        # The expected-path encoding must agree with quote(safe=""): )#? are
        # percent-encoded, the unreserved ``.`` stays literal.
        exists = {"docs/guide.zh.md", "docs/a)#?b.md", "docs/a)#?b.zh.md"}
        markdown = "[保留](a%29%23%3Fb%2Emd?view=full#section)\n"
        violations = pairing_links.link_locale_violations(
            markdown,
            _context("docs/guide.zh.md", exists, corpus={"docs/a)#?b.md"}, markdown=markdown),
        )
        assert [(violation.url, violation.expected_url) for violation in violations] == [
            ("a%29%23%3Fb%2Emd?view=full#section", "a%29%23%3Fb.zh.md?view=full#section")
        ]

    def test_fenced_code_links_are_ignored(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md"}
        markdown = "```\n[link](guide.md)\n```\n"
        assert (
            pairing_links.link_locale_violations(markdown, _context("docs/guide.zh.md", exists))
            == []
        )

    def test_reference_links_report_their_definition_once(self) -> None:
        exists = {"docs/guide.zh.md", "docs/reference.md", "docs/reference.zh.md"}
        markdown = "See [a][ref] and [b][ref].\n\n[ref]: reference.md\n"
        violations = pairing_links.link_locale_violations(
            markdown,
            _context("docs/guide.zh.md", exists, corpus={"docs/reference.md"}, markdown=markdown),
        )
        assert [(v.line, v.url, v.expected_url) for v in violations] == [
            (3, "reference.md", "reference.zh.md")
        ]

    def test_first_duplicate_definition_wins(self) -> None:
        exists = {"docs/guide.zh.md", "docs/reference.md", "docs/reference.zh.md"}
        markdown = "[x][ref]\n\n[ref]: reference.zh.md\n[ref]: reference.md\n"
        assert (
            pairing_links.link_locale_violations(
                markdown, _context("docs/guide.zh.md", exists, markdown=markdown)
            )
            == []
        )

    def test_image_only_definition_is_not_a_document_link(self) -> None:
        exists = {"docs/guide.zh.md", "docs/reference.zh.md"}
        markdown = "![preview][asset]\n\n[asset]: reference.zh.md#overview\n"
        assert (
            pairing_links.link_locale_violations(
                markdown, _context("docs/guide.zh.md", exists, markdown=markdown)
            )
            == []
        )

    def test_gfm_autolinks_stay_unchanged(self) -> None:
        exists = {"docs/guide.zh.md"}
        for markdown in (
            "<https://example.com/reference.md\n",
            "https://example.com/reference.md\n",
        ):
            assert (
                pairing_links.link_locale_violations(
                    markdown, _context("docs/guide.zh.md", exists, markdown=markdown)
                )
                == []
            )


class TestSemanticTargets:
    def test_corpus_link_normalizes_to_en_anchor(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md"}
        target = pairing_links.semantic_link_target(
            "guide.zh.md#frag", "guide.zh.md#frag", _context("docs/other.md", exists)
        )
        assert target == "hdsh-pairing-target:docs/guide.md#frag"

    def test_external_url_returns_authored_bytes(self) -> None:
        assert (
            pairing_links.semantic_link_target(
                "https://example.com/?x=1&y=2",
                "https://example.com/?x=1&amp;y=2",
                _context("docs/a.md", set()),
            )
            == "https://example.com/?x=1&amp;y=2"
        )

    def test_absolute_path_returns_authored_bytes(self) -> None:
        assert (
            pairing_links.semantic_link_target("/abs.md", "/abs.md", _context("docs/a.md", set()))
            == "/abs.md"
        )

    def test_unresolvable_link_returns_authored_bytes(self) -> None:
        assert (
            pairing_links.semantic_link_target("gone.md", "gone.md", _context("docs/a.md", set()))
            == "gone.md"
        )

    def test_fragment_only_link_passes_through(self) -> None:
        assert (
            pairing_links.semantic_link_target("#anchor", "#anchor", _context("docs/a.md", set()))
            == "#anchor"
        )

    def test_authored_query_bytes_survive_semantic_resolution(self) -> None:
        exists = {"docs/guide.md", "docs/guide.zh.md"}
        escaped = pairing_links.semantic_link_target(
            "guide.md?x=1&y=2#s",
            "guide.md?x=1&amp;y=2#s",
            _context("docs/other.md", exists),
        )
        literal = pairing_links.semantic_link_target(
            "guide.md?x=1&y=2#s", "guide.md?x=1&y=2#s", _context("docs/other.md", exists)
        )
        assert escaped != literal
        assert escaped == "hdsh-pairing-target:docs/guide.md?x=1&amp;y=2#s"


def _plain_context() -> LinkContext:
    return LinkContext(
        repo_root=".",
        source_path="docs/x.md",
        is_pair_source=lambda p: False,
        repository_file_exists=lambda p: False,
        markdown="",
    )


def _zh_context(exists: set[str], markdown: str = "") -> LinkContext:
    return LinkContext(
        repo_root=".",
        source_path="docs/guide.zh.md",
        is_pair_source=lambda path: path == "docs/guide.md",
        repository_file_exists=lambda path: path in exists,
        markdown=markdown,
    )


class TestDocumentLinks:
    def test_collects_inline_links_with_lines(self) -> None:
        markdown = "text with **bold** and [x](y.md)\n\nmore [z](w.md)\n"
        links = pairing_links.document_links(markdown)
        assert [(link.line, link.href) for link in links] == [(0, "y.md"), (2, "w.md")]

    def test_resolves_reference_links_to_their_definition(self) -> None:
        markdown = "See [x][ref].\n\n[ref]: guide.md\n"
        links = pairing_links.document_links(markdown)
        assert links == [
            DocumentLink(
                line=0, href="guide.md", authored="guide.md", label="REF", definition_line=2
            )
        ]

    def test_unresolved_references_contribute_nothing(self) -> None:
        markdown = "See [x][missing].\n"
        assert pairing_links.document_links(markdown) == []

    def test_images_contribute_nothing(self) -> None:
        markdown = "![alt](img.png) and ![alt][asset]\n\n[asset]: other.png\n"
        assert pairing_links.document_links(markdown) == []

    def test_code_spans_and_escapes_are_skipped(self) -> None:
        markdown = "`[x](a.md)` and \\[y\\](b.md)\n"
        assert pairing_links.document_links(markdown) == []

    def test_angle_autolinks_and_bare_urls_are_collected(self) -> None:
        markdown = "go <https://ex.com/a> and https://ex.com/b. and www.ex.com/c)\n"
        links = pairing_links.document_links(markdown)
        assert [(link.href, link.authored) for link in links] == [
            ("https://ex.com/a", "https://ex.com/a"),
            ("https://ex.com/b", "https://ex.com/b"),
            ("http://www.ex.com/c", "www.ex.com/c"),
        ]

    def test_bare_url_inside_a_word_is_skipped(self) -> None:
        markdown = "visit foohttps://ex.com/a now\n"
        assert pairing_links.document_links(markdown) == []

    def test_escaped_bracket_is_text(self) -> None:
        markdown = "\\[not a link](a.md)\n"
        assert pairing_links.document_links(markdown) == []


class TestScannerEdges:
    def test_decode_invalid_percent_kept_verbatim(self) -> None:
        assert pairing_links._decode_path("%zz.md") == "%zz.md"

    def test_decode_path_surrogateescape_failure(self) -> None:
        # A lone surrogate escapes strict decoding and falls back verbatim.
        assert pairing_links._decode_path("%ed%a0%80.md") == "%ed%a0%80.md"

    def test_relative_expected_path_encodes_specials(self) -> None:
        context = LinkContext(
            repo_root=".",
            source_path="docs/a b/x.md",
            is_pair_source=lambda p: True,
            repository_file_exists=lambda p: True,
            markdown="",
        )
        encoded = pairing_links._relative_expected_path(context, "docs/c d.md", "raw.md")
        assert encoded == "../c%20d.md"

    def test_protocol_relative_url_is_external(self) -> None:
        assert pairing_links.is_external_or_absolute_markdown_url("//x.example/a")

    def test_schemed_url_is_external(self) -> None:
        assert pairing_links.is_external_or_absolute_markdown_url("mailto:a@b.c")

    def test_link_in_heading_counts(self) -> None:
        markdown = "## See [guide](guide.md)\n"
        violations = pairing_links.link_locale_violations(
            markdown, _zh_context({"docs/guide.md", "docs/guide.zh.md"}, markdown)
        )
        assert violations

    def test_repository_relative_path_rejections(self) -> None:
        for rejected in ("", ".", "..", "../x", "/abs"):
            assert pairing_links._repository_relative_path(rejected) is None

    def test_repository_relative_path_accepts_nested(self) -> None:
        assert pairing_links._repository_relative_path("docs/sub/ok.md") == "docs/sub/ok.md"

    def test_translation_pair_target_rejects_non_markdown(self) -> None:
        context = LinkContext(
            repo_root=".",
            source_path="docs/guide.zh.md",
            is_pair_source=lambda p: True,
            repository_file_exists=lambda p: True,
            markdown="",
        )
        assert pairing_links._pair_target("docs/image.png", context) is None

    def test_switcher_without_link_target(self) -> None:
        markdown = "# T\n\n[English]() | 中文\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) is None

    def test_switcher_line_before_any_heading(self) -> None:
        markdown = "[English](guide.md) | 中文\n\n# T\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) is None

    def test_switcher_paragraph_with_two_links_is_rejected(self) -> None:
        markdown = "# T\n\n[English](guide.md) | [中文](guide.zh.md)\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.md"]) is None

    def test_resolve_translation_link_external_returns_none(self) -> None:
        assert pairing_links._resolve_link("https://x.example", _plain_context(), "auth") is None

    def test_link_target_escaping_repository_is_ignored(self) -> None:
        markdown = "Up to [root](../..).\n"
        assert (
            pairing_links.link_locale_violations(markdown, _zh_context(set()), ["guide.md"]) == []
        )

    def test_external_only_document_is_clean(self) -> None:
        markdown = "# 标题\n\n[English](guide.md) | 中文\n\nSee [site](https://example.com).\n"
        assert (
            pairing_links.link_locale_violations(
                markdown, _zh_context({"docs/guide.md"}, markdown), ["guide.md"]
            )
            == []
        )

    def test_switcher_shaped_line_with_wrong_target_only(self) -> None:
        markdown = "# T\n\nEnglish | [中文](other.md)\n"
        assert pairing_links.language_switcher_line(markdown, ["guide.zh.md"]) is None

    def test_nested_bracket_label_finds_inner_link(self) -> None:
        markdown = "[outer [inner](a.md)](b.md)\n"
        links = pairing_links.document_links(markdown)
        # The outer link contains a link, so CommonMark leaves the inner one.
        assert [link.href for link in links] == ["a.md"]

    def test_titled_inline_link_destination_is_scanned(self) -> None:
        markdown = '[x](guide.md "title")\n'
        links = pairing_links.document_links(markdown)
        assert [(link.href, link.authored) for link in links] == [("guide.md", "guide.md")]

    def test_angle_bracket_destination_is_scanned(self) -> None:
        markdown = "[x](<a b.md>)\n"
        links = pairing_links.document_links(markdown)
        assert links[0].authored == "a b.md"

    def test_escaped_parenthesis_destination(self) -> None:
        markdown = r"[x](a\(b.md)"
        links = pairing_links.document_links(markdown)
        assert (links[0].authored, links[0].href) == ("a\\(b.md", "a(b.md")

    def test_unclosed_inline_link_falls_back_to_text(self) -> None:
        markdown = "[broken](a.md\n"
        assert pairing_links.document_links(markdown) == []

    def test_entity_in_destination_is_decoded_for_resolution(self) -> None:
        markdown = "[x](a&amp;b.md)\n"
        links = pairing_links.document_links(markdown)
        assert (links[0].href, links[0].authored) == ("a&b.md", "a&amp;b.md")

    def test_raw_html_span_is_skipped(self) -> None:
        markdown = '<a href="[not](a.md)">text</a> and [real](b.md)\n'
        links = pairing_links.document_links(markdown)
        assert [link.href for link in links] == ["b.md"]

    def test_collapsed_and_shortcut_references_resolve(self) -> None:
        markdown = "[one][ref] and [ref][] and [ref]\n\n[ref]: guide.md\n"
        links = pairing_links.document_links(markdown)
        assert [link.label for link in links] == ["REF", "REF", "REF"]

    def test_shortcut_reference_requires_a_definition(self) -> None:
        markdown = "[undefined] stays text\n"
        assert pairing_links.document_links(markdown) == []

    def test_oversized_label_is_text(self) -> None:
        markdown = f"[{'x' * 1000}](a.md)\n"
        assert pairing_links.document_links(markdown) == []


class TestScannerGrammarBranches:
    def test_escaped_bracket_inside_label(self) -> None:
        assert pairing_links.document_links("[a\\]b](x.md)\n")[0].href == "x.md"

    def test_unterminated_label_is_text(self) -> None:
        assert pairing_links.document_links("[abc\n") == []

    def test_unterminated_code_span_consumes_the_rest(self) -> None:
        assert pairing_links.document_links("`unclosed [x](a.md)\n") == []

    def test_backtick_run_mismatch_keeps_scanning(self) -> None:
        links = pairing_links.document_links("``a`b`` and [x](a.md)\n")
        assert [link.href for link in links] == ["a.md"]

    def test_empty_inline_link_parentheses(self) -> None:
        # CommonMark parses `[x]()` as a link with an empty destination; it
        # resolves to nothing and the signature carries the empty target.
        assert pairing_links.document_links("[x]()\n")[0].href == ""

    def test_broken_destination_falls_back_to_text(self) -> None:
        assert pairing_links.document_links("[x](<<)\n") == []

    def test_escaped_paren_stops_the_bare_destination(self) -> None:
        # The escaped paren belongs to the destination; the unbalanced `)`
        # then closes the link, so the rest is text.
        markdown = r"[x](a\(b).md)"
        assert (pairing_links.document_links(markdown)[0].authored) == "a\\(b"

    def test_escaped_angle_in_angle_destination(self) -> None:
        markdown = "[x](<a\\>b.md>)\n"
        assert pairing_links.document_links(markdown)[0].authored == "a\\>b.md"

    def test_open_paren_at_chunk_end_is_text(self) -> None:
        assert pairing_links.document_links("[x](") == []

    def test_angle_destination_rejects_inner_angle(self) -> None:
        assert pairing_links.document_links("[x](<a<b.md>)\n") == []

    def test_unterminated_angle_destination(self) -> None:
        assert pairing_links.document_links("[x](<a.md\n") == []

    def test_balanced_parentheses_stay_in_the_destination(self) -> None:
        assert pairing_links.document_links("[x](a(b).md)\n")[0].href == "a(b).md"

    def test_parenthesized_title_closes_the_link(self) -> None:
        assert pairing_links.document_links("[x](a.md (t))\n")[0].href == "a.md"

    def test_single_quoted_title_closes_the_link(self) -> None:
        assert pairing_links.document_links("[x](a.md 't')\n")[0].href == "a.md"

    def test_escaped_quote_inside_title(self) -> None:
        assert pairing_links.document_links("[x](a.md 'a\\'b')\n")[0].href == "a.md"

    def test_title_with_trailing_space_closes_the_link(self) -> None:
        assert pairing_links.document_links("[x](a.md 't' )\n")[0].href == "a.md"

    def test_title_without_closing_paren_is_text(self) -> None:
        assert pairing_links.document_links("[x](a.md 't' x)\n") == []

    def test_unterminated_title_is_text(self) -> None:
        assert pairing_links.document_links("[x](a.md 't\n") == []

    def test_whitespace_after_opening_paren(self) -> None:
        assert pairing_links.document_links("[x](  a.md  )\n")[0].href == "a.md"

    def test_failed_inline_link_rescans_the_interior(self) -> None:
        markdown = "[broken](  \n [inner](a.md)\n"
        assert [link.href for link in pairing_links.document_links(markdown)] == ["a.md"]

    def test_unterminated_second_reference_label(self) -> None:
        assert pairing_links.document_links("[a][b\n") == []

    def test_html_comment_inside_an_inline_chunk(self) -> None:
        markdown = "text <!-- [x](a.md) --> tail [y](b.md)\n"
        assert [link.href for link in pairing_links.document_links(markdown)] == ["b.md"]

    def test_cdata_inside_an_inline_chunk(self) -> None:
        markdown = "text <![CDATA[ [x](a.md) ]]> tail [y](b.md)\n"
        assert [link.href for link in pairing_links.document_links(markdown)] == ["b.md"]

    def test_lone_angle_bracket_is_text(self) -> None:
        markdown = "a < b and [x](y.md)\n"
        assert [link.href for link in pairing_links.document_links(markdown)] == ["y.md"]

    def test_unterminated_html_comment_is_text(self) -> None:
        markdown = "text <!-- nope\n\n[x](y.md)\n"
        assert [link.href for link in pairing_links.document_links(markdown)] == ["y.md"]

    def test_unterminated_cdata_is_literal_text(self) -> None:
        markdown = "text <![CDATA[ nope [x](a.md)\n"
        # Malformed CDATA stays text, so the inner link still parses.
        assert [link.href for link in pairing_links.document_links(markdown)] == ["a.md"]

    def test_bare_url_with_balanced_parentheses(self) -> None:
        markdown = "see https://ex.com/a(b) now\n"
        assert pairing_links.document_links(markdown)[0].authored == "https://ex.com/a(b)"


class TestLiteralAutolinks:
    """GFM literal-autolink acceptance semantics.

    A literal autolink is accepted when either the micromark state machine
    (parser-time, its predecessor rules) or the mdast-util transform patterns
    (post-parse, whitespace/punctuation predecessors) accept it; the scanner
    unions both, so cases below name which side owns the acceptance.
    """

    @pytest.mark.parametrize(
        ("markdown", "expected"),
        [
            # Machine-accepted http(s) forms.
            ("see https://x.com/a now", [("https://x.com/a", "https://x.com/a")]),
            ("1https://x.com/a", [("https://x.com/a", "https://x.com/a")]),
            ("中文https://x.com/a", [("https://x.com/a", "https://x.com/a")]),
            ("https://x.com", [("https://x.com", "https://x.com")]),
            ("https://a-b.co/x", [("https://a-b.co/x", "https://a-b.co/x")]),
            ("https://x.com/a;", [("https://x.com/a", "https://x.com/a")]),
            ("https://x.com/a&amp;.", [("https://x.com/a", "https://x.com/a")]),
            ("https://x.com/a&", [("https://x.com/a&", "https://x.com/a&")]),
            ("https://x.com/a] text", [("https://x.com/a", "https://x.com/a")]),
            ("https://x.com/a](x", [("https://x.com/a", "https://x.com/a")]),
            ("https://x.com/a]b", [("https://x.com/a]b", "https://x.com/a]b")]),
            ("https://x.com/a]*b", [("https://x.com/a]*b", "https://x.com/a]*b")]),
            ("https://x.com/a<x", [("https://x.com/a", "https://x.com/a")]),
            ("https://x.com/a..,,.", [("https://x.com/a", "https://x.com/a")]),
            ('https://x.com/a"*q', [('https://x.com/a"*q', 'https://x.com/a"*q')]),
            ("xhttps://x.com/a", []),
            ("https://!", []),
            ("https://-", []),
            ("https://", []),
            ("https://...", []),
            ("https:x", []),
            ("httpsx://x.com", []),
            ("httpl://x.com/a", []),
            # Machine-accepted www forms.
            ("(www.x.com/a", [("http://www.x.com/a", "www.x.com/a")]),
            ("_www.x.com/a", [("http://www.x.com/a", "www.x.com/a")]),
            ("*www.x.com/a", [("http://www.x.com/a", "www.x.com/a")]),
            ("~www.x.com/a", [("http://www.x.com/a", "www.x.com/a")]),
            ("www.ex.com", [("http://www.ex.com", "www.ex.com")]),
            ("www.x.com. text", [("http://www.x.com", "www.x.com")]),
            ("www.x.com_. text", [("http://www.x.com", "www.x.com")]),
            # Transform-accepted www forms.
            (")www.x.com/a", [("http://www.x.com/a", "www.x.com/a")]),
            (")www.x.com/a(b)", [("http://www.x.com/a(b)", "www.x.com/a(b)")]),
            ("/www.x.com/a", [("http://www.x.com/a", "www.x.com/a")]),
            ("@www.x.com/a", [("http://www.x.com/a", "www.x.com/a")]),
            ("=www.x.com/a", [("http://www.x.com/a", "www.x.com/a")]),
            ("www.", [("http://www", "www")]),
            # Rejected by both: digits before www, underscores near the end.
            ("1www.x.com/a", []),
            ("wwx.com", []),
            ("https://x_.com/a", []),
            ("www.exa_mple.com/a", []),
            ("www.example._com/a", []),
            # Machine-accepted emails.
            ("mail foo@bar.com now", [("mailto:foo@bar.com", "foo@bar.com")]),
            ("xfoo@bar.com", [("mailto:xfoo@bar.com", "xfoo@bar.com")]),
            (
                "foo+tag@ex-ample_1.com",
                [("mailto:foo+tag@ex-ample_1.com", "foo+tag@ex-ample_1.com")],
            ),
            ("a.b+c@d-e.f", [("mailto:a.b+c@d-e.f", "a.b+c@d-e.f")]),
            ("foo@bar.", []),
            ("foo@bar.com,", [("mailto:foo@bar.com", "foo@bar.com")]),
            ("foo@bar.c0m", [("mailto:foo@bar.c0m", "foo@bar.c0m")]),
            ("foo@_bar.com", [("mailto:foo@_bar.com", "foo@_bar.com")]),
            ("..@x.com", [("mailto:..@x.com", "..@x.com")]),
            ("www@x.com", [("mailto:www@x.com", "www@x.com")]),
            ("mailto:foo@bar.com", [("mailto:foo@bar.com", "foo@bar.com")]),
            # Transform-accepted email.
            ("foo@bar._com", [("mailto:foo@bar._com", "foo@bar._com")]),
            # Rejected emails: no domain dot, digit or symbol ending, slash.
            ("foo@bar", []),
            ("foo@bar.com1", []),
            ("foo@bar.com_", []),
            ("foo@bar.com-", []),
            ("/foo@bar.com", []),
            ("a/foo@bar.com", []),
            # Pass precedence and failed-label rescan.
            ("https://x.com/@user", [("https://x.com/@user", "https://x.com/@user")]),
            ("[see foo@bar.com] tail", [("mailto:foo@bar.com", "foo@bar.com")]),
        ],
    )
    def test_matches_the_benchmark(self, markdown: str, expected: list[tuple[str, str]]) -> None:
        links = pairing_links.document_links(markdown + "\n")
        assert [(link.href, link.authored) for link in links] == expected


class TestRawHtmlGrammar:
    """CommonMark raw HTML inside an inline chunk leaves interior text scannable."""

    @pytest.mark.parametrize(
        ("markdown", "expected"),
        [
            ("text <!DOCTYPE html> more [x](a.md)", ["a.md"]),
            ("text <!x> [y](b.md)", ["b.md"]),
            ("text <?php echo 1 ?> [x](a.md)", ["a.md"]),
            ("text <?php foo@bar.com", ["mailto:foo@bar.com"]),
            ("text <input disabled> [z](c.md)", ["c.md"]),
            ("text <a href=foo>x</a> [b](c.md)", ["c.md"]),
            ("text <a b='x y'>t</a> [c](d.md)", ["d.md"]),
            ('text <a href="x>y"> [z](w.md)', ["w.md"]),
            ('text <a b="x> [y](b.md)', ["b.md"]),
            ('text <a b="c>d" e', []),
            ("text <a href=> [x](a.md)", ["a.md"]),
            ("text <a=1> [x](a.md)", ["a.md"]),
            ('text <a b:"c"> [x](a.md)', ["a.md"]),
            ("text <br/> [x](a.md)", ["a.md"]),
            ("text <br //> [x](a.md)", ["a.md"]),
            ("text </a> [x](b.md)", ["b.md"]),
            ("text </a b> [x](b.md)", ["b.md"]),
            ("text <!--> [x](a.md)", ["a.md"]),
            ("text <!---> [y](b.md)", ["b.md"]),
        ],
    )
    def test_html_forms_match_the_benchmark(self, markdown: str, expected: list[str]) -> None:
        assert [link.href for link in pairing_links.document_links(markdown + "\n")] == expected


class TestParsedDestinationDecoding:
    def test_semicolonless_reference_stays_verbatim(self) -> None:
        links = pairing_links.document_links("[x](a&ampb.md)\n")
        assert (links[0].href, links[0].authored) == ("a&ampb.md", "a&ampb.md")

    @pytest.mark.parametrize(
        ("markdown", "href"),
        [
            ("[x](a&amp;b.md)", "a&b.md"),
            ("[x](&#65;b.md)", "Ab.md"),
            ("[x](&#x41;b.md)", "Ab.md"),
            ("[x](&notanentity;.md)", "&notanentity;.md"),
        ],
    )
    def test_references_decode_only_with_a_semicolon(self, markdown: str, href: str) -> None:
        assert pairing_links.document_links(markdown + "\n")[0].href == href

    def test_scanner_parsed_matches_the_parser_href(self) -> None:
        # Pinned invariant: the scanner's parsed destination and
        # markdown-it's own link href are byte-identical for one document.
        markdown = (
            "[a](x&amp;y.md) [b](x&y.md) [c](&#65;.md) [d](a\\(b.md) [e](<a b.md>) [f](a%2Eb.md)\n"
        )
        parser_hrefs = [
            str(child.attrGet("href"))
            for token in pairing_links._PARSER.parse(markdown)
            for child in token.children or []
            if child.type == "link_open"
        ]
        assert [link.href for link in pairing_links.document_links(markdown)] == parser_hrefs

    def test_angle_autolink_body_rejects_whitespace_and_controls(self) -> None:
        # A tab breaks the autolink, so the bare-URL pass links up to the tab;
        # a control character is not whitespace and stays inside the URL.
        tab = pairing_links.document_links("<https://a\tb>\n")
        assert [(link.href, link.authored) for link in tab] == [("https://a", "https://a")]
        control = pairing_links.document_links("<https://a\x01b>\n")
        assert [(link.href, link.authored) for link in control] == [
            ("https://a\x01b>", "https://a\x01b>")
        ]


class TestDefinitionScanBranches:
    def test_over_indented_definition_line_is_rejected(self) -> None:
        assert pairing_links._locate_definition_destination("    [x]: a.md") is None

    def test_line_without_a_label_is_rejected(self) -> None:
        assert pairing_links._locate_definition_destination("plain text") is None

    def test_unterminated_definition_label_is_rejected(self) -> None:
        assert pairing_links._locate_definition_destination("[x: a.md") is None

    def test_definition_without_a_colon_is_rejected(self) -> None:
        assert pairing_links._locate_definition_destination("[x] a.md") is None

    def test_unlocatable_definition_falls_back_to_the_parsed_href(self) -> None:
        references = {"X": {"href": "x.md", "map": [0, 1]}}
        scans = pairing_links._scan_definitions("not a definition\n", references)
        assert scans["X"].span is None
        assert scans["X"].authored == "x.md"


class TestNormalizeSplicingEdges:
    def _pair_context(self, markdown: str, source: str) -> LinkContext:
        return LinkContext(
            repo_root=".",
            source_path=source,
            is_pair_source=lambda path: path == "docs/other.md",
            repository_file_exists=lambda path: path in {"docs/other.md", "docs/other.zh.md"},
            markdown=markdown,
        )

    def test_unlocatable_chunk_is_skipped(self) -> None:
        markdown = "> first [x](other.md)\n> continued\n"
        assert (
            pairing_links.normalize_translation_markdown_links(
                markdown, self._pair_context(markdown, "docs/guide.md")
            )
            == markdown
        )

    def test_table_cell_replacement_relocates_by_cursor(self) -> None:
        markdown = "| [ab](other.md) | [b](plain.md) |\n|---|---|\n| x | y |\n"
        normalized = pairing_links.normalize_translation_markdown_links(
            markdown, self._pair_context(markdown, "docs/guide.md")
        )
        assert normalized == (
            "| [ab](hdsh-pairing-target:docs/other.md) | [b](plain.md) |\n|---|---|\n| x | y |\n"
        )

    def test_referenced_non_corpus_definition_is_untouched(self) -> None:
        markdown = "See [x][p].\n\n[p]: plain.md\n"
        assert (
            pairing_links.normalize_translation_markdown_links(
                markdown, self._pair_context(markdown, "docs/guide.md")
            )
            == markdown
        )

    def test_unlocatable_definition_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        markdown = "See [x][o].\n\n[o]: other.md\n"
        monkeypatch.setattr(
            pairing_links,
            "_scan_definitions",
            lambda markdown, references: {
                "O": pairing_links._DefinitionScan(
                    authored="other.md", href="other.md", line=2, span=None
                )
            },
        )
        assert (
            pairing_links.normalize_translation_markdown_links(
                markdown, self._pair_context(markdown, "docs/guide.md")
            )
            == markdown
        )


class TestNormalize:
    def _pair_context(self, markdown: str, source: str) -> LinkContext:
        return LinkContext(
            repo_root=".",
            source_path=source,
            is_pair_source=lambda path: path == "docs/other.md",
            repository_file_exists=lambda path: path in {"docs/other.md", "docs/other.zh.md"},
            markdown=markdown,
        )

    def test_locale_sibling_paths_normalize_to_one_target(self) -> None:
        english = "# T\n\nSee [x](other.md) [z](https://ext.example/a).\n"
        chinese = "# T\n\nSee [x](other.zh.md) [z](https://ext.example/a).\n"
        assert pairing_links.normalize_translation_markdown_links(
            english, self._pair_context(english, "docs/guide.md")
        ) == pairing_links.normalize_translation_markdown_links(
            chinese, self._pair_context(chinese, "docs/guide.zh.md")
        )

    def test_authored_query_bytes_prevent_false_equality(self) -> None:
        english = "[x](other.md?x=1&amp;y=2#s)\n"
        chinese = "[x](other.zh.md?x=1&y=2#s)\n"
        assert pairing_links.normalize_translation_markdown_links(
            english, self._pair_context(english, "docs/guide.md")
        ) != pairing_links.normalize_translation_markdown_links(
            chinese, self._pair_context(chinese, "docs/guide.zh.md")
        )

    def test_fenced_code_is_untouched(self) -> None:
        markdown = "```\n[x](other.md)\n```\n"
        assert (
            pairing_links.normalize_translation_markdown_links(
                markdown, self._pair_context(markdown, "docs/guide.md")
            )
            == markdown
        )

    def test_non_corpus_links_are_untouched(self) -> None:
        markdown = "[x](plain.md) and [y](https://ext.example/a)\n"
        assert (
            pairing_links.normalize_translation_markdown_links(
                markdown, self._pair_context(markdown, "docs/guide.md")
            )
            == markdown
        )

    def test_referenced_definitions_are_normalized(self) -> None:
        markdown = "See [x][o].\n\n[o]: other.md#frag\n"
        normalized = pairing_links.normalize_translation_markdown_links(
            markdown, self._pair_context(markdown, "docs/guide.md")
        )
        assert normalized == "See [x][o].\n\n[o]: hdsh-pairing-target:docs/other.md#frag\n"

    def test_switcher_link_is_exempt(self) -> None:
        markdown = "# T\n\n[English](other.md) | 中文\n"
        assert (
            pairing_links.normalize_translation_markdown_links(
                markdown, self._pair_context(markdown, "docs/guide.zh.md"), ["other.md"]
            )
            == markdown
        )

    def test_switcher_shaped_line_normalizes_without_skip_targets(self) -> None:
        # Region normalization is called with no switcher skip targets, so a
        # fragment carrying its own H1 and a switcher-shaped line still has
        # its corpus link normalized.
        markdown = "# T\n\nEnglish | [中文](other.md)\n"
        normalized = pairing_links.normalize_translation_markdown_links(
            markdown, self._pair_context(markdown, "docs/guide.md")
        )
        assert normalized == "# T\n\nEnglish | [中文](hdsh-pairing-target:docs/other.md)\n"
