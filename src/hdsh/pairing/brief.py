"""Minimal-update briefing for out-of-sync translation pairs.

``hdsh pairing brief [--apply] [<pair>...]`` maps one drifted side's change
since the last confirmed state at the narrowest safely aligned granularity
(code-fence-only splice, changed Markdown units, heading sections, whole
document) and renders the diff, each changed span's three-way context, the
terminology rows the change touches, first-occurrence movement notes, and a
digest of the binding update rules. ``--apply`` writes the computed
counterpart when the change is confined to fenced code blocks. The workflow
that consumes the briefing is ``.agents/skills/translating-docs/SKILL.md``.

Reference definitions consume no block tokens in the Markdown parser, so a
change confined to one never maps to a unit; the planner escalates that side
to a wider scope instead of mis-aligning spans. The pairing manifest and the
terminology table are required inputs; either missing fails the run.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hdsh.pairing import links as pairing_links
from hdsh.pairing import structure as pairing_structure
from hdsh.pairing.corpus import is_scope_file
from hdsh.pairing.git import GitError, run_git
from hdsh.pairing.manifest import MANIFEST_PATH, manifest_excluded, parse_manifest
from hdsh.pairing.records import anchor_of_argument, pair_paths, parse_record
from hdsh.pairing.structure import parse_markdown
from hdsh.pairing.verify import PairingRepository

if TYPE_CHECKING:
    import argparse

    from markdown_it.token import Token

    from hdsh import cliargs

TOOL = "hdsh pairing brief"

TERMINOLOGY_PATH = "docs/i18n/terminology.md"

BriefDirection = Literal["en-to-zh", "zh-to-en"]

ExclusionPredicate = Callable[[str], bool]
PairSourcePredicate = Callable[[str], bool]
LineSink = Callable[[str], None]


@dataclass(frozen=True)
class MarkdownSpan:
    """One block-level span of a Markdown document, in document order."""

    #: Position in the span list; briefing ids derive from it.
    index: int
    #: Structural kind compared for alignment, language-neutral: container
    #: path plus node type for units (``root.3:tableRow``), depth for
    #: sections (``section:2``).
    kind: str
    #: Reader-facing label: heading text for sections, node type for units.
    label: str
    #: 1-based first source line.
    start_line: int
    #: 1-based last source line.
    end_line: int
    #: The span's text, trailing newline normalized to exactly one.
    text: str


def _lines_of(markdown: str) -> list[str]:
    lines = markdown.replace("\r\n", "\n").split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def _slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    joined = "\n".join(lines[start_line - 1 : end_line])
    return f"{joined}\n"


@dataclass
class _Block:
    """One mdast-shaped block node built from the Markdown token stream."""

    type: str
    depth: int | None = None
    start_line: int = 0
    end_line: int = 0
    text: str = ""
    children: list[_Block] = field(default_factory=list)


_CONTAINER_OPENS = {
    "blockquote_open": "blockquote",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
    "list_item_open": "listItem",
    "table_open": "table",
    "tr_open": "tableRow",
    "th_open": "tableCell",
    "td_open": "tableCell",
}
_LEAF_WITH_INLINE = {"heading_open": "heading", "paragraph_open": "paragraph"}
_LEAF_SOLO = {"fence": "code", "code_block": "code", "html_block": "html", "hr": "thematicBreak"}
#: thead/tbody are pass-through: table rows align as direct table children.

_INLINE_VALUE_TYPES = frozenset({"text", "code_inline", "html_inline"})


def _inline_text(token: Token) -> str:
    """Concatenate the plain values inside one inline chunk.

    Emphasis, link, and image markers drop out — only their surviving text,
    inline code, and raw HTML content joins the label — so heading labels
    read as the rendered text does.
    """
    return "".join(
        child.content for child in token.children or [] if child.type in _INLINE_VALUE_TYPES
    )


def _block_tree(tokens: list[Token]) -> _Block:
    """Build the block tree the unit and section walkers descend."""
    root = _Block("root")
    stack: list[_Block] = [root]
    for index, token in enumerate(tokens):
        kind = token.type
        if kind.startswith(("thead", "tbody")):
            continue
        if kind.endswith("_close"):
            stack.pop()
            continue
        node: _Block | None = None
        if kind in _CONTAINER_OPENS:
            node = _Block(_CONTAINER_OPENS[kind])
        elif kind in _LEAF_WITH_INLINE:
            # markdown-it always emits the inline chunk directly after these
            # opens, so the next token carries the node's label text.
            node = _Block(
                _LEAF_WITH_INLINE[kind],
                depth=int(token.tag[1]) if kind == "heading_open" else None,
                text=_inline_text(tokens[index + 1]),
            )
        elif kind in _LEAF_SOLO:
            node = _Block(_LEAF_SOLO[kind])
        if node is None:
            continue
        start, end = token.map if token.map is not None else (0, 0)
        node.start_line = start + 1
        node.end_line = end
        stack[-1].children.append(node)
        # Every open token pairs with a ``*_close`` and stays on the stack;
        # solo leaves (fences, rules, HTML blocks) are complete at emission.
        if kind in _CONTAINER_OPENS or kind in _LEAF_WITH_INLINE:
            stack.append(node)
    return root


_UNIT_TYPES = frozenset(
    {"paragraph", "code", "tableRow", "listItem", "blockquote", "html", "thematicBreak"}
)


def markdown_units(markdown: str) -> list[MarkdownSpan]:
    """List a document's translation units.

    Units are the outermost block nodes a minimal update can replace
    independently: headings, paragraphs, code fences, table rows, list items,
    block quotes, HTML blocks, and thematic breaks; the container path is part of
    the kind so kind sequences only align when container membership also
    aligns.

    Args:
        markdown: Document text.

    Returns:
        Units in document order.
    """
    positions: list[tuple[str, str, int, int]] = []

    def visit(node: _Block, path: str) -> None:
        kind: str | None = None
        if node.type == "heading":
            kind = f"{path}:heading:{node.depth}"
        elif node.type in _UNIT_TYPES:
            kind = f"{path}:{node.type}"
        if kind is not None:
            positions.append((kind, node.type, node.start_line, node.end_line))
            return
        for child_index, child in enumerate(node.children):
            visit(child, f"{path}.{child_index}")

    visit(_block_tree(parse_markdown(markdown)), "root")
    positions.sort(key=lambda position: position[2])
    lines = _lines_of(markdown)
    return [
        MarkdownSpan(
            index=span_index,
            kind=kind,
            label=label,
            start_line=start,
            end_line=end,
            text=_slice_lines(lines, start, end),
        )
        for span_index, (kind, label, start, end) in enumerate(positions)
    ]


def section_spans(markdown: str) -> list[MarkdownSpan]:
    """List a document's heading-delimited sections.

    A leading ``preamble`` span is included when content precedes the first
    heading.

    Args:
        markdown: Document text.

    Returns:
        Sections in document order.
    """
    headings: list[tuple[int, int, str]] = []

    def visit(node: _Block) -> None:
        if node.type == "heading":
            headings.append((node.depth or 0, node.start_line, node.text))
        for child in node.children:
            visit(child)

    visit(_block_tree(parse_markdown(markdown)))
    headings.sort(key=lambda heading: heading[1])
    lines = _lines_of(markdown)
    spans: list[MarkdownSpan] = []
    first_heading_line = headings[0][1] if headings else len(lines) + 1
    if first_heading_line > 1:
        spans.append(
            MarkdownSpan(
                index=0,
                kind="preamble",
                label="(preamble before the first heading)",
                start_line=1,
                end_line=first_heading_line - 1,
                text=_slice_lines(lines, 1, first_heading_line - 1),
            )
        )
    for order, (depth, line, label) in enumerate(headings):
        end_line = (headings[order + 1][1] if order + 1 < len(headings) else len(lines) + 1) - 1
        spans.append(
            MarkdownSpan(
                index=len(spans),
                # Depth only: heading TEXT is translated across a pair, so it
                # cannot participate in cross-language alignment.
                kind=f"section:{depth}",
                label=label if label != "" else "(untitled section)",
                start_line=line,
                end_line=end_line,
                text=_slice_lines(lines, line, end_line),
            )
        )
    return spans


def spans_aligned(left: list[MarkdownSpan], right: list[MarkdownSpan]) -> bool:
    """Whether two span lists map one to one.

    Mapping is sound when both lists have the same non-zero length and the
    same kind at every position.

    Args:
        left: One document's spans.
        right: The other document's spans.

    Returns:
        True when index-wise mapping is sound.
    """
    return (
        len(left) > 0
        and len(left) == len(right)
        and all(span.kind == right[index].kind for index, span in enumerate(left))
    )


def changed_span_indices(before: list[MarkdownSpan], after: list[MarkdownSpan]) -> list[int]:
    """Indices whose text differs between two aligned span lists.

    Args:
        before: Spans of the earlier state.
        after: Spans of the later state, aligned with ``before``.

    Returns:
        Ascending changed indices.
    """
    return [span.index for index, span in enumerate(before) if span.text != after[index].text]


def _code_spans_of(markdown: str) -> list[MarkdownSpan]:
    spans = [span for span in markdown_units(markdown) if span.kind.endswith(":code")]
    return [
        MarkdownSpan(
            index=code_index,
            kind=span.kind,
            label=span.label,
            start_line=span.start_line,
            end_line=span.end_line,
            text=span.text,
        )
        for code_index, span in enumerate(spans)
    ]


def _replace_span_texts(
    markdown: str, spans: list[MarkdownSpan], replacements: dict[int, str]
) -> str:
    lines = _lines_of(markdown)
    for index in sorted(replacements, reverse=True):
        span = spans[index]
        lines[span.start_line - 1 : span.end_line] = _lines_of(replacements[index])
    joined = "\n".join(lines)
    return f"{joined}\n"


def _mask_code_spans(markdown: str, spans: list[MarkdownSpan]) -> str:
    return _replace_span_texts(
        markdown, spans, {span.index: f"HDSH_TRANSLATION_CODE_{span.index}\n" for span in spans}
    )


def compute_mechanical_update(
    confirmed_source: str, current_source: str, counterpart: str
) -> str | None:
    """Compute the counterpart update for a code-fence-only change.

    Fences are byte-identical across a pair, so when the source's prose is
    untouched and the counterpart's fences match the last-confirmed source,
    splicing the edited fences into the counterpart is the complete update —
    no translation judgment is involved.

    Args:
        confirmed_source: The changed side's last-confirmed text.
        current_source: The changed side's current text.
        counterpart: The other side's current text.

    Returns:
        The updated counterpart, or ``None`` when the change is not code-only.
    """
    confirmed = _code_spans_of(confirmed_source)
    current = _code_spans_of(current_source)
    target = _code_spans_of(counterpart)
    if len(confirmed) == 0 or len(confirmed) != len(current) or len(confirmed) != len(target):
        return None
    if _mask_code_spans(confirmed_source, confirmed) != _mask_code_spans(current_source, current):
        return None
    if any(span.text != target[index].text for index, span in enumerate(confirmed)):
        return None
    changed = {span.index: span.text for span in current if span.text != confirmed[span.index].text}
    if not changed:
        return None
    return _replace_span_texts(counterpart, target, changed)


@dataclass(frozen=True)
class TerminologyRow:
    """One parsed terminology-table data row."""

    english: str
    chinese: str
    #: The 首次出现 (first-occurrence) rendering, possibly empty.
    first: str
    #: The verbatim table row.
    line: str


def _plain_term(cell: str) -> str:
    return cell.replace("`", "").replace("**", "").strip()


_TABLE_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")


def parse_terminology_rows(terminology: str) -> list[TerminologyRow]:
    """Parse the data rows of the terminology table.

    Args:
        terminology: Full ``docs/i18n/terminology.md`` contents.

    Returns:
        Rows in table order.
    """
    rows: list[TerminologyRow] = []
    for line in terminology.split("\n"):
        if not line.startswith("|") or _TABLE_SEPARATOR.match(line):
            continue
        cells = ([cell.strip() for cell in line.split("|")] + [""] * 4)[:4]
        english = _plain_term(cells[1])
        if english in ("", "English"):
            continue
        rows.append(
            TerminologyRow(
                english=english,
                chinese=_plain_term(cells[2]),
                first=_plain_term(cells[3]),
                line=line,
            )
        )
    return rows


_WORD_LIKE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*[A-Za-z0-9]$")
_CONSONANT_Y = re.compile(r"[^aeiou]y$", re.IGNORECASE)
_REGEX_ESCAPE = re.compile(r"[.*+?^${}()|[\]\\]")


def term_offsets(text: str, term: str, english_inflections: bool = False) -> list[int]:
    """Character offsets of a term's occurrences.

    English word-like terms match on word boundaries and accept plural
    inflections (``agents``, ``registries``); other terms match as
    case-insensitive substrings.

    Args:
        text: Text to search.
        term: The term to find.
        english_inflections: Whether to accept English plural forms.

    Returns:
        Ascending match offsets.
    """
    if term == "":
        return []
    escaped = _REGEX_ESCAPE.sub(r"\\\g<0>", term)
    word_like = _WORD_LIKE.match(term) is not None
    if english_inflections and word_like:
        inflected = (
            f"{escaped[:-1]}(?:y|ies)" if _CONSONANT_Y.search(term) else f"{escaped}(?:s|es)?"
        )
    else:
        inflected = escaped
    pattern = f"(?<![A-Za-z0-9_]){inflected}(?![A-Za-z0-9_])" if word_like else inflected
    return [match.start() for match in re.finditer(pattern, text, re.IGNORECASE)]


_CJK = re.compile("[一-鿿]")


def _row_occurs(row: TerminologyRow, direction: BriefDirection, text: str) -> bool:
    terms = (
        [row.english]
        if direction == "en-to-zh"
        else [term for term in (row.first, row.chinese) if _CJK.search(term)]
    )
    return any(term_offsets(text, term, direction == "en-to-zh") for term in terms)


def relevant_terminology_rows(
    terminology: str, direction: BriefDirection, changed_text: str
) -> list[TerminologyRow]:
    """Select the terminology rows the changed text touches.

    A row matches when its source-language term occurs in the changed text
    (old and new states combined).

    Args:
        terminology: Full ``docs/i18n/terminology.md`` contents.
        direction: Update direction; decides which columns to match.
        changed_text: Concatenated old and new text of the changed spans.

    Returns:
        Matched rows in table order.
    """
    return [
        row
        for row in parse_terminology_rows(terminology)
        if _row_occurs(row, direction, changed_text)
    ]


def _line_at_offset(text: str, offset: int) -> int:
    return len(text[:offset].split("\n"))


def _span_index_at_offset(text: str, spans: list[MarkdownSpan], offset: int | None) -> int | None:
    if offset is None:
        return None
    line = _line_at_offset(text, offset)
    return next((span.index for span in spans if span.start_line <= line <= span.end_line), None)


@dataclass(frozen=True)
class FirstOccurrenceContext:
    """First-occurrence guidance computed for a Chinese-target update."""

    #: Human-readable notes for the briefing.
    notes: list[str]
    #: Unchanged span indices that must join the briefing because a first
    #: occurrence moved into or out of them.
    extra_span_indices: list[int]


def _first_or_none(offsets: list[int]) -> int | None:
    return offsets[0] if offsets else None


def first_occurrence_context(
    confirmed_source: str,
    current_source: str,
    confirmed_spans: list[MarkdownSpan],
    current_spans: list[MarkdownSpan],
    *,
    rows: list[TerminologyRow],
    changed: set[int],
) -> FirstOccurrenceContext:
    """Track document-wide first occurrences of the relevant English terms.

    The 首次出现 rendering attaches to a term's first occurrence, so when an
    edit moves that occurrence across spans, both the old and new spans need
    counterpart edits even when only one of them changed.

    Args:
        confirmed_source: Last-confirmed English text.
        current_source: Current English text.
        confirmed_spans: Spans of the last-confirmed English text.
        current_spans: Spans of the current English text, aligned with
            ``confirmed_spans``.
        rows: The relevant terminology rows.
        changed: Span indices already in the briefing.

    Returns:
        Notes and extra span indices to include.
    """
    notes: list[str] = []
    extra: set[int] = set()
    for row in rows:
        if row.first == "":
            continue
        old_index = _span_index_at_offset(
            confirmed_source,
            confirmed_spans,
            _first_or_none(term_offsets(confirmed_source, row.english, True)),
        )
        new_index = _span_index_at_offset(
            current_source,
            current_spans,
            _first_or_none(term_offsets(current_source, row.english, True)),
        )
        if old_index == new_index:
            continue
        for index in (old_index, new_index):
            if index is not None and index not in changed:
                extra.add(index)
        old_text = "absent" if old_index is None else f"#{old_index}"
        new_text = "absent" if new_index is None else f"#{new_index}"
        notes.append(
            f"{row.english}: the document-wide first occurrence moved from {old_text} "
            f"to {new_text}; the {row.first} form moves with it (later occurrences "
            "drop the annotation)."
        )
    return FirstOccurrenceContext(notes=notes, extra_span_indices=sorted(extra))


_FENCE_RUN = {"`": re.compile(r"^\s*(`{3,})"), "~": re.compile(r"^\s*(~{3,})")}


def _fence_for(body: str, mark: str) -> str:
    """Smallest fence of ``mark`` characters that safely wraps ``body``."""
    longest = 2
    for line in body.split("\n"):
        run = _FENCE_RUN[mark].match(line)
        if run is not None and len(run.group(1)) > longest:
            longest = len(run.group(1))
    return mark * (longest + 1)


@dataclass(frozen=True)
class BriefBundle:
    """One changed (or first-occurrence) span with its three-way context."""

    #: Span index shared by the aligned documents.
    index: int
    #: Human label: heading text or node type.
    label: str
    #: Why the bundle is present when its source text did not change.
    reason: str | None = None
    confirmed_source_text: str = ""
    current_source_text: str = ""
    counterpart_text: str = ""
    #: 1-based line the counterpart span starts on.
    counterpart_start_line: int = 0


@dataclass(frozen=True)
class UnitsScope:
    """A mapped change at unit or section granularity."""

    kind: Literal["units", "sections"]
    bundles: list[BriefBundle]
    first_occurrence_notes: list[str]


@dataclass(frozen=True)
class DocumentScope:
    """A change that cannot be mapped below the whole document."""

    reason: str


@dataclass(frozen=True)
class MechanicalScope:
    """A change confined to fenced code blocks."""


BriefScope = MechanicalScope | UnitsScope | DocumentScope


@dataclass(frozen=True)
class TranslationBriefInput:
    """Inputs for rendering one pair's briefing."""

    #: Repository-relative path of the side that changed.
    source_path: str
    #: Repository-relative path of the counterpart to update.
    counterpart_path: str
    direction: BriefDirection
    #: Unified diff of the changed side, last-confirmed to current.
    diff: str
    scope: BriefScope
    terminology: list[TerminologyRow]


