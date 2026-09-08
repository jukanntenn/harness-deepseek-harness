"""The argparse-to-exit-code wiring shared by every hdsh command."""

from __future__ import annotations

import pytest

from hdsh.cliargs import ArgumentParser, HelpShown


def _parser() -> ArgumentParser:
    parser = ArgumentParser(prog="hdsh probe")
    parser.add_argument("--config", required=True)
    return parser


class TestArgumentParser:
    def test_usage_errors_surface_as_value_errors(self) -> None:
        with pytest.raises(ValueError, match="hdsh probe: the following arguments"):
            _parser().parse_args([])

    def test_flags_must_match_exactly(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments: --conf"):
            _parser().parse_args(["--config", "c", "--conf", "y"])

    def test_help_is_printed_then_signaled(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(HelpShown):
            _parser().parse_args(["--help"])
        assert "usage: hdsh probe" in capsys.readouterr().out
