"""Locale-aware resolution for bilingual Markdown links and language switchers.

The pairing gate compares link targets semantically: a relative link into the
active bilingual corpus resolves to a locale-independent pair anchor, so the
English side's ``foo.md`` and the Chinese side's ``foo.zh.md`` compare equal.
Links are collected from the parsed Markdown token stream plus a scanner over
each inline chunk, never from raw regex over the whole document, so fenced and
inline code is never mistaken for a link. Every destination is carried in two
forms — the destination the parser resolved and the bytes exactly as authored
— because the structural signature compares external targets and
query/fragment suffixes exactly as written.
"""

from __future__ import annotations

import posixpath
import re
import urllib.parse
from collections.abc import Callable, Container
from dataclasses import dataclass
from typing import Any, Protocol, override

from markdown_it import MarkdownIt
from markdown_it.common.utils import isPunctChar, normalizeReference, unescapeAll

#: Prefix naming the semantic, locale-independent target of a corpus link.
SEMANTIC_TARGET_PREFIX = "hdsh-pairing-target:"

_SWITCHER_LINE_PATTERN = re.compile(
    r"^(?:English \| \[中文\]\([^\n]+\)|\[English\]\([^\n]+\) \| 中文)$"
)
_EXTERNAL_URL_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
#: CommonMark autolink scheme: a letter plus 1-31 scheme characters.
_AUTOLINK_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]{1,31}:")
#: CommonMark autolink bodies reject ASCII whitespace, controls, and angles.
_ANGLE_BODY_REJECTED = (
    frozenset("<>")
    | {chr(code) for code in range(0x20)}
    | {chr(code) for code in range(0x7F, 0xA0)}
)
#: GFM literal autolinks use JavaScript ``\s`` as their whitespace class.
_JS_WHITESPACE = frozenset(
    map(
        chr,
        (
            0x09,
            0x0A,
            0x0B,
            0x0C,
            0x0D,
            0x20,
            0xA0,
            0x1680,
            *range(0x2000, 0x200B),
            0x2028,
            0x2029,
            0x202F,
            0x205F,
            0x3000,
            0xFEFF,
        ),
    )
)
#: Line endings and space: micromark's allowed ``www`` predecessors.
_MARKDOWN_LINE_ENDING_OR_SPACE = "\t\n\r "
#: The characters micromark's ``www`` autolink accepts as its predecessor.
_WWW_PREDECESSORS = frozenset("(_[]~*")
#: micromark caps the protocol-name buffer at the length of ``https``.
_PROTOCOL_NAME_LIMIT = 5
#: CommonMark caps a link label at 999 characters.
_LABEL_MAX_LENGTH = 999
#: Maximum leading spaces before a link reference definition.
_DEFINITION_INDENT_MAX = 3


class FileExists(Protocol):
    """Callable deciding whether a repository-relative path is present."""

    def __call__(self, repo_path: str) -> bool:
        """Return whether ``repo_path`` is present in the content plane."""
        ...  # pragma: no cover - protocol


@dataclass(frozen=True)
class LinkContext:
    """Repository and source document used to resolve one relative link.

    The selected content plane is expressed through ``repository_file_exists``;
    gates that read the Git index pass an index-backed callable.
    """

    #: Absolute repository root.
    repo_root: str
    #: Repository-relative Markdown source path.
    source_path: str
    #: Whether an English Markdown path belongs to the active bilingual corpus.
    is_pair_source: Callable[[str], bool]
    #: Selected content plane; defaults to working-tree files.
    repository_file_exists: Callable[[str], bool]
    #: Complete document text of ``source_path``.
    markdown: str = ""


@dataclass(frozen=True)
class LinkLocaleViolation:
    """One relative document link whose target uses the wrong locale sibling."""

    source_path: str
    line: int
    url: str
    expected_url: str


@dataclass(frozen=True)
class DocumentLink:
    """One document link occurrence with its parsed and authored destinations.

    Reference-style links carry the effective definition's destination and
    line; the occurrence line preserves document order for signatures.
    """

    #: Zero-based line of the occurrence in the document.
    line: int
    #: Destination as the Markdown parser resolved it (entities decoded).
    href: str
    #: Destination bytes exactly as authored.
    authored: str
    #: Normalized label for reference-style links; ``None`` for inline links.
    label: str | None
    #: Zero-based line of the effective definition; ``None`` for inline links.
    definition_line: int | None


@dataclass(frozen=True)
class _ResolvedLink:
    """Internal resolution result for one document link."""

    source: str
    zh: str
    target_path: str
    suffix: str
    expected_path: str
    expected_url: str
    locale: str


@dataclass(frozen=True)
class _ScanEntry:
    """One link-shaped construct found by an inline-chunk scan."""

    #: Newlines between the chunk start and the construct's first byte.
    line_offset: int
    reference: bool
    label: str | None
    parsed: str
    authored: str
    #: Authored destination range within the chunk; empty for references.
    dest_start: int
    dest_end: int