_ZH_TARGET_DIGEST = [
    "- Edit ONLY what the change requires; preserve the reviewed phrasing of everything unchanged.",
    "- Nothing added, nothing dropped: the Chinese must state exactly what the new English states.",
    "- Write natural institutional technical Chinese, not word-by-word gloss; terse stays terse.",
    (
        "- Code fences byte-identical to the English side, comments included; inline "
        "code spans verbatim."
    ),
    (
        "- Repository-relative document links keep the same semantic target and exact "
        "query/fragment; targets in the active bilingual corpus use `.zh.md` for Chinese, "
        "a missing in-scope counterpart is an error, and targets outside the corpus keep "
        "the authored path. The switcher remains the cross-locale exception."
    ),
    (
        "- Structure mirrors the counterpart: heading depths and order, list kinds and "
        "item counts, table rows and columns."
    ),
    (
        "- 首次出现 annotations attach to the document-wide first occurrence only; later "
        "occurrences use the bare form, and an empty 首次出现 cell means never gloss."
    ),
    (
        "- Typography: one half-width space between Chinese and Latin or digits; "
        "full-width punctuation in Chinese prose; 顿号 for enumerations; second "
        "person is 你."
    ),
    "- One physical line per paragraph; exactly one trailing newline.",
]

_EN_TARGET_DIGEST = [
    "- Edit ONLY what the change requires; preserve the reviewed phrasing of everything unchanged.",
    "- Nothing added, nothing dropped: the English must state exactly what the new Chinese states.",
    "- Write concise professional developer prose, not word-by-word gloss; terse stays terse.",
    (
        "- Code fences byte-identical to the Chinese side, comments included; inline "
        "code spans verbatim."
    ),
    (
        "- Repository-relative document links keep the same semantic target and exact "
        "query/fragment; targets in the active bilingual corpus use `.md` for English, "
        "a missing in-scope counterpart is an error, and targets outside the corpus keep "
        "the authored path. The switcher remains the cross-locale exception."
    ),
    (
        "- Structure mirrors the counterpart: heading depths and order, list kinds and "
        "item counts, table rows and columns."
    ),
    "- One physical line per paragraph; exactly one trailing newline.",
]


