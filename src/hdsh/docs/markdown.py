"""Shared Markdown parsing and traversal for the documentation gates.

One parser (CommonMark plus the GFM table extension) feeds every gate, so a
paragraph, destination, or anchor means the same thing wherever a gate reads
it. Destinations are collected from the token stream — never from raw regex
over the whole document — so fenced code is never mistaken for a link; every
reference definition, shadowed duplicates included, arrives as a token, and
destinations keep their authored text because the parser's URL normalizer is
the identity.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from typing import override

from markdown_it import MarkdownIt
from markdown_it.token import Token


class _AuthoredTextParser(MarkdownIt):
    """Parser whose link destinations keep their authored text.

    markdown-it percent-encodes destinations through ``normalizeLink`` for
    rendering; the gates read destinations instead of rendering them, so the
    identity keeps diagnostics quoting the authored text (``%zz-file.md``,
    not ``%25zz-file.md``) and probes decoding exactly what the author wrote.
    """

    @override
    def normalizeLink(self, url: str) -> str:
        """Return the destination unchanged."""
        return url


#: Parser with the GFM table extension enabled, matching the gate's needs.
#: ``inline_definitions`` emits one ``definition`` token per reference
#: definition — shadowed duplicates included — with its authored line map.
_PARSER = _AuthoredTextParser("commonmark", {"inline_definitions": True}).enable("table")

_EXTERNAL_URL_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
_ANCHOR_ID_PATTERN = re.compile(r'<a id="([^"]+)"')


def parse_markdown(content: str) -> list[Token]:
    """Parse Markdown with the documentation gates' extensions.

    Args:
        content: Complete document text.

    Returns:
        The flat token stream; block tokens carry ``map`` line ranges and
        inline tokens carry ``children`` with one ``link_open`` per link.
    """
    return _PARSER.parse(content)


@dataclass(frozen=True)
class HardWrapViolation:
    """A prose paragraph spanning more than one source line."""

    #: 1-based line where the hard-wrapped paragraph starts.
    line: int
    #: The paragraph's first source line, trimmed.
    text: str


def mask_non_paragraph_structure(source: str) -> str:
    """Blank structure a paragraph scan must not judge, keeping line count.

    YAML frontmatter (a leading ``---`` block) and VitePress custom-container
    delimiters (lines starting with ``:::``) would otherwise parse as prose
    and hard-wrap their indented or decorated content.
    """
    lines = source.split("\n")
    if lines and lines[0] == "---":
        closing = next((index for index in range(1, len(lines)) if lines[index] == "---"), None)
        if closing is not None:
            lines[: closing + 1] = [""] * (closing + 1)
    return "\n".join("" if line.lstrip().startswith(":::") else line for line in lines)


def hard_wrapped_paragraphs(source: str) -> list[HardWrapViolation]:
    """Find every prose paragraph spanning more than one source line.

    List items and blockquotes hold their own paragraph tokens, so wrapping
    inside them is judged exactly like top-level prose; fenced code, tables,
    and headings are not paragraphs and never violate.

    Args:
        source: Complete document text.

    Returns:
        Violations in document order.
    """
    lines = source.split("\n")
    out: list[HardWrapViolation] = []
    for token in parse_markdown(mask_non_paragraph_structure(source)):
        if token.type != "paragraph_open":
            continue
        start, end = token.map if token.map is not None else (0, 0)
        # markdown-it maps are [start, end) with end exclusive; more than one
        # line means end passes start + 1.
        if end - start > 1:
            first = lines[start] if start < len(lines) else ""
            out.append(HardWrapViolation(line=start + 1, text=first.strip()))
    return out


@dataclass(frozen=True)
class MarkdownDestination:
    """One authored link, image, or reference-definition destination."""

    #: 1-based source line of the link, image, or definition.
    line: int
    #: Destination URL as parsed.
    url: str


def _inline_destinations(token: Token) -> Iterable[MarkdownDestination]:
    line = (token.map[0] if token.map is not None else 0) + 1
    for child in token.children or []:
        # A break ends the authored line, so every destination after it sits
        # one line further down the block.
        if child.type in ("softbreak", "hardbreak"):
            line += 1
        elif child.type == "link_open":
            # markdown-it guarantees an href on link_open and a src on image; the
            # attribute table's broad value type collapses to the URL string here.
            yield MarkdownDestination(line, str(child.attrGet("href") or ""))
        elif child.type == "image":
            yield MarkdownDestination(line, str(child.attrGet("src") or ""))


def document_destinations(source: str) -> list[MarkdownDestination]:
    """Collect every parsed destination in document order.

    Inline links and images report the line they were authored on: within a
    block, soft and hard breaks advance the line counter, so a link in a
    wrapped paragraph does not inherit its block's first line. Reference
    definitions — every definition, shadowed duplicates included — arrive as
    ``definition`` tokens with their own line maps.

    Args:
        source: Complete document text.

    Returns:
        Destinations in document order.
    """
    out: list[MarkdownDestination] = []
    for token in parse_markdown(source):
        if token.type == "inline":
            out.extend(_inline_destinations(token))
        elif token.type == "definition" and token.map is not None:
            out.append(MarkdownDestination(token.map[0] + 1, str(token.meta["url"])))
    return out


def is_external_url(url: str) -> bool:
    """Whether a destination is outside the repository-relative space.

    Scheme-qualified URLs (``https:``, ``mailto:``, …), protocol-relative
    (``//host``), and root-absolute (``/path``) targets are not checked; pure
    in-page anchors (``#frag``) are relative and stay in scope.

    Args:
        url: Destination URL as parsed.

    Returns:
        True when the gate must not resolve the destination.
    """
    return url.startswith(("//", "/")) or _EXTERNAL_URL_PATTERN.match(url) is not None


def _percent_decode(raw: str) -> str:
    """Decode percent escapes the way a Markdown renderer resolves targets.

    A malformed escape (``%zz``) or invalid UTF-8 (``%ff``) keeps the raw
    text, so the link is reported broken — it names no file or anchor anyone
    meant — instead of crashing the gate.
    """
    try:
        return urllib.parse.unquote(raw, errors="strict")
    except UnicodeDecodeError:
        return raw


def path_part(url: str) -> str:
    """The percent-decoded path of a destination, without ``#fragment``/``?query``."""
    return _percent_decode(re.sub(r"[#?].*$", "", url))


def fragment_part(url: str) -> str | None:
    """The percent-decoded ``#fragment`` of a destination, or ``None`` without one."""
    hash_index = url.find("#")
    if hash_index == -1:
        return None
    return _percent_decode(re.sub(r"\?.*$", "", url[hash_index + 1 :]))


def _rendered_inline_text(children: list[Token]) -> str:
    """Text a reader sees from one inline chunk; raw HTML contributes nothing."""
    parts: list[str] = []
    for child in children:
        if child.type in ("text", "code_inline", "image"):
            # An image token's content is its alt text.
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts)


def github_slug(heading: str) -> str:
    """GitHub's heading-slug algorithm over rendered heading text.

    Lowercase; drop everything but letters, numbers, underscores, spaces, and
    hyphens; spaces become hyphens. Underscores survive, and repeated slugs
    are disambiguated by :func:`document_anchors`, not here.

    Args:
        heading: The RENDERED heading text (Markdown syntax already gone).

    Returns:
        The anchor GitHub assigns the first occurrence of the heading.
    """
    kept = "".join(
        character for character in heading.lower() if character.isalnum() or character in " -_"
    )
    return kept.replace(" ", "-")


def document_anchors(source: str) -> set[str]:
    """Every anchor one Markdown document exposes.

    Each heading contributes its GitHub slug — computed from the RENDERED
    heading text, so links, images, inline code, and emphasis inside a
    heading slug the way GitHub renders them — plus every explicit
    ``<a id="…">`` in real HTML flow (anchors inside code samples and
    commented-out HTML register nothing). Repeated slugs get GitHub's
    occupied-set ``-1``, ``-2``, … suffixes; matching is exact, because
    element ids are case-sensitive.

    Args:
        source: Complete document text.

    Returns:
        The set of valid fragments for links into this document.
    """
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    tokens = parse_markdown(source)
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        # A heading_open token is always immediately followed by its inline
        # content token in the markdown-it stream.
        base = github_slug(_rendered_inline_text(tokens[index + 1].children or []))
        result = base
        bump = occurrences.get(base, 0)
        while result in anchors:
            bump += 1
            result = f"{base}-{bump}"
        occurrences[base] = bump
        anchors.add(result)
    for token in tokens:
        for html in _html_chunks(token):
            for match in _ANCHOR_ID_PATTERN.finditer(html):
                anchors.add(match.group(1))
    return anchors


def _html_chunks(token: Token) -> list[str]:
    """Comment-free HTML text of one block or inline HTML token."""
    if token.type == "html_block":
        return [_HTML_COMMENT_PATTERN.sub("", token.content)]
    if token.type == "inline":
        return [
            _HTML_COMMENT_PATTERN.sub("", child.content)
            for child in token.children or []
            if child.type == "html_inline"
        ]
    return []