@dataclass(frozen=True)
class _DefinitionScan:
    """One effective reference definition located in the document source."""

    authored: str
    href: str
    line: int
    #: Absolute ``(line, column, end_column)`` of the authored destination.
    span: tuple[int, int, int] | None


class _AuthoredDestinationParser(MarkdownIt):
    """Parser whose link destinations keep their authored text.

    markdown-it percent-encodes destinations through ``normalizeLink`` for
    rendering; the gate resolves destinations instead of rendering them, and
    reference ``href`` values must match the scanner's own decoding of inline
    destinations byte for byte.
    """

    @override
    def normalizeLink(self, url: str) -> str:
        """Return the destination unchanged."""
        return url


_PARSER = _AuthoredDestinationParser("commonmark").enable("table")


def is_external_or_absolute_markdown_url(url: str) -> bool:
    """Whether a link destination is outside the repository-relative space.

    Args:
        url: Link destination as parsed from Markdown.

    Returns:
        True for schemed URLs, absolute paths, and protocol-relative URLs.
    """
    return _EXTERNAL_URL_PATTERN.match(url) is not None or url.startswith(("/", "\\", "//"))


def split_markdown_url_target(url: str) -> tuple[str, str]:
    """Split a destination into its path and its query/fragment suffix.

    Args:
        url: Link destination.

    Returns:
        The path before the first ``#`` or ``?``, and the remainder including
        that character.
    """
    for index, character in enumerate(url):
        if character in "#?":
            return url[:index], url[index:]
    return url, ""


def _decode_path(path: str) -> str:
    try:
        return urllib.parse.unquote(path, errors="strict")
    except UnicodeDecodeError:
        return path


def _repository_relative_path(path: str) -> str | None:
    normalized = posixpath.normpath(path)
    if normalized in {"", ".", ".."} or normalized.startswith("../") or posixpath.isabs(normalized):
        return None
    return normalized


def _resolve_repository_target(raw_path: str, context: LinkContext) -> str | None:
    decoded = _decode_path(raw_path)
    joined = posixpath.join(posixpath.dirname(context.source_path), decoded)
    exact = _repository_relative_path(joined)
    if exact is None:
        return None
    return exact if context.repository_file_exists(exact) else None


def _pair_target(target_path: str, context: LinkContext) -> tuple[str, str] | None:
    if target_path.endswith(".zh.md"):
        source = target_path[: -len(".zh.md")] + ".md"
    elif target_path.endswith(".md"):
        source = target_path
    else:
        return None
    if not context.is_pair_source(source):
        return None
    return source, source[: -len(".md")] + ".zh.md"


def _encode_path_segment(segment: str) -> str:
    # ``quote(safe="")`` leaves exactly the RFC 3986 unreserved characters
    # (plus ``%`` for already-encoded input).
    return urllib.parse.quote(segment, safe="")


def _relative_expected_path(context: LinkContext, expected_path: str, raw_path: str) -> str:
    relative = posixpath.relpath(expected_path, start=posixpath.dirname(context.source_path) or ".")
    encoded = "/".join(_encode_path_segment(part) for part in relative.split("/"))
    return f"./{encoded}" if raw_path.startswith("./") and not encoded.startswith(".") else encoded


def _expected_locale_path(
    raw_path: str, locale: str, context: LinkContext, expected_path: str
) -> str:
    if locale == "zh" and raw_path.endswith(".md") and not raw_path.endswith(".zh.md"):
        return f"{raw_path[: -len('.md')]}.zh.md"
    if locale == "en" and raw_path.endswith(".zh.md"):
        return raw_path[: -len(".zh.md")] + ".md"
    return _relative_expected_path(context, expected_path, raw_path)


def _resolve_link(url: str, context: LinkContext, authored_url: str) -> _ResolvedLink | None:
    if is_external_or_absolute_markdown_url(url):
        return None
    path, _ = split_markdown_url_target(url)
    authored_path, authored_suffix = split_markdown_url_target(authored_url)
    if path == "":
        return None
    target_path = _resolve_repository_target(path, context)
    if target_path is None:
        return None
    pair = _pair_target(target_path, context)
    if pair is None:
        return None
    source, zh = pair
    locale = "zh" if context.source_path.endswith(".zh.md") else "en"
    expected_path = zh if locale == "zh" else source
    return _ResolvedLink(
        source=source,
        zh=zh,
        target_path=target_path,
        suffix=authored_suffix,
        expected_path=expected_path,
        expected_url=(
            _expected_locale_path(authored_path, locale, context, expected_path) + authored_suffix
        ),
        locale=locale,
    )


