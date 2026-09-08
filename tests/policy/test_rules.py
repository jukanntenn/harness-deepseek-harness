"""Pure policy rules: bodies, Issues, pull requests, references, lifecycle."""

from __future__ import annotations

import pytest

from hdsh.policy.config import PolicyConfig
from hdsh.policy.rules import (
    References,
    count_visible_units,
    next_resolving_issue_status,
    parse_references,
    project_date,
    requires_pull_request_policy,
    resolving_issue_status_command,
    retain_issue_references,
    validate_body,
    validate_issue,
    validate_pull_request,
)
from tests.policy.support import CONFIG, LEGAL_ISSUE, reviewed_pull, with_details

CANONICAL_KINDS = [
    "kind/feature",
    "kind/bug-fix",
    "kind/doc",
    "kind/testing",
    "kind/cleanup",
    "kind/dependency",
]


class TestVisibleUnits:
    def test_counts_only_text_outside_details(self) -> None:
        assert (
            count_visible_units("Supports GitHub Project.<details>hidden words</details>").units
            == 3
        )

    def test_details_shape(self) -> None:
        units = count_visible_units("words\n\n<details><summary>s</summary>body</details>\n")
        assert (units.balanced, units.details_count, units.all_collapsed) == (True, 1, True)

    def test_images_links_and_entities(self) -> None:
        units = count_visible_units("![alt](img.png) [text](a.md) &amp; <b>x</b> `code`")
        assert units.units >= 3

    def test_reference_link_text(self) -> None:
        assert count_visible_units("[text][ref]").units >= 1

    def test_autolink_and_mailto(self) -> None:
        assert count_visible_units("<https://x.example> <mailto:a@b.example>").units >= 2

    def test_counts_han_beyond_the_basic_plane_and_accented_latin(self) -> None:
        assert count_visible_units("𠀀形").units == 2
        assert count_visible_units("café").units == 1
        assert count_visible_units("α β").units == 0
        assert count_visible_units("〇").units == 1


class TestValidateBody:
    def test_requires_details_region(self) -> None:
        assert validate_body("Finish the work.", [], CONFIG) == [
            "the body must contain a default-collapsed <details> region"
        ]

    def test_rejects_open_details(self) -> None:
        assert validate_body(
            "Finish the work.\n\n<details open><summary>s</summary>body</details>", [], CONFIG
        ) == ["details regions must be collapsed by default; do not set open"]

    def test_rejects_unbalanced_details(self) -> None:
        assert validate_body("Finish.\n\n<details><summary>s</summary>", [], CONFIG) == [
            "details tags must be balanced"
        ]

    def test_requires_owner_for_multiple_assignees(self) -> None:
        assert validate_body(
            with_details("Finish the work."), ["tianyicui", "tianyicui-bot"], CONFIG
        ) == ["with multiple assignees the first non-blank line must be Owner: @login"]

    def test_owner_must_be_an_assignee(self) -> None:
        assert validate_body(
            with_details("Owner: @octocat\n\nFinish."), ["tianyicui", "hubot"], CONFIG
        ) == ["Owner must be one of the assignees"]

    def test_accepts_intended_owner_while_unassigned(self) -> None:
        assert validate_body(with_details("Owner: @octocat\n\nFinish."), [], CONFIG) == []

    def test_rejects_owner_with_single_assignee(self) -> None:
        assert validate_body(with_details("Owner: @octocat\n\nFinish."), ["hubot"], CONFIG) == [
            "with zero or one assignee an Owner line must not be written"
        ]

    def test_body_limit(self) -> None:
        long_body = with_details("word " * 60)
        errors = validate_body(long_body, [], CONFIG)
        assert any("exceeding 50 units" in error for error in errors)