def _render_bundles(
    out: list[str],
    source_language: str,
    counterpart_language: str,
    *,
    counterpart_path: str,
    bundles: list[BriefBundle],
    first_occurrence_notes: list[str],
) -> None:
    for bundle in bundles:
        suffix = (
            " — unchanged; included for a first-occurrence move"
            if bundle.reason == "first-occurrence"
            else ""
        )
        out.append("")
        out.append(
            f"### #{bundle.index} {bundle.label}{suffix} "
            f"— counterpart at {counterpart_path}:{bundle.counterpart_start_line}"
        )
        fence = _fence_for(
            f"{bundle.confirmed_source_text}\n{bundle.current_source_text}"
            f"\n{bundle.counterpart_text}",
            "~",
        )
        if bundle.confirmed_source_text != bundle.current_source_text:
            out.extend(
                [
                    "",
                    f"Last-confirmed {source_language}:",
                    "",
                    f"{fence}markdown",
                    bundle.confirmed_source_text.rstrip(),
                    fence,
                ]
            )
        out.extend(
            [
                "",
                f"Current {source_language}:",
                "",
                f"{fence}markdown",
                bundle.current_source_text.rstrip(),
                fence,
                "",
                f"Current {counterpart_language} (bring this along):",
                "",
                f"{fence}markdown",
                bundle.counterpart_text.rstrip(),
                fence,
            ]
        )
    if first_occurrence_notes:
        out.extend(["", "## First-occurrence notes", ""])
        out.extend(f"- {note}" for note in first_occurrence_notes)