def language_switcher_targets(counterpart: str, public_blob_root: str) -> list[str]:
    """Return the accepted switcher destinations for one counterpart.

    Args:
        counterpart: Repository-relative counterpart path.
        public_blob_root: Manifest-configured absolute-URL prefix; empty when
            the repository accepts no absolute switcher form.

    Returns:
        The counterpart's basename plus, when configured, the public
        repository blob URL of the counterpart.
    """
    targets = [counterpart.rsplit("/", 1)[-1]]
    if public_blob_root:
        targets.append(f"{public_blob_root}{counterpart}")
    return targets


def requires_source_language_switcher(source: str, generated: Container[str]) -> bool:
    """Whether an authored English source must link back to its Chinese side.

    Generated English sources cannot carry a switcher without making their
    generator stale; the pairing manifest's ``generated`` array lists them,
    and their Chinese counterparts still link back.

    Args:
        source: Repository-relative English document path.
        generated: Manifest-listed generated English source paths.

    Returns:
        True unless the source is a listed generated English source.
    """
    return source not in generated


def _find_label_end(text: str, start: int) -> int | None:
    """Return the offset of the ``]`` closing the label opened at ``start``."""
    depth = 0
    index = start
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            index += 2
            continue
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _skip_code_span(content: str, start: int) -> int:
    """Return the offset after the code span whose backtick run starts here."""
    length = 1
    while start + length < len(content) and content[start + length] == "`":
        length += 1
    index = start + length
    while index < len(content):
        if content[index] != "`":
            index += 1
            continue
        run = index
        while run < len(content) and content[run] == "`":
            run += 1
        if run - index == length:
            return run
        index = run
    return len(content)


def _parsed_destination(authored: str) -> str:
    """Resolve escapes and character references exactly as the parser does.

    ``unescapeAll`` is the function markdown-it itself applies to link
    destinations, so the scanner's parsed form and the parser's ``href`` stay
    byte-identical; CommonMark requires the semicolon on character
    references, so ``a&ampb.md`` stays verbatim.
    """
    return unescapeAll(authored)


def _parse_destination(text: str, start: int) -> tuple[str, int, int] | None:
    """Parse one CommonMark link destination starting at ``start``.

    Returns:
        The authored destination, its start offset, and its exclusive end
        offset, or ``None`` when the text at ``start`` is malformed.
    """
    if start >= len(text):
        return None
    if text[start] == "<":
        index = start + 1
        while index < len(text):
            character = text[index]
            if character == "\\" and index + 1 < len(text):
                index += 2
                continue
            if character == ">":
                return text[start + 1 : index], start, index + 1
            if character in "<\n":
                return None
            index += 1
        return None
    index = start
    end = start
    depth = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            index += 2
            end = index
            continue
        if character <= " " or character in "<>":
            break
        if character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                break
            depth -= 1
        index += 1
        end = index
    return text[start:end], start, end


def _close_inline_link(text: str, destination_end: int) -> int | None:
    """Return the offset after the ``)`` closing an inline link, or ``None``."""
    index = destination_end
    while index < len(text) and text[index] in " \t\n":
        index += 1
    if index < len(text) and text[index] == ")":
        return index + 1
    quote = text[index] if index < len(text) else ""
    if quote not in {'"', "'", "("}:
        return None
    closer = ")" if quote == "(" else quote
    index += 1
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            index += 2
            continue
        if character == closer:
            index += 1
            while index < len(text) and text[index] in " \t\n":
                index += 1
            if index < len(text) and text[index] == ")":
                return index + 1
            return None
        index += 1
    return None


#: CommonMark raw-HTML grammar pieces for the inline scanner.
_TAG_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_ATTRIBUTE_NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9_.:-]*")
_UNQUOTED_ATTRIBUTE_VALUE = re.compile(r"[^ \t\n\"'=<>`]+")


def _match_html_comment(content: str, start: int) -> int | None:
    """Match one CommonMark HTML comment at ``start``; ``None`` when not one."""
    if content.startswith("<!-->", start):
        return start + 5
    if content.startswith("<!--->", start):
        return start + 6
    if content.startswith("<!--", start):
        comment_end = content.find("-->", start + 4)
        return comment_end + 3 if comment_end != -1 else start + 1
    return None


def _match_declaration(content: str, start: int) -> int | None:
    """Match one CommonMark declaration (``<!X … >``) at ``start``."""
    if content[start + 1 : start + 2] == "!" and _is_ascii_alpha(content[start + 2 : start + 3]):
        declaration_end = content.find(">", start + 3)
        return declaration_end + 1 if declaration_end != -1 else None
    return None


def _match_processing_instruction(content: str, start: int) -> int | None:
    """Match one CommonMark processing instruction (``<? … ?>``) at ``start``."""
    if content[start + 1 : start + 2] == "?":
        instruction_end = content.find("?>", start + 2)
        return instruction_end + 2 if instruction_end != -1 else None
    return None