class TestValidateIssue:
    def test_legal_issue(self) -> None:
        assert validate_issue(LEGAL_ISSUE, CONFIG) == []

    def test_every_open_status_is_legal(self) -> None:
        for status in ("Inbox", "Backlog", "Ready", "In progress", "In review"):
            assert validate_issue({**LEGAL_ISSUE, "status": status}, CONFIG) == []

    def test_title_language_is_unrestricted(self) -> None:
        assert validate_issue({**LEGAL_ISSUE, "title": "完成议题管理校验"}, CONFIG) == []
        assert validate_issue({**LEGAL_ISSUE, "title": "Fix the restore bug"}, CONFIG) == []

    def test_rejects_metadata_prefix(self) -> None:
        errors = validate_issue({**LEGAL_ISSUE, "title": "[Bug] fix restore error"}, CONFIG)
        assert (
            "Issue title must not carry a Type, Priority, Status, area, or Owner prefix" in errors
        )

    def test_rejects_pr_kind_labels(self) -> None:
        for label in [*CANONICAL_KINDS, "kind/experimental"]:
            errors = validate_issue({**LEGAL_ISSUE, "labels": [label]}, CONFIG)
            assert any(e.startswith("Issue must not use PR kind labels:") for e in errors)

    def test_allows_area_and_source_labels(self) -> None:
        assert (
            validate_issue({**LEGAL_ISSUE, "labels": ["area/infra", "source/member"]}, CONFIG) == []
        )

    def test_requires_native_type(self) -> None:
        errors = validate_issue({**LEGAL_ISSUE, "type": "Epic"}, CONFIG)
        assert "Type must be one of the five native English Types" in errors

    def test_none_type_reports_type(self) -> None:
        issue = {
            "title": "Work item",
            "body": "x\n\n<details><summary>s</summary>b</details>",
            "assignees": [],
            "labels": [],
            "type": None,
            "priority": None,
            "status": "Inbox",
            "state": "open",
            "stateReason": None,
        }
        errors = validate_issue(issue, CONFIG)
        assert any("Type" in e for e in errors)

    def test_requires_project_status(self) -> None:
        errors = validate_issue({**LEGAL_ISSUE, "status": None}, CONFIG)
        assert any("Project" in error for error in errors)

    def test_rejects_bad_priority(self) -> None:
        errors = validate_issue({**LEGAL_ISSUE, "priority": "P9"}, CONFIG)
        assert "Priority must be empty or one of P0–P3" in errors

    def test_done_requires_completed_close(self) -> None:
        assert (
            validate_issue(
                {**LEGAL_ISSUE, "status": "Done", "state": "closed", "stateReason": "completed"},
                CONFIG,
            )
            == []
        )
        errors = validate_issue({**LEGAL_ISSUE, "status": "Done"}, CONFIG)
        assert "Done must correspond to a Completed close reason" in errors

    def test_no_action_requires_not_planned(self) -> None:
        assert (
            validate_issue(
                {
                    **LEGAL_ISSUE,
                    "status": "No action",
                    "state": "closed",
                    "stateReason": "not_planned",
                },
                CONFIG,
            )
            == []
        )
        errors = validate_issue(
            {**LEGAL_ISSUE, "status": "No action", "state": "closed", "stateReason": "completed"},
            CONFIG,
        )
        assert "No action must correspond to a Not planned close reason" in errors

    def test_open_statuses_require_open_state(self) -> None:
        errors = validate_issue({**LEGAL_ISSUE, "state": "closed"}, CONFIG)
        assert errors and any("must correspond to an open Issue" in e for e in errors)