def render_translation_brief(brief_input: TranslationBriefInput) -> str:
    """Render the complete briefing for one out-of-sync pair.

    Args:
        brief_input: Diff, mapped scope, terminology, and pair identity.

    Returns:
        Markdown briefing text.
    """
    source_language = "English" if brief_input.direction == "en-to-zh" else "Chinese"
    counterpart_language = "Chinese" if brief_input.direction == "en-to-zh" else "English"
    anchor = re.sub(r"\.zh\.md$", ".md", brief_input.source_path)
    out: list[str] = [
        f"# Translation update briefing: {brief_input.source_path}",
        "",
        (
            f"The {source_language} side changed; bring `{brief_input.counterpart_path}` "
            "along with the smallest edit that covers the change."
        ),
    ]
    if isinstance(brief_input.scope, MechanicalScope):
        out.extend(
            [
                "",
                "## Mechanical update — no translation judgment involved",
                "",
                (
                    "Every change since the last confirmed state is inside fenced code "
                    "blocks, which are byte-identical across the pair. Run "
                    f"`uv run hdsh pairing brief --apply {brief_input.source_path}` to "
                    "splice the updated fences into the counterpart (the result is "
                    "structure-validated before writing), then record per the Finish steps."
                ),
            ]
        )
    out.extend(["", f"## {source_language} diff (last-confirmed → current)", ""])
    diff_fence = _fence_for(brief_input.diff, "`")
    out.extend([f"{diff_fence}diff", brief_input.diff.rstrip(), diff_fence])
    if isinstance(brief_input.scope, UnitsScope):
        title = (
            (
                f"## Changed units (last-confirmed {source_language} → current "
                f"{source_language}, with the current {counterpart_language})"
            )
            if brief_input.scope.kind == "units"
            else (
                "## Changed sections (fine-grained units do not align across the pair; "
                "whole heading sections shown)"
            )
        )
        out.extend(["", title])
        _render_bundles(
            out,
            source_language,
            counterpart_language,
            counterpart_path=brief_input.counterpart_path,
            bundles=brief_input.scope.bundles,
            first_occurrence_notes=brief_input.scope.first_occurrence_notes,
        )
    elif isinstance(brief_input.scope, DocumentScope):
        out.extend(
            [
                "",
                "## Whole-document update required",
                "",
                (
                    f"{brief_input.scope.reason} Open `{brief_input.counterpart_path}` "
                    "directly, locate the affected regions yourself, and reconcile under "
                    "docs/i18n/translation-rules.md."
                ),
            ]
        )
    if brief_input.terminology:
        out.extend(
            [
                "",
                "## Binding terminology rows matching this change (docs/i18n/terminology.md)",
                "",
                "| English | 中文 | 首次出现 | 不要译作 | 备注 |",
                "|---|---|---|---|---|",
            ]
        )
        out.extend(row.line for row in brief_input.terminology)
        out.extend(
            [
                "",
                (
                    "For any term you introduce that is not listed above, consult the full "
                    "table before inventing a rendering."
                ),
            ]
        )
    out.extend(
        [
            "",
            "## Rules digest (full rules: docs/i18n/translation-rules.md)",
            "",
            *(_ZH_TARGET_DIGEST if brief_input.direction == "en-to-zh" else _EN_TARGET_DIGEST),
            "",
            "## Finish",
            "",
            (
                "1. Apply the smallest counterpart edit that covers the change, then verify "
                "the changed spans clause by clause against the source."
            ),
            f"2. `uv run hdsh pairing record {anchor}`",
            f"3. `uv run hdsh pairing verify {anchor}`",
            "",
        ]
    )
    return "\n".join(out)