def _match_open_tag(content: str, start: int) -> int | None:
    """Match one CommonMark open tag at ``start``; attributes fully validated."""
    i = start + 1
    name = _TAG_NAME.match(content, i)
    if name is None:
        return None
    i = name.end()
    while i < len(content):
        character = content[i]
        if character == ">":
            return i + 1
        if character == "/":
            return i + 2 if content[i + 1 : i + 2] == ">" else None
        if character in " \t\n":
            i += 1
            continue
        attribute = _ATTRIBUTE_NAME.match(content, i)
        if attribute is None:
            return None
        i = attribute.end()
        if content[i : i + 1] == "=":
            i += 1
            quote = content[i : i + 1]
            if quote in {"'", '"'}:
                closing_quote = content.find(quote, i + 1)
                if closing_quote == -1:
                    return None
                i = closing_quote + 1
            else:
                value = _UNQUOTED_ATTRIBUTE_VALUE.match(content, i)
                if value is None:
                    return None
                i = value.end()
    return None


def _match_close_tag(content: str, start: int) -> int | None:
    """Match one CommonMark close tag (``</name >``) at ``start``."""
    name = _TAG_NAME.match(content, start + 2)
    if name is None:
        return None
    i = name.end()
    while i < len(content) and content[i] in " \t\n":
        i += 1
    return i + 1 if content[i : i + 1] == ">" else None


def _consume_angle(content: str, start: int, entries: list[_ScanEntry]) -> int:
    """Consume one ``<`` at ``start`` as an autolink, raw HTML, or plain text.

    Every raw-HTML form follows CommonMark's grammar; anything else leaves
    the ``<`` as text so the scan continues inside it.
    """
    inner = content.find(">", start)
    if inner == -1:
        return start + 1
    body = content[start + 1 : inner]
    if _AUTOLINK_SCHEME.match(body) is not None and not any(
        c in _ANGLE_BODY_REJECTED for c in body
    ):
        entries.append(
            _ScanEntry(
                line_offset=content.count("\n", 0, start),
                reference=False,
                label=None,
                parsed=_parsed_destination(body),
                authored=body,
                dest_start=start + 1,
                dest_end=inner,
            )
        )
        return inner + 1
    for matcher in (
        _match_html_comment,
        _match_declaration,
        _match_processing_instruction,
        _match_open_tag,
        _match_close_tag,
    ):
        if (end := matcher(content, start)) is not None:
            return end
    cdata_end = content.find("]]>", start + 9) if content.startswith("<![CDATA[", start) else -1
    return cdata_end + 3 if cdata_end != -1 else start + 1


def _is_ascii_alpha(character: str) -> bool:
    """Whether one character is an ASCII letter."""
    return "a" <= character <= "z" or "A" <= character <= "Z"


#: mdast-util's transform patterns, applied to text the state machine left
#: alone; together the machine and the transform accept GFM literal autolinks.
_URL_LITERAL = re.compile(r"(https?://|www(?=\.))([-.\w]+)([^ \t\r\n]*)", re.IGNORECASE | re.ASCII)
_EMAIL_LITERAL = re.compile(r"([-.\w+]+)@([-\w]+(?:\.[-\w]+)+)", re.ASCII)
#: Trailing characters the transform strips from a URL; ')' is restored while
#: parentheses stay balanced.
_URL_TRAILING = re.compile(r"[!\"&'),.:;<>?\]}]+$")


def _is_correct_domain(domain: str) -> bool:
    """Whether the transform accepts a dot-separated domain.

    At least two parts; each of the last two non-empty parts carries no
    underscore and at least one ASCII alphanumeric.
    """
    parts = domain.split(".")
    if "." not in domain:
        return False
    for part in parts[-2:]:
        if part and ("_" in part or not any(_is_ascii_alnum(c) for c in part)):
            return False
    return True


def _split_url(url: str) -> tuple[str, str]:
    """Split a URL into its body and trailing characters to drop."""
    trailing = _URL_TRAILING.search(url)
    if trailing is None:
        return url, ""
    body = url[: trailing.start()]
    trail = trailing.group()
    while True:
        closing = trail.find(")")
        if closing == -1 or body.count("(") <= body.count(")"):
            return body, trail
        body += trail[: closing + 1]
        trail = trail[closing + 1 :]


def _is_ascii_alnum(character: str) -> bool:
    """Whether one character is an ASCII letter or digit."""
    return _is_ascii_alpha(character) or "0" <= character <= "9"


def _is_atext(character: str) -> bool:
    """Whether one character may appear in an email autolink's local part."""
    return _is_ascii_alnum(character) or character in "+-._"


