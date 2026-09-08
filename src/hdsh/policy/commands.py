"""``hdsh policy`` subcommand entries and event dispatch."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from hdsh.policy.client import client_from_environment
from hdsh.policy.config import PolicyConfig

if TYPE_CHECKING:
    import argparse

    from hdsh import cliargs

TOOL = "hdsh policy"


class PolicyRunner(Protocol):
    """The client surface the command dispatch consumes."""

    def run_pull_request_check(self, event: dict[str, Any]) -> None:
        """Validate one pull-request event's policy snapshot."""
        ...

    def run_lifecycle(self, event_name: str, event: dict[str, Any]) -> None:
        """Apply one repository event to the Issue lifecycle."""
        ...


def run_command(
    command: str,
    event_name: str,
    event: dict[str, Any],
    client: PolicyRunner,
) -> None:
    """Dispatch one policy CLI command.

    Args:
        command: ``pr`` or ``lifecycle``.
        event_name: GitHub event name from the environment.
        event: GitHub event payload.
        client: Bound GitHub client.

    Raises:
        ValueError: On an unknown command.
    """
    if command == "pr":
        client.run_pull_request_check(event)
    elif command == "lifecycle":
        client.run_lifecycle(event_name, event)
    else:
        msg = f"unknown policy command: {command}"
        raise ValueError(msg)


def read_event(path: str) -> dict[str, Any]:
    """Read the GitHub event payload from one JSON file.

    Args:
        path: Event payload path.

    Returns:
        The parsed event payload.

    Raises:
        RuntimeError: When the payload cannot be read or parsed.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        msg = f"cannot read event payload {path}: {error}"
        raise RuntimeError(msg) from error


def register(subparsers: cliargs.CommandSubparsers) -> None:
    """Register the ``pr`` and ``lifecycle`` command leaves."""
    for command, handler, help_text in (
        ("pr", pr_main, "pull-request policy check"),
        ("lifecycle", lifecycle_main, "event-directed Issue lifecycle"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument(
            "--config", metavar="<path>", help="the repository's policy config.json"
        )
        parser.add_argument(
            "--event",
            metavar="<path>",
            default="",
            help="event payload path (default: GITHUB_EVENT_PATH)",
        )
        parser.set_defaults(handler=handler)


def _request(args: argparse.Namespace) -> tuple[str, str]:
    """Validate one command's parsed options.

    Args:
        args: Parsed leaf namespace with ``config`` and ``event``.

    Returns:
        The configuration path and the event path.

    Raises:
        ValueError: When ``--config`` is missing.
    """
    if args.config is None:
        msg = "--config is required (the repository's policy config.json)"
        raise ValueError(msg)
    return args.config, args.event


def _policy_main(command: str, args: argparse.Namespace) -> int:
    """Shared ``hdsh policy`` entry: validate, load, and dispatch."""
    try:
        config_path, event_path = _request(args)
    except ValueError as error:
        print(f"{TOOL} {command}: {error}", file=sys.stderr)
        return 2
    try:
        config = PolicyConfig.from_json(Path(config_path).read_text(encoding="utf-8"))
        resolved_event_path = event_path or os.environ.get("GITHUB_EVENT_PATH", "")
        if not resolved_event_path:
            msg = "GITHUB_EVENT_PATH is not set"
            raise RuntimeError(msg)
        run_command(
            command,
            os.environ.get("GITHUB_EVENT_NAME", ""),
            read_event(resolved_event_path),
            client_from_environment(config),
        )
    except (RuntimeError, ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def pr_main(args: argparse.Namespace) -> int:
    """``hdsh policy pr`` entry point."""
    return _policy_main("pr", args)


def lifecycle_main(args: argparse.Namespace) -> int:
    """``hdsh policy lifecycle`` entry point."""
    return _policy_main("lifecycle", args)