class TestReferences:
    def test_separates_resolving_and_informational(self) -> None:
        references = parse_references(
            "Fixes #12\nRelated to #4\nRefs hdsh/dsh-test#7", "hdsh/dsh-test"
        )
        assert (references.all, references.resolving, references.related) == (
            [4, 7, 12],
            [12],
            [4, 7],
        )

    def test_foreign_repository_reference_is_ignored(self) -> None:
        references = parse_references("Fixes other/repo#3\nFixes #4", "hdsh/dsh-test")
        assert (references.all, references.resolving, references.related) == ([4], [4], [])

    def test_urls_and_fences(self) -> None:
        body = "Fixes https://github.com/hdsh/dsh-test/issues/9\n```\nFixes #1\n```\n"
        references = parse_references(body, "hdsh/dsh-test")
        assert (references.all, references.resolving, references.related) == ([9], [9], [])

    def test_retain_issue_references(self) -> None:
        references = References(all=[123, 1180, 1181], resolving=[123, 1180], related=[1181])
        retained = retain_issue_references(references, {1180: {}, 1181: {}})
        assert (retained.all, retained.resolving, retained.related) == (
            [1180, 1181],
            [1180],
            [1181],
        )


class TestLifecycle:
    def test_project_date_converts_to_configured_zone(self) -> None:
        assert project_date("2026-08-27T15:59:59Z", "Asia/Shanghai") == "2026-08-27"
        assert project_date("2026-08-27T16:00:00Z", "Asia/Shanghai") == "2026-08-28"

    def test_project_date_rejects_invalid(self) -> None:
        with pytest.raises(ValueError, match="invalid pull-request creation time"):
            project_date("invalid", "Asia/Shanghai")

    def test_naive_timestamp_is_assumed_utc(self) -> None:
        assert project_date("2026-08-27T23:30:00", "Asia/Shanghai") == "2026-08-28"

    def test_policy_scope(self) -> None:
        assert requires_pull_request_policy(False, "User", 1, 0)
        assert not requires_pull_request_policy(False, "User", 0, 0)
        assert not requires_pull_request_policy(True, "User", 1, 0)
        assert not requires_pull_request_policy(False, "Bot", 1, 0)
        assert requires_pull_request_policy(False, "User", 0, 1)

    def test_explicit_review_handoffs_map_to_commands(self) -> None:
        assert (
            resolving_issue_status_command("pull_request", {"action": "review_requested"})
            == "review-requested"
        )
        assert (
            resolving_issue_status_command(
                "pull_request_review",
                {"action": "submitted", "review": {"state": "changes_requested"}},
            )
            == "changes-requested"
        )
        for state in ("approved", "commented"):
            assert (
                resolving_issue_status_command(
                    "pull_request_review", {"action": "submitted", "review": {"state": state}}
                )
                is None
            )
        assert (
            resolving_issue_status_command(
                "pull_request_review",
                {"action": "dismissed", "review": {"state": "changes_requested"}},
            )
            is None
        )

    def test_ordinary_events_are_implementation_signals(self) -> None:
        for action in ("opened", "edited", "synchronize", "reopened", "labeled", "unlabeled"):
            assert (
                resolving_issue_status_command("pull_request", {"action": action})
                == "implementation"
            )
        assert (
            resolving_issue_status_command("pull_request", {"action": "review_request_removed"})
            is None
        )

    def test_forward_transitions(self) -> None:
        for status in ("Inbox", "Backlog", "Ready"):
            assert (
                next_resolving_issue_status(status, "implementation", None, CONFIG) == "In progress"
            )
            assert (
                next_resolving_issue_status(status, "review-requested", None, CONFIG) == "In review"
            )
            assert (
                next_resolving_issue_status(status, "changes-requested", None, CONFIG)
                == "In progress"
            )

    def test_automation_owned_backward_transition(self) -> None:
        status = next_resolving_issue_status(
            "In review", "changes-requested", "hdsh-issue-management", CONFIG
        )
        assert status == "In progress"
        assert next_resolving_issue_status(status, "review-requested", None, CONFIG) == "In review"

    def test_preserves_human_and_terminal_states(self) -> None:
        assert next_resolving_issue_status("In progress", "implementation", None, CONFIG) is None
        assert next_resolving_issue_status("In review", "implementation", None, CONFIG) is None
        assert next_resolving_issue_status("In review", "review-requested", None, CONFIG) is None
        assert (
            next_resolving_issue_status("In review", "changes-requested", "tianyicui", CONFIG)
            is None
        )
        assert next_resolving_issue_status("In review", "changes-requested", None, CONFIG) is None
        assert next_resolving_issue_status("Done", "review-requested", None, CONFIG) is None
        assert next_resolving_issue_status("No action", "changes-requested", None, CONFIG) is None
        assert next_resolving_issue_status(None, "review-requested", None, CONFIG) is None

    def test_unknown_command_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown lifecycle command"):
            next_resolving_issue_status("Inbox", "bogus", None, CONFIG)