def _is_trail(content: str, index: int) -> bool:
    """Whether the run at ``index`` is trailing punctuation followed by an end.

    Mirrors micromark's ``trail``: a run of ``!"')*.,:;?_~`` (plus one
    well-formed character reference, plus ``]`` when followed by whitespace or
    a resource opener) that whitespace, ``<``, or the chunk end terminates.
    The literal autolink ends before a trail; a non-trail punctuation
    character belongs to the URL.
    """
    i = index
    while i < len(content):
        character = content[i]
        if character in "!\"')*.,:;?_~":
            i += 1
        elif character == "&":
            j = i + 1
            while j < len(content) and _is_ascii_alpha(content[j]):
                j += 1
            if j == i + 1 or j >= len(content) or content[j] != ";":
                return False
            i = j + 1
        elif character == "]":
            i += 1
            if i >= len(content) or content[i] in "([" or content[i] in _JS_WHITESPACE:
                return True
        else:
            return character == "<" or character in _JS_WHITESPACE
    return True


def _match_domain(content: str, index: int) -> int | None:
    """Match micromark's ``domain`` at ``index``; ``None`` when it fails.

    The domain runs until whitespace or punctuation (``-`` included), with
    ``.`` and ``_`` consumed only when they are not a trail; an underscore in
    the last two dot-separated segments rejects the match.
    """
    underscore_last = False
    underscore_penultimate = False
    seen = False
    i = index
    while i < len(content):
        character = content[i]
        if character in "._":
            if _is_trail(content, i):
                break
            if character == "_":
                underscore_last = True
            else:
                underscore_penultimate = underscore_last
                underscore_last = False
        elif character in _JS_WHITESPACE or (character != "-" and isPunctChar(character)):
            break
        else:
            seen = True
        i += 1
    if underscore_last or underscore_penultimate or not seen:
        return None
    return i


def _match_path(content: str, index: int) -> int:
    """Match micromark's ``path`` at ``index``; the path never fails.

    Parentheses stay balanced inside the path; the listed punctuation ends it
    only when it forms a trail; whitespace ends it outright.
    """
    opened = 0
    closed = 0
    i = index
    while i < len(content):
        character = content[i]
        if character == "(":
            opened += 1
        elif character == ")" and closed < opened:
            closed += 1
        elif character in "!\"&')*.,:;<?]_~":
            if _is_trail(content, i):
                break
        elif character in _JS_WHITESPACE:
            break
        i += 1
    return i


def _match_email(content: str, start: int) -> int | None:
    """Match micromark's email autolink at ``start``; ``None`` when it fails.

    Local atext, one ``@``, then a domain of ASCII alphanumerics, ``-``, and
    ``_`` with at least one dot; a dot ends the match unless an alphanumeric
    follows, and the domain must end in an ASCII letter.
    """
    i = start
    while i < len(content) and _is_atext(content[i]):
        i += 1
    if i >= len(content) or content[i] != "@":
        return None
    i += 1
    seen = False
    dotted = False
    while i < len(content):
        character = content[i]
        if character == "." and i + 1 < len(content) and _is_ascii_alnum(content[i + 1]):
            dotted = True
        elif character in "-_" or _is_ascii_alnum(character):
            seen = True
        else:
            break
        i += 1
    if seen and dotted and _is_ascii_alpha(content[i - 1]):
        return i
    return None


def _consume_literal_autolink(content: str, start: int, entries: list[_ScanEntry]) -> int:
    """Consume one GFM literal autolink (email, ``www``, or ``http(s)``) at ``start``.

    The micromark state machine port runs first (parser-time autolinks); when
    it declines, the mdast-util transform patterns accept the remainder —
    together they reproduce GFM's effective literal-autolink behavior.
    Emails parse to a ``mailto:`` destination and ``www`` forms to ``http://``,
    both carrying their authored bytes.
    """
    character = content[start]
    previous = content[start - 1] if start > 0 else None
    end: int | None = None
    scheme = ""
    if _is_atext(character) and (previous is None or (previous != "/" and not _is_atext(previous))):
        email_end = _match_email(content, start)
        if email_end is not None:
            end = email_end
            scheme = "mailto:"
    if (
        end is None
        and character in "wW"
        and (
            previous is None
            or previous in _WWW_PREDECESSORS
            or previous in _MARKDOWN_LINE_ENDING_OR_SPACE
        )
        and content[start : start + 4].lower() == "www."
        and start + 4 < len(content)
    ):
        domain_end = _match_domain(content, start + 4)
        if domain_end is not None:
            end = _match_path(content, domain_end)
            scheme = "http://"
    if end is None and character in "hH" and (previous is None or not _is_ascii_alpha(previous)):
        i = start
        while i < len(content) and _is_ascii_alpha(content[i]) and i - start < _PROTOCOL_NAME_LIMIT:
            i += 1
        after_scheme = (
            i + 3
            if i < len(content)
            and content[i] == ":"
            and content[start:i].lower() in ("http", "https")
            and content[i + 1 : i + 3] == "//"
            else None
        )
        if after_scheme is not None and after_scheme < len(content):
            following = content[after_scheme]
            resource_start = not (
                following in _JS_WHITESPACE
                or following < "\x20"
                or "\x7f" <= following <= "\x9f"
                or isPunctChar(following)
            )
            if resource_start:
                domain_end = _match_domain(content, after_scheme)
                if domain_end is not None:
                    end = _match_path(content, domain_end)
    if end is None:
        transformed = _match_transform_autolink(content, start)
        if transformed is None:
            return start + 1
        end, parsed = transformed
        entries.append(
            _ScanEntry(
                line_offset=content.count("\n", 0, start),
                reference=False,
                label=None,
                parsed=parsed,
                authored=content[start:end],
                dest_start=start,
                dest_end=end,
            )
        )
        return end
    authored = content[start:end]
    entries.append(
        _ScanEntry(
            line_offset=content.count("\n", 0, start),
            reference=False,
            label=None,
            parsed=f"{scheme}{authored}" if scheme else authored,
            authored=authored,
            dest_start=start,
            dest_end=end,
        )
    )
    return end


