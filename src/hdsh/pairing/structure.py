"""Generated-region grammar and the structural signature compared across a pair.

Kept free of filesystem and Git access so corpus scoping and signature
behavior can be regression-tested without mutating a repository tree. This
module is the one home of the generated-region grammar and the structural
signature compared between the two sides of a pair.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from markdown_it.token import Token

import hdsh.pairing.links as pairing_links

#: Complete opening marker line: ``<!-- BEGIN GENERATED <slug> … -->``.
GENERATED_REGION_BEGIN_LINE = re.compile(r"^<!-- BEGIN GENERATED (\S+)(?: [^>]*)? -->$")
#: Complete closing marker line: ``<!-- END GENERATED <slug> -->``.
GENERATED_REGION_END_LINE = re.compile(r"^<!-- END GENERATED (\S+) -->$")
#: Loose marker detector: any line that looks like a region marker must parse.
GENERATED_REGION_MARKER_HINT = re.compile(r"^<!-- (?:BEGIN|END) GENERATED ")


@dataclass(frozen=True)
class GeneratedRegionPartition:
    """Generated regions of one document and the region-free remainder."""

    regions: list[str]
    stripped: str


def partition_generated_regions(content: str) -> GeneratedRegionPartition:
    """Extract every generated region (markers included) and the stripped remainder.

    Regions are line-delimited: a marker occupies its whole line, must be a
    complete well-formed marker, and the closing slug must match the opener.

    Args:
        content: Full Markdown document text.

    Returns:
        The regions in document order and the region-free remainder.

    Raises:
        ValueError: On an unopened END, unclosed BEGIN, nested BEGIN,
            malformed marker line, or a closing slug mismatch.
    """
    lines = content.split("\n")
    regions: list[str] = []
    kept: list[str] = []
    open_region: tuple[str, list[str]] | None = None
    for line in lines:
        begin = GENERATED_REGION_BEGIN_LINE.match(line)
        if begin:
            if open_region is not None:
                msg = "generated region BEGIN marker nested inside an open region"
                raise ValueError(msg)
            open_region = (begin.group(1), [line])
            continue
        end = GENERATED_REGION_END_LINE.match(line)
        if end:
            if open_region is None:
                msg = "generated region END marker without a BEGIN"
                raise ValueError(msg)
            slug, region_lines = open_region
            if end.group(1) != slug:
                msg = (
                    f"generated region END slug '{end.group(1)}' does not match "
                    f"its BEGIN slug '{slug}'"
                )
                raise ValueError(msg)
            region_lines.append(line)
            regions.append("\n".join(region_lines))
            open_region = None
            continue
        if GENERATED_REGION_MARKER_HINT.match(line):
            msg = f"malformed generated region marker line: {line!r}"
            raise ValueError(msg)
        if open_region is not None:
            open_region[1].append(line)
        else:
            kept.append(line)
    if open_region is not None:
        msg = "generated region BEGIN marker without an END"
        raise ValueError(msg)
    return GeneratedRegionPartition(regions=regions, stripped="\n".join(kept))


@dataclass(frozen=True)
class StructureSignature:
    """The structural signature compared between the two sides of a pair."""

    #: Heading depths in document order (h2 -> 2).
    headings: list[int] = field(default_factory=list)
    #: Fenced code blocks verbatim: info string plus content, in order.
    code: list[str] = field(default_factory=list)
    #: Row and column count of each table, in order.
    tables: list[str] = field(default_factory=list)
    #: Kind, ordered-list start, and direct item count of each list, in order.
    lists: list[str] = field(default_factory=list)
    #: Every link's semantic target in document order; the switcher is excluded.
    links: list[str] = field(default_factory=list)


#: Parser with the GFM table extension enabled, matching the gate's needs.
_PARSER = MarkdownIt("commonmark").enable("table")


def parse_markdown(content: str) -> list[Token]:
    """Parse Markdown with the pairing gate's extensions.

    Args:
        content: Complete document text.

    Returns:
        The flat token stream; block tokens carry ``map`` line ranges and
        inline tokens carry ``map`` plus the raw ``content`` of their chunk.
    """
    return _PARSER.parse(content)


class _ListNode:
    """One list's signature data plus its nested lists, for pre-order output."""

    ordered: bool
    start: int
    items: int
    children: list[_ListNode]

    def __init__(self, ordered: bool, start: int) -> None:
        self.ordered = ordered
        self.start = start
        self.items = 0
        self.children = []

    def render(self) -> str:
        """Render the signature entry for this list."""
        if self.ordered:
            return f"ordered:start={self.start}:items={self.items}"
        return f"bullet:items={self.items}"


