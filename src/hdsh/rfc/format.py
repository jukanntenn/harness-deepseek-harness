"""Enforce the RFC file format under ``.agents/rfcs/``.

The contract lives in ``.agents/rfcs/README.md``: a three-line header block
followed by a blank line, a ``Status:`` line consistent with the lifecycle
folder, the required section skeleton per lifecycle, and the mandatory
``## Alternatives considered`` section. Format tokens inside fenced code
blocks are content, not structure. ``.zh.md`` counterparts are skipped by
this gate; the pairing gate owns their structural consistency, and the
sealed ``archived/`` tree is owned by the archive gate.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from hdsh.rfc.tree import NOTES_ROOT, walk_notes

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh rfc"

STATUS_LINE = re.compile(r"^Status: (proposed|implemented|rejected — .+)$")
TITLE_LINE = re.compile(r"^# RFC: \S")
SECTION = re.compile(r"^## (.*)$")
#: Proposal-era heading prefixes banned from implemented records: a word
#: prefix at any case, so ``## Proposal sketch`` is rejected as well.
SPEC_LANGUAGE_SECTION = re.compile(
    r"^(Proposal|Plan|Migration plan|Acceptance criteria)\b", re.IGNORECASE
)

#: Sections required per lifecycle folder, beyond the universal ``## Problem``
#: opener; a rejected record is its proposal frozen, so only the core applies.
REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "proposed": ("Proposal", "Acceptance criteria", "Risks"),
    "implemented": ("Decision", "Consequences"),
    "rejected": ("Proposal",),
}

_STATUS_MARKER = "Status:"
_STATUS_PREFIX = "Status: "
_HEADER_LINE_COUNT = 3


def _prose_lines(lines: list[str]) -> list[str]:
    """Drop fenced code blocks: format tokens inside fences are not structure."""
    prose: list[str] = []
    in_fence = False
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            prose.append(line)
    return prose


def _status_folder(status: str) -> str:
    """Map one ``Status:`` value to the lifecycle folder it must live in.

    Args:
        status: The status text without the ``Status: `` prefix.

    Returns:
        ``proposed``, ``implemented``, or ``rejected``.
    """
    if status == "implemented":
        return "implemented"
    return "rejected" if status.startswith("rejected") else "proposed"


def validate_note(path: Path, root: Path) -> list[str]:
    """Validate one walked RFC against the format contract.

    Args:
        path: Absolute RFC path placed by :func:`hdsh.rfc.tree.walk_notes`.
        root: Repository root path.

    Returns:
        Violations; an empty list means the RFC is well formed.
    """
    relative = str(path.relative_to(root))
    errors: list[str] = []
    lifecycle = path.relative_to(root / NOTES_ROOT).parts[0]

    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if (
        len(lines) < _HEADER_LINE_COUNT
        or TITLE_LINE.match(lines[0]) is None
        or lines[1] != ""
        or STATUS_LINE.match(lines[2]) is None
    ):
        errors.append(
            f"{relative}: the first three lines must be `# RFC: <title>`, blank, "
            "and `Status: proposed|implemented|rejected — <why>`"
        )
        return errors
    status = lines[2][len(_STATUS_PREFIX) :]
    if len(lines) <= _HEADER_LINE_COUNT or lines[_HEADER_LINE_COUNT] != "":
        errors.append(f"{relative}: line 4 must be blank")

    prose = _prose_lines(lines)
    if (
        any(line.startswith(_STATUS_MARKER) and line != lines[2] for line in prose)
        or sum(line == lines[2] for line in prose) > 1
    ):
        errors.append(f"{relative}: the line-3 `Status:` line must be the only one in the file")

    sections = [
        match.group(1).rstrip() for line in prose if (match := SECTION.match(line)) is not None
    ]
    if not sections or sections[0] != "Problem":
        got = f"`## {sections[0]}`" if sections else "<none>"
        errors.append(f"{relative}: the first section must be `## Problem` (got {got})")
    errors.extend(
        f"{relative}: `## {required}` section is required"
        for required in REQUIRED_SECTIONS[lifecycle]
        if required not in sections
    )
    if lifecycle == "implemented":
        errors.extend(
            f"{relative}: `## {section}` is a proposal-era heading; an implemented "
            "RFC states what is (fold it into Decision/Consequences/Testing)"
            for section in sections
            if SPEC_LANGUAGE_SECTION.match(section)
        )
    if "Alternatives considered" not in sections:
        errors.append(f"{relative}: `## Alternatives considered` is required")

    if _status_folder(status) != lifecycle:
        errors.append(f"{relative}: Status {status!r} does not match the {lifecycle}/ folder")
    if not text.endswith("\n") or text.endswith("\n\n"):
        errors.append(f"{relative}: files end with exactly one trailing newline")
    return errors


def run(root: Path) -> int:
    """Validate every walked RFC and print violations.

    Args:
        root: Repository root path.

    Returns:
        The exit code: 0 green, 1 violations found.
    """
    notes, errors = walk_notes(root)
    for note in notes:
        errors.extend(validate_note(note, root))
    # The loop form above reads as the discovery contract; extend-per-note is
    # intentional, so the PERF401 comprehension rewrite is not applied here.
    if not errors:
        print(f"{TOOL}: all RFCs well formed")
        return 0
    print(f"{TOOL}: format violations (see .agents/rfcs/README.md):")
    for error in errors:
        print(f"  {error}")
    return 1


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``verify`` command leaf."""
    parser = subparsers.add_parser("verify", help="RFC format gate")
    parser.set_defaults(handler=main)


def main(_args: argparse.Namespace) -> int:
    """``hdsh rfc verify`` entry point."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        )
    except OSError as error:
        print(f"{TOOL}: cannot locate repository root: {error}", file=sys.stderr)
        return 2
    if completed.returncode != 0:
        print(f"{TOOL}: working directory is inside no Git repository", file=sys.stderr)
        return 2
    return run(Path(completed.stdout.strip()))