def _match_transform_autolink(content: str, start: int) -> tuple[int, str] | None:
    """Match the mdast-util transform patterns at ``start``; ``None`` if neither fits.

    The transform accepts a match only at a text-node start or after
    whitespace or punctuation; construct boundaries end in punctuation or
    whitespace, so the previous-character check subsumes node starts. An
    email's predecessor may not be ``/``.
    """
    if start > 0:
        previous = content[start - 1]
        if previous not in _JS_WHITESPACE and not isPunctChar(previous):
            return None
    url = _URL_LITERAL.match(content, start)
    if url is not None:
        protocol, domain, path = url.group(1), url.group(2), url.group(3)
        prefix = ""
        if protocol[0].lower() == "w":
            domain = protocol + domain
            protocol = ""
            prefix = "http://"
        if _is_correct_domain(domain):
            body, trail = _split_url(domain + path)
            if body:
                return url.end() - len(trail), f"{prefix}{protocol}{body}"
    email = _EMAIL_LITERAL.match(content, start)
    if email is not None and email.group(2)[-1] not in "-_0123456789":
        if start > 0 and content[start - 1] == "/":
            return None
        return email.end(), f"mailto:{email.group(0)}"
    return None


def _label_contains_link(label: str, definitions: Container[str]) -> bool:
    """Whether a link label holds an active link, which voids the outer one.

    CommonMark forbids links inside link labels: when the label parses into
    any link construct (inline or resolved reference), the outer bracket
    sequence stays text and the inner constructs are what remain.
    """
    return bool(_scan_chunk(label, definitions))


def _consume_bracket(
    content: str, start: int, definitions: Container[str], entries: list[_ScanEntry], *, image: bool
) -> int:
    """Consume one ``[`` (or ``![``) at ``start`` as a link, image, or text."""
    label_open = start + (2 if image else 1)
    label_end = _find_label_end(content, label_open - 1)
    if label_end is None:
        return start + 1
    label = content[label_open:label_end]
    if len(label) > _LABEL_MAX_LENGTH:
        return start + 1
    if _label_contains_link(label, definitions):
        return start + 1
    after = label_end + 1
    if after < len(content) and content[after] == "(":
        index = after + 1
        while index < len(content) and content[index] in " \t\n":
            index += 1
        destination = _parse_destination(content, index)
        if destination is not None:
            authored, dest_start, dest_end = destination
            stop = _close_inline_link(content, dest_end)
            if stop is not None:
                if not image:
                    entries.append(
                        _ScanEntry(
                            line_offset=content.count("\n", 0, start),
                            reference=False,
                            label=None,
                            parsed=_parsed_destination(authored),
                            authored=authored,
                            dest_start=dest_start,
                            dest_end=dest_end,
                        )
                    )
                return stop
        return start + 1
    effective = label
    stop = after
    if after < len(content) and content[after] == "[":
        second_end = _find_label_end(content, after)
        if second_end is None:
            return start + 1
        collapsed = content[after + 1 : second_end]
        if collapsed:
            effective = collapsed
        stop = second_end + 1
    normalized = normalizeReference(effective)
    if image:
        return stop if normalized in definitions else start + 1
    if normalized not in definitions:
        return start + 1
    entries.append(
        _ScanEntry(
            line_offset=content.count("\n", 0, start),
            reference=True,
            label=normalized,
            parsed="",
            authored="",
            dest_start=-1,
            dest_end=-1,
        )
    )
    return stop


def _scan_chunk(content: str, definitions: Container[str]) -> list[_ScanEntry]:
    """Scan one inline chunk for link-shaped constructs in document order."""
    entries: list[_ScanEntry] = []
    index = 0
    while index < len(content):
        character = content[index]
        if character == "\\":
            index += 2
            continue
        if character == "`":
            index = _skip_code_span(content, index)
            continue
        if character == "<":
            index = _consume_angle(content, index, entries)
            continue
        if character == "[":
            index = _consume_bracket(content, index, definitions, entries, image=False)
            continue
        if character == "!" and content[index + 1 : index + 2] == "[":
            index = _consume_bracket(content, index, definitions, entries, image=True)
            continue
        index = _consume_literal_autolink(content, index, entries)
    return entries


