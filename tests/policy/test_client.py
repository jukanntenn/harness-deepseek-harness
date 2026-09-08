"""The policy client: snapshots, Project maintenance, audits, transports."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from hdsh.policy.client import GitHubPolicyClient, client_from_environment
from hdsh.policy.config import PolicyConfig
from tests.helpers import project_payload
from tests.policy.support import CONFIG, config_with, make_client, routing_transport


def _client(transport: Any) -> GitHubPolicyClient:
    return GitHubPolicyClient(
        PolicyConfig.from_json(config_with()),
        repository_token="r-token",
        project_token="p-token",
        transport=transport,
    )


def _graphql_client_with_data(data: dict[str, Any]) -> GitHubPolicyClient:
    def transport(
        url: str,
        method: str = "GET",
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        if url.endswith("/graphql"):
            return 200, json.dumps({"data": data})
        return 200, "{}"

    return _client(transport)


def project_graphql_data(
    *,
    project_item: bool = True,
    priority: str | None = None,
    priority_field: bool = True,
    priority_type: str = "SINGLE_SELECT",
    priority_issue_field: bool = False,
    start_date: str | None = None,
    start_date_field: bool = True,
    start_date_type: str = "DATE",
    start_date_issue_field: bool = False,
) -> dict[str, Any]:
    status_options = [{"id": f"{status}-option-id", "name": status} for status in CONFIG.statuses]
    fields: list[dict[str, Any]] = [
        {
            "id": "status-field-id",
            "name": "Status",
            "dataType": "SINGLE_SELECT",
            "isIssueField": False,
            "options": status_options,
        }
    ]
    if priority_field:
        fields.append(
            {
                "id": "priority-project-field-id",
                "name": "Priority",
                "dataType": priority_type,
                "isIssueField": priority_issue_field,
                "options": [],
            }
        )
    if start_date_field:
        fields.append(
            {
                "id": "start-date-field-id",
                "name": "Start Date",
                "dataType": start_date_type,
                "isIssueField": start_date_issue_field,
            }
        )
    return {
        "organization": {
            "projectV2": {
                "id": "project-id",
                "title": "HDSH Issue Management",
                "fields": {"nodes": fields},
            }
        },
        "repository": {
            "issue": {
                "id": "issue-id",
                "projectItems": {
                    "nodes": [
                        {
                            "id": "item-id",
                            "project": {"id": "project-id"},
                            "fieldValueByName": {"name": "Inbox", "optionId": "inbox-option-id"},
                            "priorityValue": None
                            if priority is None
                            else {"name": priority, "optionId": f"{priority}-option-id"},
                            "startDateValue": None if start_date is None else {"date": start_date},
                        }
                    ]
                    if project_item
                    else []
                },
            }
        },
    }


class TestClient:
    def test_issue_snapshot_reads_project_fields(self) -> None:
        calls: list[tuple[str, str]] = []

        def rest(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            calls.append((url, str(headers and headers.get("Authorization"))))
            return 200, json.dumps(
                {
                    "node_id": "issue-id",
                    "title": "Project metadata",
                    "body": None,
                    "assignees": [],
                    "labels": [],
                    "type": {"name": "Task"},
                    "state": "open",
                    "state_reason": None,
                }
            )

        def graphql(
            url: str,
            method: str = "POST",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            calls.append((url, str(headers and headers.get("Authorization"))))
            assert body is not None
            request = json.loads(body)
            assert request["variables"]["priorityField"] == "Priority"
            return 200, json.dumps({"data": project_graphql_data(priority="P1")})

        client = make_client(routing_transport(rest, graphql))
        issue = client.issue_snapshot(42)
        assert issue is not None
        assert issue["priority"] == "P1"
        assert issue["status"] == "Inbox"
        assert calls == [
            ("https://api.github.com/repos/hdsh/hdsh/issues/42", "Bearer repository-token"),
            ("https://api.github.com/graphql", "Bearer project-token"),
        ]

    def test_issue_snapshot_ignores_pull_requests(self) -> None:
        def rest(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 200, json.dumps(
                {
                    "pull_request": {},
                    "title": "x",
                    "body": "",
                    "assignees": [],
                    "labels": [],
                    "state": "open",
                    "state_reason": None,
                }
            )

        def graphql(
            url: str,
            method: str = "POST",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            raise AssertionError("graphql must not be reached for pull requests")

        client = make_client(routing_transport(rest, graphql))
        assert client.issue_snapshot(42) is None

    def test_initialize_start_date_writes_empty_value(self) -> None:
        requests: list[dict[str, Any]] = []

        def graphql(
            url: str,
            method: str = "POST",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            assert body is not None
            request = json.loads(body)
            requests.append(request)
            if "query(" in request["query"]:
                return 200, json.dumps({"data": project_graphql_data()})
            if "addProjectV2ItemById" in request["query"]:
                return 200, json.dumps(
                    {"data": {"addProjectV2ItemById": {"item": {"id": "new-item-id"}}}}
                )
            return 200, json.dumps(
                {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "item-id"}}}}
            )

        client = make_client(routing_transport(lambda *a, **k: (200, "{}"), graphql))  # type: ignore[misc]
        client.initialize_issue_start_date(42, "2026-08-28")
        assert len(requests) == 2
        assert "ProjectV2ItemFieldDateValue" in requests[0]["query"]
        assert requests[1]["variables"] == {
            "projectId": "project-id",
            "itemId": "item-id",
            "fieldId": "start-date-field-id",
            "date": "2026-08-28",
        }

    def test_initialize_start_date_preserves_existing(self) -> None:
        def graphql(
            url: str,
            method: str = "POST",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            assert body is not None
            assert "query(" in json.loads(body)["query"]
            return 200, json.dumps({"data": project_graphql_data(start_date="2026-08-01")})

        client = make_client(routing_transport(lambda *a, **k: (200, "{}"), graphql))  # type: ignore[misc]
        client.initialize_issue_start_date(42, "2026-08-28")

    def test_initialize_start_date_adds_missing_item(self) -> None:
        requests: list[dict[str, Any]] = []

        def graphql(
            url: str,
            method: str = "POST",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            assert body is not None
            request = json.loads(body)
            requests.append(request)
            if "query(" in request["query"]:
                return 200, json.dumps({"data": project_graphql_data(project_item=False)})
            if "addProjectV2ItemById" in request["query"]:
                return 200, json.dumps(
                    {"data": {"addProjectV2ItemById": {"item": {"id": "new-item-id"}}}}
                )
            return 200, json.dumps(
                {
                    "data": {
                        "updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "new-item-id"}}
                    }
                }
            )

        client = make_client(routing_transport(lambda *a, **k: (200, "{}"), graphql))  # type: ignore[misc]
        client.initialize_issue_start_date(42, "2026-08-28")
        assert requests[1]["variables"] == {"projectId": "project-id", "contentId": "issue-id"}
        assert requests[2]["variables"]["itemId"] == "new-item-id"

    @pytest.mark.parametrize(
        ("kwargs", "pattern"),
        [
            ({"start_date_field": False}, "missing the Start Date field"),
            ({"start_date_type": "TEXT"}, "field must be Date"),
            ({"start_date_issue_field": True}, "must be a Project Date field"),
            ({"priority_field": False}, "missing the Priority field"),
            ({"priority_type": "TEXT"}, "field must be Single Select"),
            ({"priority_issue_field": True}, "must be a Project custom field"),
        ],
    )
    def test_rejects_invalid_project_fields(self, kwargs: dict[str, Any], pattern: str) -> None:
        def graphql(
            url: str,
            method: str = "POST",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            assert body is not None
            assert "query(" in json.loads(body)["query"]
            return 200, json.dumps({"data": project_graphql_data(**kwargs)})

        client = make_client(routing_transport(lambda *a, **k: (200, "{}"), graphql))  # type: ignore[misc]
        with pytest.raises(RuntimeError, match=pattern):
            client.initialize_issue_start_date(42, "2026-08-28")

    def test_run_lifecycle_issues_event_sets_status_and_audits(self) -> None:
        from tests.policy.support import with_details

        posted: list[str] = []
        mutations: list[dict[str, Any]] = []

        def rest(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if "/issues/7/comments" in url and method == "POST":
                posted.append(body or "")
                return 201, json.dumps({"id": 1})
            if method == "GET" and "/comments" in url:
                return 200, "[]"
            return 200, json.dumps(
                {
                    "node_id": "issue-id",
                    "title": "Opened work",
                    "body": with_details("Opened work."),
                    "assignees": [],
                    "labels": [{"name": "kind/feature"}],
                    "type": {"name": "Task"},
                    "state": "open",
                    "state_reason": None,
                }
            )

        def graphql(
            url: str,
            method: str = "POST",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            assert body is not None
            request = json.loads(body)
            mutations.append(request)
            if "query(" in request["query"]:
                data = project_graphql_data()
                nodes = cast(
                    "list[dict[str, Any]]",
                    data["repository"]["issue"]["projectItems"]["nodes"],
                )
                nodes[0]["fieldValueByName"] = {"name": "Backlog", "optionId": "backlog-option-id"}
                return 200, json.dumps({"data": data})
            return 200, json.dumps(
                {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "item-id"}}}}
            )

        client = make_client(routing_transport(rest, graphql))
        client.run_lifecycle(
            "issues", {"action": "opened", "issue": {"number": 7, "state_reason": None}}
        )
        assert any("singleSelectOptionId" in m["query"] for m in mutations)
        assert posted and "hdsh-issue-policy" in posted[0]

    def test_run_pull_request_check_fails_loud(self, capsys: pytest.CaptureFixture[str]) -> None:
        def rest(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if url.endswith("/pulls/9"):
                return 200, json.dumps(
                    {
                        "draft": False,
                        "user": {"type": "User"},
                        "labels": [],
                        "body": "",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                )
            if url.endswith("/requested_reviewers"):
                return 200, json.dumps({"users": [{"login": "r"}], "teams": []})
            if "/reviews" in url:
                return 200, "[]"
            if "/comments" in url:
                return 200, "[]"
            return 200, "{}"

        def graphql(
            url: str,
            method: str = "POST",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 200, json.dumps({"data": project_graphql_data()})

        client = make_client(routing_transport(rest, graphql))
        with pytest.raises(RuntimeError, match="failed with"):
            client.run_pull_request_check({"pull_request": {"number": 9}})
        assert "::error::" in capsys.readouterr().out


class TestTransportEdges:
    def test_api_error_raises_with_body(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 404, json.dumps({"message": "Not Found"})

        client = _client(transport)
        with pytest.raises(RuntimeError, match="404"):
            client._api("/repos/hdsh/hdsh/issues/1")

    def test_api_allow_404_returns_none(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 404, json.dumps({"message": "Not Found"})

        client = _client(transport)
        assert client._api("/x", allow_404=True) is None

    def test_empty_body_returns_none(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 204, ""

        client = _client(transport)
        assert client._api("/x") is None

    def test_graphql_http_error_raises(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 500, "server error"

        client = _client(transport)
        with pytest.raises(RuntimeError, match="500"):
            client._graphql("query { x }", {})

    def test_graphql_error_list_raises(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 200, json.dumps({"errors": [{"message": "bad"}, {"message": "worse"}]})

        client = _client(transport)
        with pytest.raises(RuntimeError, match="bad; worse"):
            client._graphql("query { x }", {})


class TestProjectContextEdges:
    def _graphql_client(self, data: dict[str, Any] | None) -> GitHubPolicyClient:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if data is None:
                return 200, json.dumps({"data": {}})
            return 200, json.dumps({"data": data})

        return _client(transport)

    def test_missing_project_raises(self) -> None:
        client = self._graphql_client(None)
        with pytest.raises(RuntimeError, match="Project is missing or its title"):
            client.project_context(1)

    def test_wrong_title_raises(self) -> None:
        client = self._graphql_client(project_payload(title="Other"))
        with pytest.raises(RuntimeError, match="title does not match"):
            client.project_context(1)

    def test_missing_issue_raises(self) -> None:
        payload = project_payload()
        payload["repository"] = {**cast("dict[str, Any]", payload["repository"]), "issue": None}
        client = self._graphql_client(payload)
        with pytest.raises(RuntimeError, match="does not exist"):
            client.project_context(1)

    def test_missing_status_field_raises(self) -> None:
        client = self._graphql_client(project_payload(status_field=False))
        with pytest.raises(RuntimeError, match="missing the Status field"):
            client.project_context(1)


class TestStatusAndAudit:
    def test_update_status_rejects_unknown_option(self) -> None:
        client = _graphql_client_with_data(project_payload())
        context = client.project_context(1)
        with pytest.raises(RuntimeError, match="Status does not exist"):
            client._update_status(context, "NotAStatus")

    def test_update_status_skips_when_equal(self) -> None:
        client = _graphql_client_with_data(project_payload())
        context = client.project_context(1)
        client._update_status(context, "Inbox")  # item already Inbox: no mutation

    def test_audit_issue_skips_pull_requests(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 200, json.dumps(
                {
                    "pull_request": {},
                    "title": "x",
                    "body": "",
                    "assignees": [],
                    "labels": [],
                    "state": "open",
                    "state_reason": None,
                }
            )

        client = _client(transport)
        assert client.audit_issue(1) == []

    def test_upsert_audit_deletes_stale_comment(self) -> None:
        deleted: list[str] = []

        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if method == "GET" and "/comments" in url:
                return 200, json.dumps(
                    [{"id": 7, "user": {"type": "Bot"}, "body": "<!-- hdsh-issue-policy -->\nold"}]
                )
            if method == "DELETE":
                deleted.append(url)
                return 204, ""
            raise AssertionError(url)

        client = _client(transport)
        client.upsert_audit(1, [])
        assert deleted and "/issues/comments/7" in deleted[0]

    def test_upsert_audit_keeps_identical_body(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if method == "GET":
                return 200, json.dumps(
                    [
                        {
                            "id": 7,
                            "user": {"type": "Bot"},
                            "body": "<!-- hdsh-issue-policy -->\n⚠️ Issue policy failed:\n\n- boom",
                        }
                    ]
                )
            raise AssertionError("no further calls expected")

        client = _client(transport)
        client.upsert_audit(1, ["boom"])

    def test_upsert_audit_patches_changed_body(self) -> None:
        patched: list[str] = []

        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if method == "GET":
                return 200, json.dumps(
                    [
                        {
                            "id": 7,
                            "user": {"type": "Bot"},
                            "body": "<!-- hdsh-issue-policy -->\n⚠️ Issue policy failed:\n\n- old",
                        }
                    ]
                )
            if method == "PATCH":
                patched.append(body or "")
                return 200, "{}"
            raise AssertionError(url)

        client = _client(transport)
        client.upsert_audit(1, ["new"])
        assert patched and "new" in patched[0]


class TestPullRequestFlows:
    def test_pull_request_snapshot_shapes(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if url.endswith("/pulls/3"):
                return 200, json.dumps(
                    {
                        "draft": False,
                        "user": {"type": "User"},
                        "labels": [{"name": "kind/feature"}],
                        "body": "Fixes #2",
                        "created_at": "2026-08-27T16:00:00Z",
                    }
                )
            if url.endswith("/requested_reviewers"):
                return 200, json.dumps({"users": [{"login": "a"}], "teams": [{"name": "t"}]})
            if "/reviews" in url:
                return 200, json.dumps([{"id": 1}, {"id": 2}])
            if url.endswith("/issues/2"):
                return 200, json.dumps(
                    {
                        "node_id": "n2",
                        "title": "t",
                        "body": None,
                        "assignees": [],
                        "labels": [],
                        "type": {"name": "Feature"},
                        "state": "open",
                        "state_reason": None,
                    }
                )
            if url.endswith("/graphql"):
                return 200, json.dumps({"data": project_payload()})
            raise AssertionError(url)

        client = _client(transport)
        snapshot = client.pull_request_snapshot(3)
        assert snapshot["reviewRequestCount"] == 2
        assert snapshot["reviewCount"] == 2
        assert snapshot["references"]["resolving"] == [2]
        lifecycle = client.lifecycle_pull_request_snapshot(3)
        assert lifecycle["createdAt"] == "2026-08-27T16:00:00Z"

    def test_transition_applies_forward_command(self) -> None:
        mutations: list[str] = []

        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if url.endswith("/graphql"):
                assert body is not None
                request = json.loads(body)
                if "query(" in request["query"]:
                    data = project_payload()
                    nodes = cast(
                        "list[dict[str, Any]]",
                        data["repository"]["issue"]["projectItems"]["nodes"],
                    )
                    nodes[0]["fieldValueByName"] = {
                        "name": "Inbox",
                        "optionId": "i",
                    }
                    return 200, json.dumps({"data": data})
                mutations.append(request["query"])
                return 200, json.dumps(
                    {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}}
                )
            if method == "GET" and url.endswith("/comments?per_page=100"):
                return 200, "[]"
            if method == "POST" and url.endswith("/issues/2/comments"):
                return 201, json.dumps({"id": 1})
            if method == "GET" and "/issues/" in url:
                return 200, json.dumps(
                    {
                        "node_id": "n2",
                        "title": "Valid title",
                        "body": None,
                        "assignees": [],
                        "labels": [],
                        "type": {"name": "Feature"},
                        "state": "open",
                        "state_reason": None,
                    }
                )
            raise AssertionError(url)

        client = _client(transport)
        client.transition_resolving_issues({"references": {"resolving": [2]}}, "review-requested")
        assert mutations

    def test_transition_skips_when_no_target(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if url.endswith("/graphql"):
                assert body is not None
                assert "query(" in json.loads(body)["query"]
                data = project_payload()
                nodes = cast(
                    "list[dict[str, Any]]",
                    data["repository"]["issue"]["projectItems"]["nodes"],
                )
                nodes[0]["fieldValueByName"] = {"name": "In review", "optionId": "i"}
                return 200, json.dumps({"data": data})
            raise AssertionError(url)

        client = _client(transport)
        client.transition_resolving_issues({"references": {"resolving": [2]}}, "implementation")

    def test_run_lifecycle_ignores_irrelevant_events(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            raise AssertionError("no transport calls expected")

        client = _client(transport)
        client.run_lifecycle(
            "pull_request_review",
            {"action": "submitted", "review": {"state": "approved"}, "pull_request": {"number": 1}},
        )

    def test_client_from_environment_uses_project_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "repo")
        monkeypatch.setenv("PROJECT_TOKEN", "project")
        client = client_from_environment(PolicyConfig.from_json(config_with()))
        assert client.repository_token == "repo"
        assert client.project_token == "project"


def test_client_from_environment_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GH_TOKEN or GITHUB_TOKEN"):
        client_from_environment(CONFIG)


def test_client_from_environment_falls_back_to_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "fallback")
    client = client_from_environment(CONFIG)
    assert client.repository_token == "fallback"
    assert client.project_token == "fallback"


UTC_CONFIG = json.dumps(
    {
        "organization": "hdsh",
        "repository": "hdsh",
        "projectNumber": 1,
        "projectTitle": "HDSH Issue Management",
        "lifecycleActor": "a",
        "priorityField": "Priority",
        "startDateField": "Start Date",
        "projectTimeZone": "UTC",
        "allowUnassignedOwner": True,
        "statuses": [
            "Inbox",
            "Backlog",
            "Ready",
            "In progress",
            "In review",
            "Done",
            "No action",
        ],
    }
)


def _utc_client(transport: Any) -> GitHubPolicyClient:
    return GitHubPolicyClient(PolicyConfig.from_json(UTC_CONFIG), "r", "p", transport=transport)


class TestClientBranches:
    def test_default_transport_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.error
        from io import BytesIO

        def urllib_error(code: int, body: bytes) -> Exception:
            return urllib.error.HTTPError("url", code, "x", cast("Any", None), BytesIO(body))

        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda request: (_ for _ in ()).throw(urllib_error(404, b'{"m":1}')),
        )
        client = GitHubPolicyClient(
            PolicyConfig.from_json(UTC_CONFIG),
            repository_token="r",
            project_token="p",
        )
        with pytest.raises(RuntimeError, match="404"):
            client._api("/repos/hdsh/hdsh/issues/1")

    def test_default_transport_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeResponse:
            status = 200

            def read(self) -> bytes:
                return b'{"ok": true}'

            def __enter__(self) -> FakeResponse:  # noqa: PYI034 - test double
                return self

            def __exit__(self, *args: object) -> None:
                return None

        monkeypatch.setattr("urllib.request.urlopen", lambda request: FakeResponse())
        client = GitHubPolicyClient(PolicyConfig.from_json(UTC_CONFIG), "r", "p")
        assert client._api("/x") == {"ok": True}

    def test_status_actor_from_timeline(self) -> None:
        payload = {
            "organization": {
                "projectV2": {
                    "id": "project-id",
                    "title": "HDSH Issue Management",
                    "fields": {
                        "nodes": [
                            {
                                "id": "s",
                                "name": "Status",
                                "dataType": "SINGLE_SELECT",
                                "isIssueField": False,
                                "options": [],
                            },
                            {
                                "id": "p",
                                "name": "Priority",
                                "dataType": "SINGLE_SELECT",
                                "isIssueField": False,
                                "options": [],
                            },
                        ]
                    },
                }
            },
            "repository": {
                "issue": {
                    "id": "issue-id",
                    "timelineItems": {
                        "nodes": [
                            {
                                "actor": {"login": "hdsh-issue-management"},
                                "project": {"id": "project-id"},
                                "status": "In review",
                            },
                        ]
                    },
                    "projectItems": {
                        "nodes": [
                            {
                                "id": "item-id",
                                "project": {"id": "project-id"},
                                "fieldValueByName": {"name": "In review", "optionId": "x"},
                                "priorityValue": None,
                                "startDateValue": None,
                            },
                        ]
                    },
                }
            },
        }

        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            return 200, json.dumps({"data": payload})

        client = _utc_client(transport)
        context = client.project_context(1, include_status_actor=True)
        assert context["statusActor"] == "hdsh-issue-management"

    def test_initialize_start_dates_only_on_opened(self) -> None:
        client = _utc_client(lambda *a, **k: (200, "{}"))
        writes: list[tuple[int, str]] = []

        def writer(number: int, date: str) -> None:
            writes.append((number, date))

        pull = {"createdAt": "2026-08-27T16:00:00Z", "references": {"all": [4]}}
        client.initialize_pull_request_start_dates(pull, "edited", writer)
        assert writes == []
        client.initialize_pull_request_start_dates(pull, "opened", writer)
        assert writes == [(4, "2026-08-27")]

    def test_run_lifecycle_closed_sets_terminal_status(self) -> None:
        mutations: list[dict[str, Any]] = []

        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if url.endswith("/graphql"):
                assert body is not None
                request = json.loads(body)
                mutations.append(request)
                if "query(" in request["query"]:
                    return 200, json.dumps({"data": project_graphql_data()})
                return 200, json.dumps(
                    {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}}
                )
            if method == "GET" and url.endswith("/comments?per_page=100"):
                return 200, "[]"
            return 200, json.dumps(
                {
                    "node_id": "n",
                    "title": "Closing work",
                    "body": "Summary.\n\n<details><summary>s</summary>b</details>",
                    "assignees": [],
                    "labels": [],
                    "type": {"name": "Task"},
                    "state": "closed",
                    "state_reason": "not_planned",
                }
            )

        client = _utc_client(transport)
        client.run_lifecycle(
            "issues",
            {"action": "closed", "issue": {"number": 5, "state_reason": "not_planned"}},
        )
        assert any(m["variables"].get("optionId") == "No action-option-id" for m in mutations)

    def test_run_pull_request_check_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if url.endswith("/pulls/9"):
                return 200, json.dumps(
                    {
                        "draft": False,
                        "user": {"type": "User"},
                        "labels": [{"name": "kind/feature"}, {"name": "area/infra"}],
                        "body": "Fixes #2",
                        "created_at": "2026-08-27T16:00:00Z",
                    }
                )
            if url.endswith("/requested_reviewers"):
                return 200, json.dumps({"users": [{"login": "a"}], "teams": []})
            if "/reviews" in url:
                return 200, "[]"
            if url.endswith("/issues/2"):
                return 200, json.dumps(
                    {
                        "node_id": "n2",
                        "title": "Valid title",
                        "body": "Summary.\n\n<details><summary>s</summary>b</details>",
                        "assignees": [],
                        "labels": [],
                        "type": {"name": "Feature"},
                        "state": "open",
                        "state_reason": None,
                    }
                )
            if url.endswith("/graphql"):
                return 200, json.dumps({"data": project_payload()})
            raise AssertionError(url)

        client = _client(transport)
        client.run_pull_request_check({"pull_request": {"number": 9}})
        assert "Issue policy passed." in capsys.readouterr().out

    def test_run_pull_request_check_reports_out_of_scope(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if url.endswith("/pulls/9"):
                return 200, json.dumps(
                    {
                        "draft": False,
                        "user": {"type": "User"},
                        "labels": [{"name": "kind/feature"}, {"name": "area/infra"}],
                        "body": "Fixes #2",
                        "created_at": "2026-08-27T16:00:00Z",
                    }
                )
            if url.endswith("/requested_reviewers"):
                return 200, json.dumps({"users": [], "teams": []})
            if "/reviews" in url:
                return 200, "[]"
            if url.endswith("/issues/2"):
                return 200, json.dumps(
                    {
                        "node_id": "n2",
                        "title": "Valid title",
                        "body": "Summary.\n\n<details><summary>s</summary>b</details>",
                        "assignees": [],
                        "labels": [],
                        "type": {"name": "Feature"},
                        "state": "open",
                        "state_reason": None,
                    }
                )
            if url.endswith("/graphql"):
                return 200, json.dumps({"data": project_payload()})
            raise AssertionError(url)

        client = _client(transport)
        client.run_pull_request_check({"pull_request": {"number": 9}})
        assert "not yet in the Issue policy enforcement scope." in capsys.readouterr().out

    def test_audit_valid_issue_without_existing_comment(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if method == "GET" and url.endswith("/comments?per_page=100"):
                return 200, "[]"
            return 200, json.dumps(
                {
                    "node_id": "n",
                    "title": "Valid work",
                    "body": "Summary.\n\n<details><summary>s</summary>b</details>",
                    "assignees": [],
                    "labels": [],
                    "type": {"name": "Task"},
                    "state": "open",
                    "state_reason": None,
                }
            )

        client = _client(
            routing_transport(
                transport, lambda *a, **k: (200, json.dumps({"data": project_payload()}))
            )
        )
        assert client.audit_issue(2) == []

    def test_resolving_snapshot_skips_pull_request_references(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            if url.endswith("/pulls/9"):
                return 200, json.dumps(
                    {
                        "draft": False,
                        "user": {"type": "User"},
                        "labels": [],
                        "body": "Fixes #2",
                        "created_at": "2026-08-27T16:00:00Z",
                    }
                )
            if url.endswith("/requested_reviewers"):
                return 200, json.dumps({"users": [], "teams": []})
            if "/reviews" in url:
                return 200, "[]"
            if url.endswith("/issues/2"):
                return 200, json.dumps({"pull_request": {}})
            raise AssertionError(url)

        client = _client(transport)
        snapshot = client.pull_request_snapshot(9)
        assert snapshot["references"]["all"] == []

    def test_lifecycle_returns_for_irrelevant_pull_request_action(self) -> None:
        def transport(
            url: str,
            method: str = "GET",
            body: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[int, str]:
            raise AssertionError("no transport calls expected")

        client = _client(transport)
        client.run_lifecycle(
            "pull_request", {"action": "review_request_removed", "pull_request": {"number": 1}}
        )


class _LifecycleClient:
    """Hand-rolled client double exposing the lifecycle surface."""

    def __init__(self) -> None:
        self.status_mutations: list[str] = []
        self.dates_written: list[int] = []
        self.config = PolicyConfig.from_json(UTC_CONFIG)

    def seen_status(self, name: str) -> bool:
        return name in self.status_mutations

    def set_status(self, number: int, status: str) -> None:
        self.status_mutations.append(status)

    def ensure_project_item(self, number: int, include_start_date: bool = False) -> dict[str, Any]:
        return {"item": {}}

    def audit_issue(
        self, number: int, extra_errors: list[str] | None = None, status: str | None = None
    ) -> list[str]:
        return []

    def lifecycle_pull_request_snapshot(self, number: int) -> dict[str, Any]:
        return {
            "createdAt": "2026-08-27T16:00:00Z",
            "references": {"all": [7], "resolving": [7], "related": []},
        }

    def transition_resolving_issues(self, pull: dict[str, Any], command: str) -> None:
        self.status_mutations.append(command)

    def initialize_pull_request_start_dates(
        self, pull: dict[str, Any], action: str, initialize: Any = None
    ) -> None:
        if action != "opened":
            return
        self.dates_written.extend(pull["references"]["all"])

    def run_lifecycle(self, event_name: str, event: dict[str, Any]) -> None:
        GitHubPolicyClient.run_lifecycle(self, event_name, event)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    def run_pull_request_check(self, event: dict[str, Any]) -> None:
        print("Issue policy passed.")


class TestLifecycleDispatch:
    def test_run_lifecycle_reopened_resets_to_inbox(self) -> None:
        client = _LifecycleClient()
        client.run_lifecycle("issues", {"action": "reopened", "issue": {"number": 5}})
        assert client.seen_status("Inbox")

    def test_run_lifecycle_pull_request_event_transitions_and_inits_dates(self) -> None:
        client = _LifecycleClient()
        client.run_lifecycle(
            "pull_request",
            {"action": "opened", "pull_request": {"number": 9}},
        )
        assert client.dates_written == [7]

    def test_run_lifecycle_review_event_transitions(self) -> None:
        client = _LifecycleClient()
        client.run_lifecycle(
            "pull_request_review",
            {
                "action": "submitted",
                "review": {"state": "changes_requested"},
                "pull_request": {"number": 9},
            },
        )
        assert client.status_mutations

    def test_run_lifecycle_ignores_unrelated_events(self) -> None:
        client = _LifecycleClient()
        # GitHubPolicyClient.run_lifecycle falls through for event names it
        # does not subscribe to.
        client.run_lifecycle("push", {})
