"""argparse wiring for the ``hdsh`` exit-code contract.

argparse parsers print and exit the process on usage errors and on
``--help``; hdsh command handlers return integer exit codes instead. This
module converts both parser exits into ordinary control flow: usage errors
surface as ``ValueError`` messages prefixed with the parser's ``prog``, and
a handled ``--help`` surfaces as ``HelpShown`` (its text is already on
stdout when the exception is raised).
"""

from __future__ import annotations

import argparse
from typing import Any, NoReturn, override

#: argparse keeps its subparser action type private (``_SubParsersAction``);
#: registrar signatures take it as ``Any`` rather than reach the private name.
type CommandSubparsers = Any


class HelpShown(Exception):  # noqa: N818 - a successful help exit, not an error condition
    """``-h``/``--help`` was handled; its text is already on stdout."""


class ArgumentParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` that signals instead of exiting the process.

    Long-option prefix abbreviation is disabled: hdsh commands take few
    flags, and a mistyped flag must fail loud rather than silently resolve
    to a prefix match.
    """

    def __init__(
        self,
        *args: Any,  # noqa: ANN401 - argparse's own constructor surface passes through
        **kwargs: Any,  # noqa: ANN401 - argparse's own constructor surface passes through
    ) -> None:
        """Create the parser with abbreviation matching always disabled."""
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    @override
    def error(self, message: str) -> NoReturn:
        """Reject a usage error as a ``ValueError`` carrying ``<prog>:``.

        Raises:
            ValueError: Always; argparse would otherwise print and exit 2.
        """
        raise ValueError(f"{self.prog}: {message}")

    @override
    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        """Convert the parser's exit path to :class:`HelpShown`.

        Only the help action reaches this method, ignoring both arguments:
        :meth:`error` is overridden above and no version actions are
        registered.

        Raises:
            HelpShown: Always, after the help action printed its text.
        """
        raise HelpShown