class TestValidatePullRequest:
    def test_informational_references_without_constraints(self) -> None:
        errors = validate_pull_request(
            {
                "isDraft": False,
                "authorType": "User",
                "reviewRequestCount": 1,
                "reviewCount": 0,
                "labels": ["kind/cleanup", "area/infra"],
                "references": {"all": [4], "resolving": [], "related": [4]},
                "issues": {4: {"type": "Bug", "priority": "P0", "labels": ["area/web"]}},
            }
        )
        assert errors == []

    def test_highest_resolving_priority(self) -> None:
        pull = {
            "isDraft": False,
            "authorType": "User",
            "reviewRequestCount": 0,
            "reviewCount": 1,
            "labels": ["kind/cleanup", "p0", "area/web"],
            "references": {"all": [2, 3], "resolving": [2, 3], "related": []},
            "issues": {
                2: {"type": "Feature", "priority": "P2"},
                3: {"type": "Bug", "priority": "P0"},
            },
        }
        assert validate_pull_request(pull) == []
        assert "PR Priority should be p0" in validate_pull_request(
            {**pull, "labels": ["kind/cleanup", "p2", "area/web"]}
        )

    def test_exempted_prs(self) -> None:
        invalid = {
            "isDraft": False,
            "labels": [],
            "references": {"all": [], "resolving": [], "related": []},
            "issues": {},
            "reviewRequestCount": 1,
            "reviewCount": 0,
            "authorType": "User",
        }
        assert validate_pull_request({**invalid, "authorType": "Bot"}) == []
        assert validate_pull_request({**invalid, "authorType": "App"}) == []
        assert validate_pull_request({**invalid, "isDraft": True}) == []
        assert validate_pull_request(invalid)

    def test_label_requirements(self) -> None:
        errors = validate_pull_request(reviewed_pull([]))
        assert "PR must carry exactly one allowed kind/*, currently 0" in errors
        assert "PR must carry at least one area/*" in errors

    def test_canonical_kinds_accepted(self) -> None:
        for kind in CANONICAL_KINDS:
            assert validate_pull_request(reviewed_pull([kind, "area/future-domain"])) == []

    def test_rejects_multiple_unknown_and_source(self) -> None:
        assert "PR must carry exactly one allowed kind/*, currently 2" in validate_pull_request(
            reviewed_pull(["kind/feature", "kind/doc", "area/web"])
        )
        assert "PR carries unsupported kind/*: kind/experimental" in validate_pull_request(
            reviewed_pull(["kind/experimental", "area/web"])
        )
        assert "source/* is for Issues only: source/internal-pr" in validate_pull_request(
            reviewed_pull(["kind/feature", "area/web", "source/internal-pr"])
        )

    def test_multiple_priorities_rejected(self) -> None:
        errors = validate_pull_request(reviewed_pull(["kind/feature", "area/web", "p0", "p1"]))
        assert any("at most one p0–p3" in e for e in errors)

    def test_reference_must_be_issue(self) -> None:
        errors = validate_pull_request(
            {
                "isDraft": False,
                "authorType": "User",
                "reviewRequestCount": 1,
                "reviewCount": 0,
                "labels": ["kind/feature", "area/web"],
                "references": {"all": [9], "resolving": [], "related": [9]},
                "issues": {},
            }
        )
        assert "#9 is not a same-repository Issue" in errors

    def test_priority_sync_with_resolving_issues(self) -> None:
        pull = reviewed_pull(["kind/feature", "area/web"])
        pull["references"] = {"all": [2], "resolving": [2], "related": []}
        pull["issues"] = {2: {"priority": None}}
        assert validate_pull_request(pull) == []
        assert "PR Priority should be p2" in validate_pull_request(
            {**pull, "issues": {2: {"priority": "P2"}}}
        )
        assert (
            "a prioritized resolving PR requires every resolved Issue to set Priority"
            in validate_pull_request(
                {
                    **pull,
                    "labels": ["kind/feature", "area/web", "p2"],
                    "issues": {2: {"priority": None}},
                }
            )
        )

    def test_non_priority_issue_values_are_tolerated(self) -> None:
        pull = reviewed_pull(["kind/feature", "area/web"])
        pull["references"] = {"all": [2], "resolving": [2], "related": []}
        pull["issues"] = {2: {"priority": "P9"}}
        assert validate_pull_request(pull) == []
        assert (
            "a prioritized resolving PR requires every resolved Issue to set Priority"
            in validate_pull_request({**pull, "labels": ["kind/feature", "area/web", "p0"]})
        )
        mixed = {
            **pull,
            "references": {"all": [2, 3], "resolving": [2, 3], "related": []},
            "issues": {2: {"priority": "P2"}, 3: {"priority": "custom"}},
        }
        assert "PR Priority should be p2" in validate_pull_request(mixed)