class _SignatureCollector:
    """Single pass over one Markdown token stream collecting the pair signature."""

    context: pairing_links.LinkContext
    switcher_line: int | None
    signature: StructureSignature
    _table_rows: int
    _table_columns: int | None
    _row_cells: int
    _in_table: bool
    _in_row: bool
    _list_stack: list[_ListNode]
    _list_roots: list[_ListNode]

    def __init__(
        self,
        link_context: pairing_links.LinkContext,
        switcher_line: int | None,
    ) -> None:
        self.context = link_context
        self.switcher_line = switcher_line
        self.signature = StructureSignature()
        self._table_rows = 0
        self._table_columns = None
        self._row_cells = 0
        self._in_table = False
        self._in_row = False
        self._list_stack = []
        self._list_roots = []

    def visit(self, token: Token) -> None:
        """Add one token's structural contribution.

        Args:
            token: The current Markdown token.
        """
        kind = token.type
        if kind == "heading_open":
            self.signature.headings.append(int(token.tag[1]))
        elif kind in ("fence", "code_block"):
            # Deliberate format: the entry keeps the raw info string and the
            # token content with its trailing newline. Both sides of a pair
            # come from this implementation, so the signature bytes only need
            # internal stability — do not normalize this format.
            info = token.info.strip() if kind == "fence" else ""
            self.signature.code.append(f"```{info}\n{token.content}")
        elif kind == "table_open":
            self._in_table = True
            self._table_rows = 0
            self._table_columns = None
        elif kind == "tr_open" and self._in_table:
            self._table_rows += 1
            self._in_row = True
            self._row_cells = 0
        elif kind in ("th_open", "td_open") and self._in_row:
            self._row_cells += 1
        elif kind == "tr_close" and self._in_row:
            if self._table_columns is None:
                self._table_columns = self._row_cells
            self._in_row = False
        elif kind == "table_close" and self._in_table:
            self.signature.tables.append(f"{self._table_rows}x{self._table_columns or 0}")
            self._in_table = False
        elif kind in ("bullet_list_open", "ordered_list_open"):
            node = _ListNode(kind == "ordered_list_open", int(token.attrGet("start") or 1))
            if self._list_stack:
                self._list_stack[-1].children.append(node)
            else:
                self._list_roots.append(node)
            self._list_stack.append(node)
        elif kind == "list_item_open" and self._list_stack:
            self._list_stack[-1].items += 1
        elif kind in ("bullet_list_close", "ordered_list_close") and self._list_stack:
            self._list_stack.pop()

    def collect_links(self) -> None:
        """Append every document link's semantic target, skipping the switcher."""
        for link in pairing_links.document_links(self.context.markdown):
            if link.line == self.switcher_line:
                continue
            self.signature.links.append(
                pairing_links.semantic_link_target(link.href, link.authored, self.context)
            )

    def flatten_lists(self) -> None:
        """Emit list signature entries in document (pre-order) traversal."""
        stack = list(reversed(self._list_roots))
        while stack:
            node = stack.pop()
            self.signature.lists.append(node.render())
            stack.extend(reversed(node.children))


def structure_signature(
    tokens: list[Token],
    switcher_targets: Sequence[str],
    link_context: pairing_links.LinkContext,
) -> StructureSignature:
    """Collect the ordered structural signature, skipping the switcher link.

    Args:
        tokens: Parsed Markdown token stream of the document.
        switcher_targets: Accepted counterpart link targets for this side.
        link_context: Repository and source context for semantic link targets.

    Returns:
        The ordered signature.
    """
    collector = _SignatureCollector(
        link_context,
        pairing_links.language_switcher_line(link_context.markdown, list(switcher_targets)),
    )
    for token in tokens:
        collector.visit(token)
    collector.flatten_lists()
    collector.collect_links()
    return collector.signature


_SHOW_LIMIT = 72


def _show(value: str | int | None) -> str:
    # ``repr`` quoting is deliberate and pinned by tests — the diff wording is
    # behavior, its quote style is not.
    if value is None:
        return "nothing"
    text = repr(value)
    return f"{text[:_SHOW_LIMIT]}…" if len(text) > _SHOW_LIMIT else text


def structure_diff(source: StructureSignature, zh: StructureSignature) -> list[str]:
    """Return the first divergence for each structural field; empty means equal.

    Args:
        source: The English side's signature.
        zh: The Chinese side's signature.

    Returns:
        One human-readable divergence per differing field.
    """
    out: list[str] = []
    fields: list[tuple[str, list[str] | list[int], list[str] | list[int]]] = [
        ("heading (depth)", source.headings, zh.headings),
        ("code block", source.code, zh.code),
        ("table (row x column count)", source.tables, zh.tables),
        ("list (kind, start, item count)", source.lists, zh.lists),
        ("link target", source.links, zh.links),
    ]
    for field_name, source_values, zh_values in fields:
        for index in range(max(len(source_values), len(zh_values))):
            source_value: str | int | None = (
                source_values[index] if index < len(source_values) else None
            )
            zh_value: str | int | None = zh_values[index] if index < len(zh_values) else None
            if source_value != zh_value:
                out.append(
                    f"{field_name} #{index + 1} diverges between the pair: "
                    f"{_show(source_value)} vs {_show(zh_value)}"
                )
                break
    return out
