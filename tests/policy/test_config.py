"""Policy configuration parsing and validation."""

from __future__ import annotations

import json

import pytest

from hdsh.policy.config import PolicyConfig
from tests.policy.support import config_with


class TestPolicyConfigValidation:
    def test_rejects_missing_lifecycle_actor(self) -> None:
        with pytest.raises(ValueError, match="lifecycleActor"):
            PolicyConfig.from_json(config_with(lifecycleActor=""))

    def test_rejects_missing_priority_field(self) -> None:
        with pytest.raises(ValueError, match="priorityField"):
            PolicyConfig.from_json(config_with(priorityField=""))

    def test_rejects_missing_start_date_field(self) -> None:
        with pytest.raises(ValueError, match="startDateField"):
            PolicyConfig.from_json(config_with(startDateField=""))

    def test_rejects_missing_time_zone(self) -> None:
        with pytest.raises(ValueError, match="projectTimeZone"):
            PolicyConfig.from_json(config_with(projectTimeZone=""))

    def test_rejects_unknown_time_zone(self) -> None:
        with pytest.raises(Exception, match="Olympus"):
            PolicyConfig.from_json(config_with(projectTimeZone="Mars/Olympus"))

    def test_rejects_bad_json(self) -> None:
        with pytest.raises(ValueError, match="config.organization"):
            PolicyConfig.from_json("{}")

    def test_config_requires_active_statuses(self) -> None:
        content = json.dumps(
            {
                "organization": "o",
                "repository": "r",
                "projectNumber": 1,
                "projectTitle": "T",
                "lifecycleActor": "a",
                "priorityField": "Priority",
                "startDateField": "Start Date",
                "projectTimeZone": "UTC",
                "statuses": ["Inbox", "Done"],
            }
        )
        with pytest.raises(ValueError, match="missing In progress"):
            PolicyConfig.from_json(content)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("organization", None),
            ("projectTitle", 3),
            ("lifecycleActor", None),
            ("priorityField", ""),
            ("startDateField", 1.5),
            ("projectTimeZone", []),
        ],
    )
    def test_rejects_non_string_settings(self, field: str, value: object) -> None:
        with pytest.raises(ValueError, match=f"config.{field}"):
            PolicyConfig.from_json(config_with(**{field: value}))  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", ["1", None, 1.0, True])
    def test_rejects_non_integer_project_number(self, value: object) -> None:
        with pytest.raises(ValueError, match="config.projectNumber"):
            PolicyConfig.from_json(config_with(projectNumber=value))  # type: ignore[arg-type]

    def test_rejects_non_list_statuses(self) -> None:
        with pytest.raises(ValueError, match="config.statuses"):
            PolicyConfig.from_json(config_with(statuses="Inbox"))  # type: ignore[arg-type]

    def test_rejects_non_string_status_entries(self) -> None:
        with pytest.raises(ValueError, match="config.statuses"):
            PolicyConfig.from_json(config_with(statuses=["Inbox", 3]))  # type: ignore[arg-type]

    def test_rejects_non_boolean_allow_unassigned_owner(self) -> None:
        with pytest.raises(ValueError, match="config.allowUnassignedOwner"):
            PolicyConfig.from_json(config_with(allowUnassignedOwner="yes"))  # type: ignore[arg-type]

    def test_rejects_non_object_payload(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            PolicyConfig.from_json("[]")