class TestRuleEdges:
    def test_details_close_without_open(self) -> None:
        units = count_visible_units("x</details>y")
        assert units.balanced is False

    def test_validate_body_owner_in_assignees_branch(self) -> None:
        config = PolicyConfig.from_json(
            '{"organization": "o", "repository": "r", "projectNumber": 1, "projectTitle": "T",'
            ' "lifecycleActor": "a", "priorityField": "Priority", "startDateField": "Start Date",'
            ' "projectTimeZone": "UTC", "statuses": ["In progress", "In review", "Done"]}'
        )
        body = "Owner: @alice\n\nSummary.\n\n<details><summary>s</summary>b</details>"
        assert validate_body(body, ["alice", "bob"], config) == []

    def test_validate_issue_closed_non_terminal(self) -> None:
        config = PolicyConfig.from_json(
            '{"organization": "o", "repository": "r", "projectNumber": 1, "projectTitle": "T",'
            ' "lifecycleActor": "a", "priorityField": "Priority", "startDateField": "Start Date",'
            ' "projectTimeZone": "UTC", "statuses": ["In progress", "In review", "Done"]}'
        )
        issue = {
            "title": "Closed work",
            "body": "S.\n\n<details><summary>s</summary>b</details>",
            "assignees": [],
            "labels": [],
            "type": "Task",
            "priority": None,
            "status": "In progress",
            "state": "closed",
            "stateReason": "completed",
        }
        assert any("open Issue" in e for e in validate_issue(issue, config))

    def test_first_nonblank_skips_blank_lines(self) -> None:
        config = PolicyConfig.from_json(
            '{"organization": "o", "repository": "r", "projectNumber": 1, "projectTitle": "T",'
            ' "lifecycleActor": "a", "priorityField": "Priority", "startDateField": "Start Date",'
            ' "projectTimeZone": "UTC", "statuses": ["In progress", "In review", "Done"]}'
        )
        body = "\n\nSummary.\n\n<details><summary>s</summary>b</details>"
        errors = validate_body(body, [], config)
        assert all("Owner" not in e for e in errors)

    def test_mismatched_fence_close_continues(self) -> None:
        body = "```\ncode\n~~~\nFixes #1\n```\n"
        assert parse_references(body, "hdsh/hdsh").all == []
