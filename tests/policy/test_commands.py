"""The ``hdsh policy`` subcommand entries and event dispatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import hdsh.policy.commands as policy_module
from hdsh.policy.commands import (
    _request,
    lifecycle_main,
    pr_main,
    read_event,
    run_command,
)
from tests.helpers import parse_command
from tests.policy.support import config_with


class FakeClient:
    """Records the dispatch a command triggers."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def run_pull_request_check(self, event: dict[str, object]) -> None:
        self.calls.append(("pr", event))

    def run_lifecycle(self, event_name: str, event: dict[str, object]) -> None:
        self.calls.append(("lifecycle", (event_name, event)))


class TestRunCommand:
    def test_pr_dispatches_the_check(self) -> None:
        client = FakeClient()
        run_command("pr", "pull_request", {"pull_request": {"number": 1}}, client)
        assert client.calls == [("pr", {"pull_request": {"number": 1}})]

    def test_lifecycle_dispatches_the_event(self) -> None:
        client = FakeClient()
        run_command("lifecycle", "issues", {"action": "opened"}, client)
        assert client.calls == [("lifecycle", ("issues", {"action": "opened"}))]

    def test_unknown_command_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown policy command"):
            run_command("bogus", "", {}, FakeClient())


class TestReadEvent:
    def test_reads_json_payload(self, tmp_path: Path) -> None:
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"action": "opened"}), encoding="utf-8")
        assert read_event(str(event)) == {"action": "opened"}

    def test_missing_payload_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="cannot read event payload"):
            read_event(str(tmp_path / "gone.json"))

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        event = tmp_path / "event.json"
        event.write_text("{nope", encoding="utf-8")
        with pytest.raises(RuntimeError, match="cannot read event payload"):
            read_event(str(event))


class TestRequest:
    def test_requires_config(self) -> None:
        with pytest.raises(ValueError, match="--config is required"):
            _request(argparse.Namespace(config=None, event=""))

    def test_returns_config_and_event(self) -> None:
        args = argparse.Namespace(config="c.json", event="e.json")
        assert _request(args) == ("c.json", "e.json")


class TestLeafParsing:
    def test_parses_config_and_event(self) -> None:
        parsed = parse_command(
            policy_module.register, ["pr", "--config", "c.json", "--event", "e.json"]
        )
        assert (parsed.config, parsed.event) == ("c.json", "e.json")

    def test_rejects_unknown_arguments(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse_command(policy_module.register, ["pr", "--config", "c.json", "--verbose"])

    def test_rejects_flag_without_value(self) -> None:
        with pytest.raises(ValueError, match="expected one argument"):
            parse_command(policy_module.register, ["pr", "--config"])


class TestPolicyMain:
    def write_config(self, tmp_path: Path) -> str:
        config = tmp_path / "config.json"
        config.write_text(config_with(), encoding="utf-8")
        return str(config)

    def pr_cli(self, *args: str) -> int:
        return pr_main(parse_command(policy_module.register, ["pr", *args]))

    def lifecycle_cli(self, *args: str) -> int:
        return lifecycle_main(parse_command(policy_module.register, ["lifecycle", *args]))

    def test_pr_runs_the_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 1}}), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert self.pr_cli("--config", self.write_config(tmp_path)) == 1
        assert "GH_TOKEN or GITHUB_TOKEN" in capsys.readouterr().err

    def test_missing_event_env_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        assert self.lifecycle_cli("--config", self.write_config(tmp_path)) == 1

    def test_missing_config_flag_is_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert self.pr_cli() == 2
        assert "--config is required" in capsys.readouterr().err


class TestPolicyMainSuccess:
    def test_pr_main_returns_zero_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 1}}), encoding="utf-8")
        config = tmp_path / "config.json"
        config.write_text(config_with(), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GH_TOKEN", "token")
        dispatched: list[tuple[str, object]] = []
        monkeypatch.setattr(
            policy_module,
            "run_command",
            lambda command, name, payload, client: dispatched.append((command, payload)),
        )
        parsed = parse_command(policy_module.register, ["pr", "--config", str(config)])
        assert pr_main(parsed) == 0
        assert dispatched == [("pr", {"pull_request": {"number": 1}})]

    def test_lifecycle_main_returns_zero_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"action": "opened"}), encoding="utf-8")
        config = tmp_path / "config.json"
        config.write_text(config_with(), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
        monkeypatch.setenv("GH_TOKEN", "token")
        monkeypatch.setattr(policy_module, "run_command", lambda *args: None)
        parsed = parse_command(policy_module.register, ["lifecycle", "--config", str(config)])
        assert lifecycle_main(parsed) == 0
