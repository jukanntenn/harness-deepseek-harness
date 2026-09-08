"""Validated repository, Project, and lifecycle configuration."""

from __future__ import annotations

import json
import zoneinfo
from dataclasses import dataclass

TERMINAL_STATUSES = frozenset({"Done", "No action"})


ACCOUNT_TYPES = frozenset({"organization", "user"})


@dataclass(frozen=True)
class PolicyConfig:
    """Repository, Project, and lifecycle settings for the policy engine."""

    owner: str
    account_type: str
    repository: str
    project_number: int
    project_title: str
    lifecycle_actor: str
    priority_field: str
    start_date_field: str
    project_time_zone: str
    statuses: tuple[str, ...]
    allow_unassigned_owner: bool = False

    @classmethod
    def from_json(cls, content: str) -> PolicyConfig:
        """Parse and validate the checked-in policy configuration.

        Args:
            content: Complete ``config.json`` text.

        Returns:
            The validated configuration.

        Raises:
            ValueError: When required settings are missing, malformed, or
                inconsistent.
        """
        value = json.loads(content)
        if not isinstance(value, dict):
            # Misconfiguration surfaces as the domain's ValueError, not a TypeError.
            msg = "policy configuration must be a JSON object"
            raise ValueError(msg)  # noqa: TRY004
        for field in (
            "owner",
            "accountType",
            "repository",
            "projectTitle",
            "lifecycleActor",
            "priorityField",
            "startDateField",
            "projectTimeZone",
        ):
            if not isinstance(value.get(field), str):
                msg = f"config.{field} must be a string"
                raise ValueError(msg)  # noqa: TRY004
        if value["accountType"] not in ACCOUNT_TYPES:
            msg = f"config.accountType must be one of {sorted(ACCOUNT_TYPES)}"
            raise ValueError(msg)
        project_number = value.get("projectNumber")
        if not isinstance(project_number, int) or isinstance(project_number, bool):
            msg = "config.projectNumber must be an integer"
            raise ValueError(msg)  # noqa: TRY004
        statuses = value.get("statuses")
        if not isinstance(statuses, list) or not all(isinstance(s, str) for s in statuses):
            msg = "config.statuses must be a list of strings"
            raise ValueError(msg)
        allow_unassigned_owner = value.get("allowUnassignedOwner", False)
        if not isinstance(allow_unassigned_owner, bool):
            msg = "config.allowUnassignedOwner must be a boolean"
            raise ValueError(msg)  # noqa: TRY004
        config = cls(
            owner=value["owner"],
            account_type=value["accountType"],
            repository=value["repository"],
            project_number=project_number,
            project_title=value["projectTitle"],
            lifecycle_actor=value["lifecycleActor"],
            priority_field=value["priorityField"],
            start_date_field=value["startDateField"],
            project_time_zone=value["projectTimeZone"],
            statuses=tuple(statuses),
            allow_unassigned_owner=allow_unassigned_owner,
        )
        for status in ("In progress", "In review"):
            if status not in config.active_statuses:
                msg = f"config.statuses is missing {status}"
                raise ValueError(msg)
        if not config.lifecycle_actor:
            msg = "config.lifecycleActor is not set"
            raise ValueError(msg)
        if not config.priority_field:
            msg = "config.priorityField is not set"
            raise ValueError(msg)
        if not config.start_date_field:
            msg = "config.startDateField is not set"
            raise ValueError(msg)
        if not config.project_time_zone:
            msg = "config.projectTimeZone is not set"
            raise ValueError(msg)
        zoneinfo.ZoneInfo(config.project_time_zone)
        return config

    @property
    def active_statuses(self) -> tuple[str, ...]:
        """Non-terminal statuses in board order."""
        return tuple(s for s in self.statuses if s not in TERMINAL_STATUSES)