def _locate_definition_destination(span: str) -> tuple[str, int, int] | None:
    """Locate the authored destination inside one definition's line span."""
    index = 0
    indent = 0
    while index < len(span) and span[index] in " \t":
        indent += 1
        index += 1
    if indent > _DEFINITION_INDENT_MAX or index >= len(span) or span[index] != "[":
        return None
    label_end = _find_label_end(span, index)
    if label_end is None or label_end + 1 >= len(span) or span[label_end + 1] != ":":
        return None
    index = label_end + 2
    while index < len(span) and span[index] in " \t\n":
        index += 1
    return _parse_destination(span, index)


def _scan_definitions(
    markdown: str, references: dict[str, dict[str, Any]]
) -> dict[str, _DefinitionScan]:
    """Locate every effective reference definition in the document source."""
    lines = markdown.split("\n")
    scans: dict[str, _DefinitionScan] = {}
    for label, record in references.items():
        begin: int = record["map"][0]
        span = "\n".join(lines[begin : record["map"][1]])
        located = _locate_definition_destination(span)
        href: str = record["href"]
        if located is None:
            scans[label] = _DefinitionScan(authored=href, href=href, line=begin, span=None)
            continue
        authored, start, stop = located
        line = begin + span.count("\n", 0, start)
        column = start - (span.rfind("\n", 0, start) + 1)
        scans[label] = _DefinitionScan(
            authored=authored, href=href, line=begin, span=(line, column, column + stop - start)
        )
    return scans


def document_links(markdown: str) -> list[DocumentLink]:
    """Collect every document link occurrence in document order.

    Reference-style links resolve to their effective definition's destination,
    and images contribute nothing (their label content is alt text, not nodes).
    """
    env: dict[str, Any] = {}
    tokens = _PARSER.parse(markdown, env)
    references: dict[str, dict[str, Any]] = env.get("references", {})
    scans = _scan_definitions(markdown, references)
    links: list[DocumentLink] = []
    for token in tokens:
        if token.type != "inline":
            continue
        base = token.map[0] if token.map is not None else 0
        for entry in _scan_chunk(token.content, references):
            if not entry.reference:
                links.append(
                    DocumentLink(
                        line=base + entry.line_offset,
                        href=entry.parsed,
                        authored=entry.authored,
                        label=None,
                        definition_line=None,
                    )
                )
                continue
            scan = scans[entry.label or ""]
            links.append(
                DocumentLink(
                    line=base + entry.line_offset,
                    href=scan.href,
                    authored=scan.authored,
                    label=entry.label,
                    definition_line=scan.line,
                )
            )
    return links


def language_switcher_line(
    markdown: str, accepted_targets: tuple[str, ...] | list[str]
) -> int | None:
    """Find the line of the canonical top-level language switcher.

    The switcher is the first paragraph after the document's first H1 heading
    (setext included; earlier non-H1 headings do not end the search) whose
    authored text matches ``English | [中文](…)`` or ``[English](…) | 中文``
    exactly and whose single inline link targets one of ``accepted_targets``.
    The scan stops at the next heading of any depth.

    Args:
        markdown: Complete document text.
        accepted_targets: Accepted counterpart link destinations.

    Returns:
        The zero-based switcher line index, or None when absent.
    """
    tokens = _PARSER.parse(markdown)
    accepted = set(accepted_targets)
    depth = 0
    after_h1 = False
    paragraph_pending = False
    for token in tokens:
        top_level = depth == 0
        opening = token.type.endswith("_open")
        if top_level and not after_h1:
            if opening and token.type == "heading_open" and token.tag == "h1":
                after_h1 = True
        elif top_level:
            if opening and token.type == "heading_open":
                return None
            if opening and token.type == "paragraph_open":
                paragraph_pending = True
        if token.type == "inline" and paragraph_pending:
            paragraph_pending = False
            base = token.map[0] if token.map is not None else 0
            if _SWITCHER_LINE_PATTERN.match(token.content) is None:
                continue
            inline_links = [
                entry for entry in _scan_chunk(token.content, ()) if not entry.reference
            ]
            if len(inline_links) == 1 and inline_links[0].parsed in accepted:
                return base + inline_links[0].line_offset
        if opening:
            depth += 1
        elif token.type.endswith("_close"):
            depth -= 1
    return None


def has_language_switcher(markdown: str, accepted_targets: tuple[str, ...] | list[str]) -> bool:
    """Whether the document carries its canonical top-level language switcher.

    Args:
        markdown: Complete document text.
        accepted_targets: Accepted counterpart link destinations.

    Returns:
        True when the switcher line is present.
    """
    return language_switcher_line(markdown, accepted_targets) is not None


