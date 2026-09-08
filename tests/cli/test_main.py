"""The unified ``hdsh`` entry point: dispatch, help, and usage errors."""

from __future__ import annotations

import argparse

import pytest

from hdsh.cli import main


class TestDispatch:
    def test_no_arguments_prints_help_and_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([]) == 2
        assert "usage: hdsh" in capsys.readouterr().err

    def test_help_lists_domains_and_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--help"]) == 0
        out = capsys.readouterr().out
        assert "domains:" in out
        assert "pairing" in out
        assert "scope" in out
        assert "worktree" in out

    def test_unknown_domain_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["bogus", "verify"]) == 2
        captured = capsys.readouterr()
        assert "hdsh: argument" in captured.err
        assert "invalid choice: 'bogus'" in captured.err

    def test_domain_without_command_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["pairing"]) == 2
        captured = capsys.readouterr()
        assert "hdsh pairing:" in captured.err
        assert "required" in captured.err

    def test_unknown_command_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["pairing", "bogus"]) == 2
        captured = capsys.readouterr()
        assert "hdsh pairing: argument" in captured.err
        assert "invalid choice: 'bogus'" in captured.err

    def test_domain_help_lists_its_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["docs", "--help"]) == 0
        out = capsys.readouterr().out
        assert "wrap" in out
        assert "links" in out
        assert "budgets" in out

    def test_command_help_documents_its_flags(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["pairing", "verify", "--help"]) == 0
        out = capsys.readouterr().out
        assert "usage: hdsh pairing verify" in out
        assert "--cached" in out

    def test_every_registered_command_is_reachable(self) -> None:
        invocations = [
            ["pairing", "verify", "--help"],
            ["pairing", "record", "--help"],
            ["pairing", "list", "--help"],
            ["pairing", "merge", "--help"],
            ["docs", "wrap", "--help"],
            ["docs", "links", "--help"],
            ["docs", "budgets", "--help"],
            ["rfc", "verify", "--help"],
            ["rfc", "archive", "--help"],
            ["rfc", "seal", "--help"],
            ["scope", "--help"],
            ["policy", "pr", "--help"],
            ["policy", "lifecycle", "--help"],
            ["worktree", "install", "--help"],
        ]
        for argv in invocations:
            assert main(argv) == 0, argv

    def test_subcommand_receives_the_parsed_namespace(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from hdsh.docs import budgets

        seen: list[argparse.Namespace] = []

        def record_then_zero(args: argparse.Namespace) -> int:
            seen.append(args)
            return 0

        monkeypatch.setattr(budgets, "main", record_then_zero)
        assert main(["docs", "budgets", "--list"]) == 0
        assert seen[0].list is True

    def test_handler_exit_code_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import hdsh.scope as scope_module

        def exit_seven(args: argparse.Namespace) -> int:
            return 7

        monkeypatch.setattr(scope_module, "main", exit_seven)
        assert main(["scope", "--base", "main"]) == 7


def test_python_m_hdsh_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy
    import sys

    import hdsh.docs.budgets

    monkeypatch.setattr(sys, "argv", ["hdsh", "docs", "budgets", "--list"])

    def exit_zero(args: argparse.Namespace) -> int:
        return 0

    monkeypatch.setattr(hdsh.docs.budgets, "main", exit_zero)
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("hdsh", run_name="__main__", alter_sys=True)
    assert excinfo.value.code == 0


def test_main_module_import_is_inert() -> None:
    # Importing hdsh.__main__ as a plain module must not dispatch anything.
    import hdsh.__main__ as hdsh_main_module

    assert hdsh_main_module.__name__ == "hdsh.__main__"
