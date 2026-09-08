"""Enforce ``wc -w``-style word ceilings for standing documents.

Ceilings live in the ``docBudgets`` section of ``.hdsh/docs.manifest.json``
and are validated at load: a missing or invalid manifest fails the gate
rather than blessing an unbudgeted corpus. Only listed standing docs are
budgeted; a budgeted file that is missing fails so a rename cannot silently
orphan its budget. ``--list`` reports current usage. Ceilings ratchet down
with headroom; raising one requires justification in the PR.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from hdsh.docs.config import (
    DocsConfigError,
    load_docs_manifest,
    missing_section_error,
)
from hdsh.docs.corpus import find_repository_root

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh docs budgets"


def count_words(text: str) -> int:
    """Count whitespace-delimited tokens, matching ``wc -w``."""
    return len(text.split())


def _render(root: Path, budgets: dict[str, int]) -> tuple[list[str], list[str]]:
    """Produce the report rows and failure lines for one budget manifest."""
    rows: list[str] = []
    failures: list[str] = []
    for path, ceiling in budgets.items():
        absolute = root / path
        if not absolute.is_file():
            rows.append(f"MISS  {'—':>6} / {ceiling!s:<6} {path}")
            failures.append(
                f"{path}: budgeted file does not exist "
                "(renamed or deleted? update .hdsh/docs.manifest.json in the same change)"
            )
            continue
        words = count_words(absolute.read_text(encoding="utf-8"))
        status = "ok  " if words <= ceiling else "OVER"
        rows.append(f"{status}  {words:6d} / {ceiling!s:<6} {path}")
        if words > ceiling:
            failures.append(
                f"{path}: {words} words exceeds the {ceiling}-word ceiling — relocate or "
                "condense per docs/AGENTS.md (raising a ceiling requires justification in the PR)"
            )
    return rows, failures


def run(root: Path, *, list_only: bool = False) -> int:
    """Check every budgeted document against its word ceiling.

    Args:
        root: Absolute repository root.
        list_only: Report current usage and never fail.

    Returns:
        The exit code: 0 green, 1 violations found.
    """
    manifest = load_docs_manifest(root)
    if manifest.doc_budgets is None:
        raise missing_section_error("docBudgets", TOOL)
    rows, failures = _render(root, manifest.doc_budgets)
    if list_only:
        print("\n".join(rows))
        return 0
    if failures:
        print(
            f"{TOOL}: budget violations (relocate or condense; see docs/AGENTS.md):",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(f"{TOOL}: {len(manifest.doc_budgets)} budgeted docs within ceiling.")
    return 0


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``budgets`` command leaf."""
    parser = subparsers.add_parser("budgets", help="word ceilings for standing docs")
    parser.add_argument("--list", action="store_true", help="report current usage and never fail")
    parser.set_defaults(handler=main)


def main(args: argparse.Namespace) -> int:
    """``hdsh docs budgets`` entry point."""
    root = find_repository_root(TOOL)
    try:
        return run(root, list_only=args.list)
    except DocsConfigError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 2