@dataclass(frozen=True)
class _PairState:
    """One pair's recorded and current state."""

    anchor: str
    source_drifted: bool
    zh_drifted: bool
    source_last: str
    zh_last: str


@dataclass(frozen=True)
class _PlannedBrief:
    """The mapped scope for one drifted side plus its derived context."""

    scope: BriefScope
    #: Old + new text of the changed spans, for terminology matching.
    changed_text: str
    #: Computed counterpart for a mechanical scope, for ``--apply``.
    mechanical_result: str | None = None


def _read_pair_file(root: str, path: str) -> str | None:
    file = Path(root, path)
    return file.read_text(encoding="utf-8") if file.is_file() else None


def _blob_text(root: str, object_id: str) -> str:
    return run_git(
        root, ["cat-file", "-p", object_id], f"reading recorded blob {object_id}"
    ).decode("utf-8")


def _diff_texts(root: str, before: str, after: str) -> str:
    """Unified diff between two texts, headers stripped, via ``git diff --no-index``."""
    with tempfile.TemporaryDirectory(prefix="hdsh-pairing-brief-") as temporary:
        before_path = Path(temporary, "last-confirmed.md")
        after_path = Path(temporary, "current.md")
        before_path.write_text(before, encoding="utf-8")
        after_path.write_text(after, encoding="utf-8")
        result = subprocess.run(
            [
                "git",
                "-C",
                root,
                "diff",
                "--no-index",
                "--unified=2",
                str(before_path),
                str(after_path),
            ],
            capture_output=True,
            check=False,
        )
    # ``git diff --no-index`` exits 1 on differences; anything else is a
    # failure, and an empty diff must never masquerade as "nothing changed".
    if result.returncode not in (0, 1):
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        msg = (
            f"git diff --no-index for the changed side failed with status "
            f"{result.returncode}: {detail}"
        )
        raise GitError(msg)
    return "\n".join(
        line
        for line in result.stdout.decode("utf-8").split("\n")
        if not line.startswith(("diff --git", "index ", "--- ", "+++ "))
    ).strip()