def semantic_link_target(parsed: str, authored: str, context: LinkContext) -> str:
    """Compute the locale-independent semantic target of one link destination.

    Corpus links normalize to ``hdsh-pairing-target:<english-path><suffix>``
    with the suffix exactly as authored; every other destination keeps its
    authored bytes.

    Args:
        parsed: Destination as the Markdown parser resolved it.
        authored: Destination bytes exactly as authored.
        context: Repository and source context.

    Returns:
        The semantic target used by the structural signature.
    """
    if is_external_or_absolute_markdown_url(parsed):
        return authored
    resolved = _resolve_link(parsed, context, authored)
    if resolved is None:
        return authored
    return f"{SEMANTIC_TARGET_PREFIX}{resolved.source}{resolved.suffix}"


def link_locale_violations(
    markdown: str,
    context: LinkContext,
    skip_targets: tuple[str, ...] | list[str] | None = None,
) -> list[LinkLocaleViolation]:
    """Return one violation per wrong-locale relative document link.

    Inline links report at their occurrence; reference-style links report
    their effective definition once per label. Reported URLs are the authored
    destination bytes.

    Args:
        markdown: Complete document text of ``context.source_path``.
        context: Repository and source context.
        skip_targets: Accepted switcher targets; the detected switcher line
            is exempt from locale checking.

    Returns:
        Violations with source line, authored URL, and expected URL.
    """
    skip: list[str] = list(skip_targets or [])
    switcher_line = language_switcher_line(markdown, skip)
    reported_labels: set[str] = set()
    violations: list[LinkLocaleViolation] = []
    for link in document_links(markdown):
        if link.line == switcher_line:
            continue
        if link.label is not None:
            if link.label in reported_labels:
                continue
            reported_labels.add(link.label)
        if is_external_or_absolute_markdown_url(link.href):
            continue
        resolved = _resolve_link(link.href, context, link.authored)
        if resolved is None or resolved.target_path == resolved.expected_path:
            continue
        report_line = link.definition_line if link.definition_line is not None else link.line
        violations.append(
            LinkLocaleViolation(
                source_path=context.source_path,
                line=report_line + 1,
                url=link.authored,
                expected_url=resolved.expected_url,
            )
        )
    return violations


def normalize_translation_markdown_links(
    markdown: str,
    context: LinkContext,
    skip_targets: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Normalize only paired-document locale paths, retaining every other byte.

    Every relative link into the active bilingual corpus — inline or through a
    referenced definition — has its authored destination replaced with the
    locale-independent pair anchor plus its exact query/fragment suffix. Links
    inside code spans and fenced blocks are untouched, and bytes outside
    destinations never change.

    Args:
        markdown: Complete document text.
        context: Repository and source context.
        skip_targets: Accepted switcher targets; the switcher link is exempt.

    Returns:
        The document with corpus-link destinations normalized.
    """
    skip: list[str] = list(skip_targets or [])
    switcher_line = language_switcher_line(markdown, skip)
    lines = markdown.split("\n")
    env: dict[str, Any] = {}
    tokens = _PARSER.parse(markdown, env)
    references: dict[str, dict[str, Any]] = env.get("references", {})
    scans = _scan_definitions(markdown, references)
    replacements: list[tuple[int, int, int, str]] = []
    referenced_labels: set[str] = set()
    spans: dict[tuple[int, int], int] = {}
    for token in tokens:
        if token.type != "inline" or token.map is None:
            continue
        begin, end = token.map[0], token.map[1]
        span_text = "\n".join(lines[begin:end])
        offset = span_text.find(token.content, spans.get((begin, end), 0))
        if offset == -1:
            offset = span_text.find(token.content)
        if offset == -1:
            continue
        spans[(begin, end)] = offset + len(token.content)
        for entry in _scan_chunk(token.content, references):
            if entry.reference:
                referenced_labels.add(entry.label or "")
                continue
            if begin + entry.line_offset == switcher_line:
                continue
            resolved = _resolve_link(entry.parsed, context, entry.authored)
            if resolved is None:
                continue
            absolute = offset + entry.dest_start
            line = begin + span_text.count("\n", 0, absolute)
            column = absolute - (span_text.rfind("\n", 0, absolute) + 1)
            replacements.append(
                (
                    line,
                    column,
                    column + entry.dest_end - entry.dest_start,
                    f"{SEMANTIC_TARGET_PREFIX}{resolved.source}{resolved.suffix}",
                )
            )
    for label in referenced_labels:
        scan = scans[label]
        if scan.span is None:
            continue
        resolved = _resolve_link(scan.href, context, scan.authored)
        if resolved is None:
            continue
        line, column, end_column = scan.span
        replacements.append(
            (
                line,
                column,
                end_column,
                f"{SEMANTIC_TARGET_PREFIX}{resolved.source}{resolved.suffix}",
            )
        )
    for line, column, end_column, value in sorted(
        replacements, key=lambda item: (item[0], item[1]), reverse=True
    ):
        text = lines[line]
        lines[line] = text[:column] + value + text[end_column:]
    return "\n".join(lines)
