"""Enforce one physical line per prose paragraph.

The writing rule is owned by ``docs/AGENTS.md``; this gate makes it
mechanical. Each in-scope Markdown file is parsed and any paragraph node —
including paragraphs inside lists and blockquotes — spanning more than one
source line is reported. The gate never rewrites; VitePress frontmatter and
custom-container delimiters are masked before parsing.
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
from hdsh.docs.corpus import discover_corpus_files, find_repository_root
from hdsh.docs.markdown import hard_wrapped_paragraphs

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh docs wrap"

_SNIPPET_LIMIT = 80


def run(root: Path) -> int:
    """Check the configured Markdown corpus for hard-wrapped prose paragraphs.

    Args:
        root: Absolute repository root.

    Returns:
        The exit code: 0 green, 1 violations found.
    """
    manifest = load_docs_manifest(root)
    if manifest.markdown_wrap is None:
        raise missing_section_error("markdownWrap", TOOL)
    files = discover_corpus_files(root, manifest.markdown_wrap)
    violations: list[str] = []
    for file in files:
        source = file.abs_path.read_text(encoding="utf-8")
        for violation in hard_wrapped_paragraphs(source):
            snippet = violation.text[:_SNIPPET_LIMIT]
            if len(violation.text) > _SNIPPET_LIMIT:
                snippet += "…"
            violations.append(f"{file.path}:{violation.line}  {snippet}")
    if not violations:
        print(f"{TOOL}: {len(files)} file(s) checked, no hard-wrapped prose paragraphs.")
        return 0
    print(
        f"{TOOL}: hard-wrapped prose paragraphs found (write one physical line per paragraph):",
        file=sys.stderr,
    )
    for violation in violations:
        print(f"  {violation}", file=sys.stderr)
    return 1


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``wrap`` command leaf."""
    parser = subparsers.add_parser("wrap", help="one physical line per prose paragraph")
    parser.set_defaults(handler=main)


def main(_args: argparse.Namespace) -> int:
    """``hdsh docs wrap`` entry point."""
    root = find_repository_root(TOOL)
    try:
        return run(root)
    except DocsConfigError as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        return 2