def _load_pair(root: str, anchor: str, excluded: ExclusionPredicate) -> _PairState | str:
    """Load one pair's recorded and current state, or explain the problem.

    Args:
        root: Absolute repository root.
        anchor: English anchor path.
        excluded: Manifest exclusion predicate.

    Returns:
        The pair state, or a human-readable problem message.
    """
    paths = pair_paths(anchor)
    if not is_scope_file(anchor) or excluded(anchor):
        return f"{anchor}: not an in-scope documentation pair (docs/i18n/README.md)"
    missing = [
        file for file in (paths.source, paths.zh, paths.meta) if not Path(root, file).is_file()
    ]
    if missing:
        return (
            f"{anchor}: incomplete pair (missing {', '.join(missing)}) — a new counterpart "
            "is whole-document translation work, not a minimal update"
        )
    record = parse_record(Path(root, paths.meta).read_text(encoding="utf-8"), paths)
    if record is None:
        return f"{paths.meta}: malformed consistency record"
    source_current = Path(root, paths.source).read_text(encoding="utf-8")
    zh_current = Path(root, paths.zh).read_text(encoding="utf-8")
    source_last = _blob_text(root, record.source_hash)
    zh_last = _blob_text(root, record.zh_hash)
    return _PairState(
        anchor=anchor,
        source_drifted=source_current != source_last,
        zh_drifted=zh_current != zh_last,
        source_last=source_last,
        zh_last=zh_last,
    )


def _bundles_for(
    indices: list[int],
    extra_indices: list[int],
    confirmed: list[MarkdownSpan],
    current: list[MarkdownSpan],
    counterpart: list[MarkdownSpan],
) -> list[BriefBundle]:
    """Assemble bundles for the given changed plus first-occurrence indices."""
    extras = set(extra_indices)
    return [
        BriefBundle(
            index=index,
            label=current[index].label,
            reason=(
                "first-occurrence"
                if index in extras and confirmed[index].text == current[index].text
                else None
            ),
            confirmed_source_text=confirmed[index].text,
            current_source_text=current[index].text,
            counterpart_text=counterpart[index].text,
            counterpart_start_line=counterpart[index].start_line,
        )
        for index in sorted(set(indices) | extras)
    ]


