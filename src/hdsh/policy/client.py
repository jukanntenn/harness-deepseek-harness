"""REST and GraphQL access for the policy engine, with injectable transport.

The client is pure plumbing over the GitHub APIs: snapshots, Project-item
maintenance, status writes, and the audit comment. All policy judgment lives
in :mod:`hdsh.policy.rules`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from hdsh.policy.config import PolicyConfig
from hdsh.policy.rules import (
    classification_from_labels,
    next_resolving_issue_status,
    parse_references,
    project_date,
    requires_pull_request_policy,
    resolving_issue_status_command,
    retain_issue_references,
    validate_issue,
    validate_pull_request,
)

API_VERSION = "2026-03-10"
_HTTP_NOT_FOUND = 404
_HTTP_ERROR_MIN = 400
AUDIT_MARKER = "<!-- hdsh-issue-policy -->"

Transport = Callable[..., Any]


class GitHubPolicyClient:
    """REST and GraphQL access for the policy engine, with injectable transport."""

    config: PolicyConfig
    repository_token: str
    project_token: str
    api_base: str
    _transport: Transport

    def __init__(
        self,
        config: PolicyConfig,
        repository_token: str,
        project_token: str,
        *,
        api_base: str = "https://api.github.com",
        transport: Transport | None = None,
    ) -> None:
        """Bind the client to tokens and an HTTP transport.

        Args:
            config: Policy configuration.
            repository_token: Token for REST Issue and pull-request reads.
            project_token: Token for ProjectV2 GraphQL operations.
            api_base: GitHub REST API base URL.
            transport: Callable executing ``request(url, method, body, headers)``
                and returning ``(status, body_text)``; defaults to urllib.
        """
        self.config = config
        self.repository_token = repository_token
        self.project_token = project_token
        self.api_base = api_base
        self._transport = transport or self._urllib_transport

    @staticmethod
    def _urllib_transport(
        url: str,
        method: str = "GET",
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        request = urllib.request.Request(  # noqa: S310 - api_base is https by contract
            url,
            method=method,
            data=body.encode("utf-8") if body is not None else None,
            headers=headers or {},
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - scheme verified above
                request
            ) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def _api(
        self,
        path: str,
        *,
        method: str = "GET",
        body: str | None = None,
        allow_404: bool = False,
    ) -> Any:  # noqa: ANN401 - decoded JSON payloads are Any by nature
        status, text = self._transport(
            f"{self.api_base}{path}",
            method,
            body,
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.repository_token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "hdsh-policy",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        if allow_404 and status == _HTTP_NOT_FOUND:
            return None
        if status >= _HTTP_ERROR_MIN:
            msg = f"{method} {path}: {status} {text}"
            raise RuntimeError(msg)
        return json.loads(text) if text else None

    def _graphql(self, query: str, variables: dict[str, Any]) -> Any:  # noqa: ANN401 - GraphQL responses are Any by nature
        status, text = self._transport(
            f"{self.api_base}/graphql",
            "POST",
            json.dumps({"query": query, "variables": variables}),
            {
                "Authorization": f"Bearer {self.project_token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "User-Agent": "hdsh-policy",
            },
        )
        if status >= _HTTP_ERROR_MIN:
            msg = f"POST /graphql: {status} {text}"
            raise RuntimeError(msg)
        result = json.loads(text)
        if result.get("errors"):
            raise RuntimeError("; ".join(e["message"] for e in result["errors"]))
        return result["data"]

    def issue_snapshot(self, number: int, status: str | None = None) -> dict[str, Any] | None:
        """Read one Issue together with its Project planning values.

        Args:
            number: Same-repository Issue number.
            status: Optionally known Project status.

        Returns:
            Issue snapshot, or ``None`` when the number identifies a pull request.
        """
        issue = self._api(f"/repos/{self.config.owner}/{self.config.repository}/issues/{number}")
        if issue.get("pull_request") is not None:
            return None
        context = self.project_context(number)
        labels = [label["name"] for label in issue["labels"]]
        return {
            "number": number,
            "nodeId": issue["node_id"],
            "title": issue["title"],
            "body": issue.get("body") or "",
            "assignees": [a["login"] for a in issue["assignees"]],
            "labels": labels,
            "type": (
                (issue.get("type") or {}).get("name")
                if self.config.account_type == "organization"
                else classification_from_labels(labels)
            ),
            "priority": (context["item"].get("priorityValue") or {}).get("name")
            if context["item"]
            else None,
            "status": (
                status
                if status is not None
                else (
                    (context["item"].get("fieldValueByName") or {}).get("name")
                    if context["item"]
                    else None
                )
            ),
            "state": issue["state"],
            "stateReason": issue.get("state_reason"),
        }

    _PROJECT_QUERY: str = """
    query($owner: String!, $repository: String!, $number: Int!,
          $project: Int!, $isOrganization: Boolean!, $isUser: Boolean!,
          $includeStatusActor: Boolean!, $includeStartDate: Boolean!,
          $priorityField: String!, $startDateField: String!) {
      organization(login: $owner) @include(if: $isOrganization) {
        projectV2(number: $project) {
          id
          title
          fields(first: 50) {
            nodes {
              ... on ProjectV2Field { id name dataType isIssueField }
              ... on ProjectV2SingleSelectField {
                id name dataType isIssueField options { id name }
              }
            }
          }
        }
      }
      user(login: $owner) @include(if: $isUser) {
        projectV2(number: $project) {
          id
          title
          fields(first: 50) {
            nodes {
              ... on ProjectV2Field { id name dataType isIssueField }
              ... on ProjectV2SingleSelectField {
                id name dataType isIssueField options { id name }
              }
            }
          }
        }
      }
      repository(owner: $owner, name: $repository) {
        issue(number: $number) {
          id
          timelineItems(last: 100, itemTypes: [PROJECT_V2_ITEM_STATUS_CHANGED_EVENT])
            @include(if: $includeStatusActor) {
            nodes {
              ... on ProjectV2ItemStatusChangedEvent { actor { login } project { id } status }
            }
          }
          projectItems(first: 20, includeArchived: true) {
            nodes {
              id
              project { id }
              fieldValueByName(name: "Status") {
                ... on ProjectV2ItemFieldSingleSelectValue { name optionId }
              }
              priorityValue: fieldValueByName(name: $priorityField) {
                ... on ProjectV2ItemFieldSingleSelectValue { name optionId }
              }
              startDateValue: fieldValueByName(name: $startDateField)
                @include(if: $includeStartDate) {
                ... on ProjectV2ItemFieldDateValue { date }
              }
            }
          }
        }
      }
    }
    """

    def project_context(
        self, number: int, include_status_actor: bool = False, include_start_date: bool = False
    ) -> dict[str, Any]:
        """Read Project fields, the Issue's item, and its latest status actor.

        Args:
            number: Same-repository Issue number.
            include_status_actor: Include the latest status-change event.
            include_start_date: Include the Start Date field and value.

        Returns:
            The project, issue, fields, item, and status actor.

        Raises:
            RuntimeError: When the Project or a required field is missing or
                has the wrong data type.
        """
        config = self.config
        data = self._graphql(
            self._PROJECT_QUERY,
            {
                "owner": config.owner,
                "repository": config.repository,
                "number": number,
                "project": config.project_number,
                "isOrganization": config.account_type == "organization",
                "isUser": config.account_type == "user",
                "includeStatusActor": include_status_actor,
                "includeStartDate": include_start_date,
                "priorityField": config.priority_field,
                "startDateField": config.start_date_field,
            },
        )
        account = data.get("organization") or data.get("user") or {}
        project = account.get("projectV2") or None
        issue = ((data.get("repository") or {}).get("issue")) or None
        if not project or project["title"] != config.project_title:
            msg = "target Project is missing or its title does not match"
            raise RuntimeError(msg)
        if not issue:
            msg = f"#{number} does not exist"
            raise RuntimeError(msg)
        fields = project["fields"]["nodes"]
        status_field = next((f for f in fields if f["name"] == "Status"), None)
        if not status_field:
            msg = "Project is missing the Status field"
            raise RuntimeError(msg)
        priority_field = next((f for f in fields if f["name"] == config.priority_field), None)
        if not priority_field:
            msg = f"Project is missing the {config.priority_field} field"
            raise RuntimeError(msg)
        if priority_field["dataType"] != "SINGLE_SELECT":
            msg = f"Project {config.priority_field} field must be Single Select"
            raise RuntimeError(msg)
        if priority_field["isIssueField"]:
            msg = f"Project {config.priority_field} field must be a Project custom field"
            raise RuntimeError(msg)
        start_date_field = None
        if include_start_date:
            start_date_field = next(
                (f for f in fields if f["name"] == config.start_date_field), None
            )
            if not start_date_field:
                msg = f"Project is missing the {config.start_date_field} field"
                raise RuntimeError(msg)
            if start_date_field["dataType"] != "DATE":
                msg = f"Project {config.start_date_field} field must be Date"
                raise RuntimeError(msg)
            if start_date_field["isIssueField"]:
                msg = f"Project {config.start_date_field} field must be a Project Date field"
                raise RuntimeError(msg)
        item = next(
            (n for n in issue["projectItems"]["nodes"] if n["project"]["id"] == project["id"]),
            None,
        )
        status_actor = None
        timeline = issue.get("timelineItems", {}).get("nodes", []) if include_status_actor else []
        latest = next((e for e in reversed(timeline) if e["project"]["id"] == project["id"]), None)
        if latest and item and latest["status"] == (item.get("fieldValueByName") or {}).get("name"):
            status_actor = (latest.get("actor") or {}).get("login")
        return {
            "project": project,
            "issue": issue,
            "statusField": status_field,
            "priorityField": priority_field,
            "startDateField": start_date_field,
            "item": item,
            "statusActor": status_actor,
        }

    def ensure_project_item(self, number: int, include_start_date: bool = False) -> dict[str, Any]:
        """Load one Issue's Project item, adding it to the Project when absent.

        Args:
            number: Same-repository Issue number.
            include_start_date: Include Start Date validation and value.

        Returns:
            The project context with a non-null item.
        """
        context = self.project_context(number, False, include_start_date)
        if context["item"]:
            return context
        data = self._graphql(
            """
            mutation($projectId: ID!, $contentId: ID!) {
              addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
                item { id }
              }
            }
            """,
            {"projectId": context["project"]["id"], "contentId": context["issue"]["id"]},
        )
        context["item"] = {"id": data["addProjectV2ItemById"]["item"]["id"]}
        return context

    def initialize_issue_start_date(self, number: int, date: str) -> None:
        """Initialize one Issue's Project Start Date when it is empty.

        Args:
            number: Same-repository Issue number.
            date: Date in YYYY-MM-DD form.
        """
        context = self.ensure_project_item(number, True)
        if (context["item"].get("startDateValue") or {}).get("date"):
            return
        self._graphql(
            """
            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $date: Date!) {
              updateProjectV2ItemFieldValue(input: {
                projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
                value: {date: $date}
              }) { projectV2Item { id } }
            }
            """,
            {
                "projectId": context["project"]["id"],
                "itemId": context["item"]["id"],
                "fieldId": context["startDateField"]["id"],
                "date": date,
            },
        )

    def initialize_pull_request_start_dates(
        self,
        pull: dict[str, Any],
        action: str,
        initialize: Callable[[int, str], Any] | None = None,
    ) -> None:
        """Initialize every Issue referenced by a newly opened pull request.

        Args:
            pull: Pull-request snapshot with ``createdAt`` and references.
            action: Pull-request event action.
            initialize: Date writer; defaults to ``initialize_issue_start_date``.
        """
        if action != "opened":
            return
        writer = initialize or self.initialize_issue_start_date
        date = project_date(pull["createdAt"], self.config.project_time_zone)
        for number in pull["references"]["all"]:
            writer(number, date)

    def _update_status(self, context: dict[str, Any], status: str) -> None:
        option = next((o for o in context["statusField"]["options"] if o["name"] == status), None)
        if not option:
            msg = f"Status does not exist: {status}"
            raise RuntimeError(msg)
        current = (context["item"].get("fieldValueByName") or {}).get("name")
        if current == status:
            return
        self._graphql(
            """
            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
              updateProjectV2ItemFieldValue(input: {
                projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
                value: {singleSelectOptionId: $optionId}
              }) { projectV2Item { id } }
            }
            """,
            {
                "projectId": context["project"]["id"],
                "itemId": context["item"]["id"],
                "fieldId": context["statusField"]["id"],
                "optionId": option["id"],
            },
        )

    def set_status(self, number: int, status: str) -> None:
        """Ensure the Issue is a Project item, then set its Status.

        Args:
            number: Same-repository Issue number.
            status: Target Status name.
        """
        self._update_status(self.ensure_project_item(number), status)

    def upsert_audit(self, number: int, errors: list[str]) -> None:
        """Create, update, or delete the audit comment carrying the marker.

        Args:
            number: Same-repository Issue number.
            errors: Current validation errors.
        """
        repo = f"/repos/{self.config.owner}/{self.config.repository}"
        comments = self._api(f"{repo}/issues/{number}/comments?per_page=100")
        existing = next(
            (
                c
                for c in comments
                if (c.get("user") or {}).get("type") == "Bot"
                and AUDIT_MARKER in (c.get("body") or "")
            ),
            None,
        )
        if not errors:
            if existing:
                self._api(f"{repo}/issues/comments/{existing['id']}", method="DELETE")
            return
        body = f"{AUDIT_MARKER}\n⚠️ Issue policy failed:\n\n" + "\n".join(
            f"- {error}" for error in errors
        )
        if existing:
            if existing["body"] == body:
                return
            self._api(
                f"{repo}/issues/comments/{existing['id']}",
                method="PATCH",
                body=json.dumps({"body": body}),
            )
        else:
            self._api(
                f"{repo}/issues/{number}/comments", method="POST", body=json.dumps({"body": body})
            )

    def audit_issue(
        self, number: int, extra_errors: list[str] | None = None, status: str | None = None
    ) -> list[str]:
        """Validate one Issue and upsert its audit comment.

        Args:
            number: Same-repository Issue number.
            extra_errors: Errors to prepend.
            status: Optionally known Project status.

        Returns:
            All validation errors.
        """
        issue = self.issue_snapshot(number, status)
        if issue is None:
            return []
        errors = [*(extra_errors or []), *validate_issue(issue, self.config)]
        self.upsert_audit(number, errors)
        return errors

    def _resolving_references_snapshot(self, number: int, pull: dict[str, Any]) -> dict[str, Any]:
        references = parse_references(
            pull.get("body") or "",
            f"{self.config.owner}/{self.config.repository}",
        )
        issues: dict[int, Any] = {}
        for issue_number in references.all:
            issue = self.issue_snapshot(issue_number, status=None)
            if issue is not None:
                issues[issue_number] = issue
        retained = retain_issue_references(references, issues)
        return {
            "number": number,
            "references": {
                "all": retained.all,
                "resolving": retained.resolving,
                "related": retained.related,
            },
            "issues": issues,
        }

    def pull_request_snapshot(self, number: int) -> dict[str, Any]:
        """Read the pull request, its review state, and referenced Issues.

        Args:
            number: Pull-request number.

        Returns:
            The validated-policy snapshot.
        """
        repo = f"/repos/{self.config.owner}/{self.config.repository}"
        pull = self._api(f"{repo}/pulls/{number}")
        review_requests = self._api(f"{repo}/pulls/{number}/requested_reviewers")
        reviews = self._api(f"{repo}/pulls/{number}/reviews?per_page=100")
        resolving = self._resolving_references_snapshot(number, pull)
        return {
            **resolving,
            "isDraft": pull["draft"],
            "authorType": (pull.get("user") or {}).get("type", "User"),
            "reviewRequestCount": len(review_requests["users"]) + len(review_requests["teams"]),
            "reviewCount": len(reviews),
            "labels": [label["name"] for label in pull["labels"]],
        }

    def lifecycle_pull_request_snapshot(self, number: int) -> dict[str, Any]:
        """Read the pull request body and its resolving references.

        Args:
            number: Pull-request number.

        Returns:
            Snapshot including ``createdAt``.
        """
        pull = self._api(f"/repos/{self.config.owner}/{self.config.repository}/pulls/{number}")
        return {
            **self._resolving_references_snapshot(number, pull),
            "createdAt": pull["created_at"],
        }

    def transition_resolving_issues(self, pull: dict[str, Any], command: str) -> None:
        """Apply one lifecycle command to every resolving Issue.

        Args:
            pull: Lifecycle pull-request snapshot.
            command: Lifecycle command.
        """
        for number in pull["references"]["resolving"]:
            context = self.project_context(number, command == "changes-requested")
            target = next_resolving_issue_status(
                (context["item"].get("fieldValueByName") or {}).get("name")
                if context["item"]
                else None,
                command,
                context["statusActor"],
                self.config,
            )
            if not target:
                continue
            # TODO: replace this latest-state guard with per-Issue serialization
            # or a conditional ProjectV2 update; GraphQL has no compare-and-swap.
            self._update_status(context, target)
            self.audit_issue(number)

    def run_pull_request_check(self, event: dict[str, Any]) -> None:
        """Validate one pull-request event's policy snapshot.

        Args:
            event: Pull-request event payload.
        """
        pull = self.pull_request_snapshot(event["pull_request"]["number"])
        errors = validate_pull_request(pull)
        if errors:
            for error in errors:
                print(f"::error::{error}")
            msg = f"Issue policy failed with {len(errors)} error(s)"
            raise RuntimeError(msg)
        print(
            "Issue policy passed."
            if requires_pull_request_policy(
                pull["isDraft"],
                pull["authorType"],
                pull["reviewRequestCount"],
                pull["reviewCount"],
            )
            else "Pull request is not yet in the Issue policy enforcement scope."
        )

    def run_lifecycle(self, event_name: str, event: dict[str, Any]) -> None:
        """Apply one repository event to the Issue lifecycle.

        Args:
            event_name: GitHub event name.
            event: GitHub event payload.
        """
        if event_name == "issues":
            number = event["issue"]["number"]
            if event["action"] == "opened":
                self.set_status(number, "Inbox")
            if event["action"] == "closed":
                self.set_status(
                    number,
                    "No action" if event["issue"].get("state_reason") == "not_planned" else "Done",
                )
            if event["action"] == "reopened":
                self.set_status(number, "Inbox")
            self.ensure_project_item(number)
            self.audit_issue(number)
            return
        if event_name in ("pull_request", "pull_request_review"):
            command = resolving_issue_status_command(event_name, event)
            if not command:
                return
            pull = self.lifecycle_pull_request_snapshot(event["pull_request"]["number"])
            self.transition_resolving_issues(pull, command)
            if event_name == "pull_request":
                self.initialize_pull_request_start_dates(pull, event["action"])


def client_from_environment(config: PolicyConfig) -> GitHubPolicyClient:
    """Build the policy client from ``GH_TOKEN``/``GITHUB_TOKEN`` variables.

    Args:
        config: Policy configuration.

    Returns:
        The bound client.

    Raises:
        RuntimeError: When no token is configured.
    """
    repository_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repository_token:
        msg = "GH_TOKEN or GITHUB_TOKEN is not set"
        raise RuntimeError(msg)
    project_token = os.environ.get("PROJECT_TOKEN") or repository_token
    return GitHubPolicyClient(
        config,
        repository_token=repository_token,
        project_token=project_token,
        api_base=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
