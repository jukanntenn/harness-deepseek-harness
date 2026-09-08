"""Command tree for the unified ``hdsh`` entry point.

This module owns the two-level ``hdsh <domain> <command>`` parser tree: it
registers every domain's leaf parsers and maps parser signals to the
process exit-code contract (0 green, 1 violation, 2 usage). Argument
syntax, semantic validation, and diagnostics belong to the domain
packages; the single-command ``scope`` domain registers its flags directly
at the domain level.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from hdsh import scope
from hdsh.cliargs import ArgumentParser, CommandSubparsers, HelpShown
from hdsh.docs import budgets, links, wrap
from hdsh.pairing import brief as pairing_brief
from hdsh.pairing import merge as pairing_merge
from hdsh.pairing import verify as pairing_verify
from hdsh.policy import commands as policy_commands
from hdsh.rfc import archive as rfc_archive
from hdsh.rfc import format as rfc_format
from hdsh.worktree import install as worktree_install

#: Registers one domain's command leaves on a command-level action.
Registrar = Callable[[CommandSubparsers], None]

#: One command handler: consumes the parsed leaf namespace, returns the exit code.
Handler = Callable[[argparse.Namespace], int]

#: The multi-command domains, in help order: name, one-line help, registrars.
_COMMAND_DOMAINS: tuple[tuple[str, str, tuple[Registrar, ...]], ...] = (
    (
        "pairing",
        "bilingual documentation pairing",
        (pairing_verify.register, pairing_merge.register, pairing_brief.register),
    ),
    (
        "docs",
        "documentation corpus gates",
        (wrap.register, links.register, budgets.register),
    ),
    ("rfc", "RFC format gates", (rfc_format.register, rfc_archive.register)),
    ("policy", "GitHub issue and pull-request policy", (policy_commands.register,)),
    ("worktree", "worktree-local prek hooks", (worktree_install.register,)),
)


def _build_parser() -> ArgumentParser:
    """Build the full ``hdsh`` command tree."""
    parser = ArgumentParser(prog="hdsh")
    domains = parser.add_subparsers(title="domains", required=True)
    scope.register(domains)
    for name, help_text, registrars in _COMMAND_DOMAINS:
        domain_parser = domains.add_parser(name, help=help_text)
        commands = domain_parser.add_subparsers(title="commands", required=True)
        for register in registrars:
            register(commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch one ``hdsh`` invocation.

    Args:
        argv: The full argument list after the ``hdsh`` program name;
            defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 0 green (or handled help), 1 violation,
        2 usage.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    if not arguments:
        parser.print_help(sys.stderr)
        return 2
    try:
        parsed = parser.parse_args(arguments)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    except HelpShown:
        return 0
    handler: Handler = parsed.handler
    return handler(parsed)