#: The granularities a briefing can map the change at, narrowest first.
_GRANULARITY: tuple[
    tuple[Literal["units", "sections"], Callable[[str], list[MarkdownSpan]]], ...
] = (("units", markdown_units), ("sections", section_spans))


def _plan_scope(
    terminology: str,
    source_last: str,
    source_current: str,
    counterpart_current: str,
    *,
    direction: BriefDirection,
    both_drifted: bool,
) -> _PlannedBrief:
    """Choose the narrowest safely mapped granularity for one drifted side."""
    whole_changed_text = f"{source_last}\n{source_current}"
    if both_drifted:
        return _PlannedBrief(
            scope=DocumentScope(
                reason="BOTH sides changed since the pair was last confirmed consistent, "
                "so no side is a trustworthy mapping anchor; decide which side owns each "
                "divergence."
            ),
            changed_text=whole_changed_text,
        )
    mechanical = compute_mechanical_update(source_last, source_current, counterpart_current)
    if mechanical is not None:
        return _PlannedBrief(
            scope=MechanicalScope(), changed_text=whole_changed_text, mechanical_result=mechanical
        )
    for kind, spans_of in _GRANULARITY:
        confirmed = spans_of(source_last)
        current = spans_of(source_current)
        counterpart = spans_of(counterpart_current)
        if not spans_aligned(confirmed, current) or not spans_aligned(confirmed, counterpart):
            continue
        changed = changed_span_indices(confirmed, current)
        if not changed:
            continue
        changed_text = "\n".join(
            f"{confirmed[index].text}\n{current[index].text}" for index in changed
        )
        rows = relevant_terminology_rows(terminology, direction, changed_text)
        occurrence = (
            first_occurrence_context(
                source_last, source_current, confirmed, current, rows=rows, changed=set(changed)
            )
            if direction == "en-to-zh"
            else FirstOccurrenceContext(notes=[], extra_span_indices=[])
        )
        return _PlannedBrief(
            scope=UnitsScope(
                kind=kind,
                bundles=_bundles_for(
                    changed, occurrence.extra_span_indices, confirmed, current, counterpart
                ),
                first_occurrence_notes=occurrence.notes,
            ),
            changed_text=changed_text,
        )
    return _PlannedBrief(
        scope=DocumentScope(
            reason="Neither fine-grained units nor heading sections align one to one across "
            "the last-confirmed source, current source, and current counterpart."
        ),
        changed_text=whole_changed_text,
    )


def _apply_mechanical(
    root: str,
    is_pair_source: PairSourcePredicate,
    counterpart_path: str,
    source_current: str,
    result: str,
    *,
    public_blob_root: str,
    stderr: LineSink,
) -> None:
    """Validate a computed mechanical counterpart and write it.

    Args:
        root: Absolute repository root.
        is_pair_source: Active bilingual-source predicate.
        counterpart_path: Repository-relative counterpart path to rewrite.
        source_current: Current text of the changed source side.
        result: Computed counterpart text.
        public_blob_root: Manifest-configured absolute-URL prefix accepted
            before switcher counterparts.
        stderr: Receipt sink for the applied-splice confirmation.

    Raises:
        ValueError: When the computed result violates the pair structure.
    """
    if counterpart_path.endswith(".zh.md"):
        source_path = f"{counterpart_path[: -len('.zh.md')]}.md"
    else:
        source_path = f"{counterpart_path[: -len('.md')]}.zh.md"

    def context_for(path: str, markdown: str) -> pairing_links.LinkContext:
        return pairing_links.LinkContext(
            repo_root=root,
            source_path=path,
            is_pair_source=is_pair_source,
            repository_file_exists=lambda candidate: Path(root, candidate).is_file(),
            markdown=markdown,
        )

    # Each side's accepted switcher targets name its counterpart's basename.
    errors = pairing_structure.structure_diff(
        pairing_structure.structure_signature(
            parse_markdown(source_current),
            pairing_links.language_switcher_targets(counterpart_path, public_blob_root),
            context_for(source_path, source_current),
        ),
        pairing_structure.structure_signature(
            parse_markdown(result),
            pairing_links.language_switcher_targets(source_path, public_blob_root),
            context_for(counterpart_path, result),
        ),
    )
    if errors:
        message = (
            f"{TOOL}: computed mechanical update for {counterpart_path} violates the pair "
            f"structure: {'; '.join(errors)}"
        )
        raise ValueError(message)
    Path(root, counterpart_path).write_text(result, encoding="utf-8")
    stderr(
        f"{TOOL}: applied code-fence splice to {counterpart_path}; "
        "review the diff, then record the pair."
    )


