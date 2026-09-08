"""Shared fixtures for the policy-domain tests: config, issue shapes, doubles."""

from __future__ import annotations

import json
from typing import Any

from hdsh.policy.client import GitHubPolicyClient
from hdsh.policy.config import PolicyConfig

CONFIG_JSON = {
    "owner": "hdsh",
    "accountType": "organization",
    "repository": "hdsh",
    "projectNumber": 1,
    "projectTitle": "HDSH Issue Management",
    "lifecycleActor": "hdsh-issue-management",
    "priorityField": "Priority",
    "startDateField": "Start Date",
    "projectTimeZone": "Asia/Shanghai",
    "allowUnassignedOwner": True,
    "statuses": ["Inbox", "Backlog", "Ready", "In progress", "In review", "Done", "No action"],
}

CONFIG = PolicyConfig.from_json(json.dumps(CONFIG_JSON))
USER_CONFIG = PolicyConfig.from_json(json.dumps({**CONFIG_JSON, "accountType": "user"}))


def config_with(**overrides: Any) -> str:
    """The canonical policy config JSON with per-test overrides."""
    return json.dumps({**CONFIG_JSON, **overrides})


def with_details(summary: str) -> str:
    """Wrap one summary in the required collapsed details region."""
    return f"{summary}\n\n<details><summary>Acceptance and details</summary>To be filled.</details>"


LEGAL_ISSUE: dict[str, Any] = {
    "title": "Finish issue-management validation",
    "body": with_details("Finish issue-management validation."),
    "assignees": [],
    "labels": [],
    "type": "Idea",
    "priority": None,
    "status": "In review",
    "state": "open",
    "stateReason": None,
}


def reviewed_pull(labels: list[str]) -> dict[str, Any]:
    """A policy-scoped pull-request snapshot carrying ``labels``."""
    return {
        "isDraft": False,
        "authorType": "User",
        "reviewRequestCount": 1,
        "reviewCount": 0,
        "labels": labels,
        "references": {"all": [2], "resolving": [], "related": [2]},
        "issues": {2: {"priority": None}},
    }


def make_client(
    transport: Any, *, project_transport: Any = None, config: PolicyConfig | None = None
) -> GitHubPolicyClient:
    """A client whose transport is ``transport`` (or a REST/GraphQL router)."""
    return GitHubPolicyClient(
        config or CONFIG,
        repository_token="repository-token",
        project_token="project-token",
        transport=transport
        if project_transport is None
        else routing_transport(transport, project_transport),
    )


def routing_transport(rest: Any, graphql: Any) -> Any:
    """Route one transport by URL: ``/graphql`` to ``graphql``, the rest to ``rest``."""

    def route(
        url: str,
        method: str = "GET",
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        if url.endswith("/graphql"):
            return graphql(url, method, body, headers)
        return rest(url, method, body, headers)

    return route