def _brief_direction(
    root: str,
    terminology: str,
    is_pair_source: PairSourcePredicate,
    state: _PairState,
    *,
    direction: BriefDirection,
    apply: bool,
    public_blob_root: str,
    stderr: LineSink,
) -> str:
    """Render (and under ``apply``, apply) the briefing for one drifted side."""
    source_is_english = direction == "en-to-zh"
    paths = pair_paths(state.anchor)
    source_path = paths.source if source_is_english else paths.zh
    counterpart_path = paths.zh if source_is_english else paths.source
    source_last = state.source_last if source_is_english else state.zh_last
    source_current = _read_pair_file(root, source_path)
    counterpart_current = _read_pair_file(root, counterpart_path)
    if source_current is None:
        msg = f"{TOOL}: {source_path} was removed after the pair was loaded"
        raise ValueError(msg)
    if counterpart_current is None:
        msg = f"{TOOL}: {counterpart_path} was removed after the pair was loaded"
        raise ValueError(msg)
    diff = _diff_texts(root, source_last, source_current)
    planned = _plan_scope(
        terminology,
        source_last,
        source_current,
        counterpart_current,
        direction=direction,
        both_drifted=state.source_drifted and state.zh_drifted,
    )
    if apply and planned.mechanical_result is not None:
        _apply_mechanical(
            root,
            is_pair_source,
            counterpart_path,
            source_current,
            planned.mechanical_result,
            public_blob_root=public_blob_root,
            stderr=stderr,
        )
    return render_translation_brief(
        TranslationBriefInput(
            source_path=source_path,
            counterpart_path=counterpart_path,
            direction=direction,
            diff=diff,
            scope=planned.scope,
            terminology=relevant_terminology_rows(terminology, direction, planned.changed_text),
        )
    )


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``brief`` command leaf."""
    parser = subparsers.add_parser("brief", help="minimal-update briefing for out-of-sync pairs")
    parser.add_argument(
        "--apply", action="store_true", help="write the computed code-fence-only update"
    )
    parser.add_argument(
        "anchors", nargs="*", metavar="<pair>", help="any file of each pair to brief"
    )
    parser.set_defaults(handler=main)


def _run(
    root: str,
    requested: list[str],
    *,
    apply: bool = False,
    stdout: LineSink = print,
    stderr: LineSink = print,
) -> int:
    """Execute one brief request against a repository root.

    Args:
        root: Absolute repository root.
        requested: Pair arguments as passed on the command line.
        apply: Write computed code-fence-only counterparts.
        stdout: Briefing-text sink.
        stderr: Problem-line sink.

    Returns:
        The process exit code: 0 briefed or nothing to do, 2 usage or
        repository error.
    """
    manifest_content = _read_pair_file(root, MANIFEST_PATH)
    if manifest_content is None:
        stderr(f"{TOOL}: {MANIFEST_PATH} is missing from the repository root")
        return 2
    try:
        manifest = parse_manifest(manifest_content)
    except (TypeError, ValueError) as error:
        stderr(f"{TOOL}: {error}")
        return 2

    terminology = _read_pair_file(root, TERMINOLOGY_PATH)
    if terminology is None:
        stderr(f"{TOOL}: {TERMINOLOGY_PATH} is missing from the repository root")
        return 2

    def excluded(file: str) -> bool:
        return manifest_excluded(file, manifest)

    def is_pair_source(path: str) -> bool:
        return is_scope_file(path) and not excluded(path)

    if requested:
        selected = sorted({anchor_of_argument(argument) for argument in requested})
    else:
        repository = PairingRepository(root)
        selected = sorted(
            path[: -len(".i18n.yaml")] + ".md"
            for path in repository.discover_scope_files()
            if path.endswith(".i18n.yaml")
        )

    briefs: list[str] = []
    problems: list[str] = []
    skipped: list[str] = []
    for anchor in selected:
        loaded = _load_pair(root, anchor, excluded)
        if isinstance(loaded, str):
            if requested:
                problems.append(loaded)
            continue
        if not loaded.source_drifted and not loaded.zh_drifted:
            if requested:
                skipped.append(f"{anchor}: pair is consistent with its record — nothing to brief")
            continue
        if loaded.source_drifted:
            briefs.append(
                _brief_direction(
                    root,
                    terminology,
                    is_pair_source,
                    loaded,
                    direction="en-to-zh",
                    apply=apply,
                    public_blob_root=manifest.public_blob_root,
                    stderr=stderr,
                )
            )
        if loaded.zh_drifted:
            briefs.append(
                _brief_direction(
                    root,
                    terminology,
                    is_pair_source,
                    loaded,
                    direction="zh-to-en",
                    apply=apply,
                    public_blob_root=manifest.public_blob_root,
                    stderr=stderr,
                )
            )

    if problems or skipped:
        for message in [*problems, *skipped]:
            stderr(f"{TOOL}: {message}")
        return 2
    if not briefs:
        stdout(f"{TOOL}: every recorded pair matches its consistency record; nothing to brief.")
        return 0
    stdout("\n\n---\n\n".join(briefs))
    return 0


def main(args: argparse.Namespace) -> int:
    """``hdsh pairing brief`` entry point.

    Args:
        args: Parsed leaf namespace with ``apply`` and ``anchors``.

    Returns:
        The exit code: 0 briefed, 2 usage or repository error.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, check=False
        )
    except OSError as error:
        print(f"{TOOL}: cannot locate repository root: {error}", file=sys.stderr)
        return 2
    if completed.returncode != 0:
        print(f"{TOOL}: working directory is inside no Git repository", file=sys.stderr)
        return 2
    root = completed.stdout.decode("utf-8").strip()
    try:
        return _run(root, list(args.anchors), apply=args.apply)
    except (ValueError, GitError) as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 2
