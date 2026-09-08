"""Pure validation rules and lifecycle logic for the issue/PR policy engine.

Everything here is logic plus injected configuration: body visibility,
Issue and pull-request metadata validation, reference parsing, and the
event-directed status-transition planner.
"""

from __future__ import annotations

import re
import unicodedata
import zoneinfo
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from hdsh.policy.config import PolicyConfig

BODY_LIMIT = 50
_MULTI_ASSIGNEE_MIN = 2
OWNER_LINE = re.compile(r"^Owner: @([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)$")
TYPES = frozenset({"Idea", "Feature", "Bug", "Research", "Task"})
#: User-account carrier for the Issue classification; organization accounts
#: use the native Issue Type instead.
TYPE_LABELS = {f"type/{name.lower()}": name for name in TYPES}
PRIORITIES = ("p0", "p1", "p2", "p3")
PR_KINDS = frozenset(
    {
        "kind/feature",
        "kind/bug-fix",
        "kind/doc",
        "kind/testing",
        "kind/cleanup",
        "kind/dependency",
    }
)
IMPLEMENTATION_PULL_REQUEST_ACTIONS = frozenset(
    {"opened", "edited", "synchronize", "reopened", "labeled", "unlabeled"}
)
_TITLE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:\[(?:Idea|Feature|Bug|Research|Task|P[0-3]|Inbox|Backlog|Ready|In progress"
    r"|In review|Done|No action|Owner|area/[^\]]+)[^\]]*\]|(?:Idea|Feature|Bug|Research|Task"
    r"|P[0-3]|Inbox|Backlog|Ready|In progress|In review|Done|No action|Owner"
    r"|area/[^:： ]+)\s*[:：-])",
    re.IGNORECASE,
)
#: Script=Han code-point ranges: CJK radicals, ideographic description and
#: iteration marks, the unified ideograph blocks, and their compatibility and
#: extension planes.
_HAN_RANGES = (
    (0x2E80, 0x2EFF),
    (0x2F00, 0x2FDF),
    (0x2FF0, 0x2FFF),
    (0x3005, 0x3005),
    (0x3007, 0x3007),
    (0x3021, 0x3029),
    (0x3038, 0x303A),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x2EBF0, 0x2EE5F),
    (0x2F800, 0x2FA1F),
    (0x30000, 0x3134F),
    (0x31350, 0x323AF),
)
_HAN_STARTS = tuple(start for start, _ in _HAN_RANGES)
#: Script=Latin code-point ranges covering the blocks GitHub issue bodies use.
_LATIN_RANGES = (
    (0x41, 0x5A),
    (0x61, 0x7A),
    (0xAA, 0xAA),
    (0xBA, 0xBA),
    (0xC0, 0xD6),
    (0xD8, 0xF6),
    (0xF8, 0x2B8),
    (0x1D00, 0x1D25),
    (0x1D2C, 0x1D5C),
    (0x1D62, 0x1D65),
    (0x1D6B, 0x1D77),
    (0x1D79, 0x1DBE),
    (0x1E00, 0x1EFF),
    (0x2071, 0x2071),
    (0x207F, 0x207F),
    (0x2090, 0x209C),
    (0x2170, 0x217F),
    (0x24D0, 0x24E9),
    (0x2C60, 0x2C7F),
    (0xA722, 0xA787),
    (0xA78B, 0xA7CA),
    (0xA7F5, 0xA7FF),
    (0xAB30, 0xAB5F),
    (0xFB00, 0xFB06),
    (0xFF21, 0xFF3A),
    (0xFF41, 0xFF5A),
)
_LATIN_STARTS = tuple(start for start, _ in _LATIN_RANGES)
_ASCII_TOKEN_EXTRA = frozenset("_./:@+-")
_NUMBER_CATEGORIES = frozenset({"Nd", "Nl", "No"})


def _in_ranges(
    code_point: int, starts: tuple[int, ...], ranges: tuple[tuple[int, int], ...]
) -> bool:
    index = bisect_right(starts, code_point) - 1
    return index >= 0 and code_point <= ranges[index][1]


def _is_han_char(character: str) -> bool:
    return _in_ranges(ord(character), _HAN_STARTS, _HAN_RANGES)


def _is_token_char(character: str) -> bool:
    if character in _ASCII_TOKEN_EXTRA:
        return True
    if _in_ranges(ord(character), _LATIN_STARTS, _LATIN_RANGES):
        return True
    return unicodedata.category(character) in _NUMBER_CATEGORIES


def _script_units(visible: str) -> int:
    """Count Han characters plus contiguous Latin, numeric, or code tokens."""
    han = 0
    tokens = 0
    in_token = False
    for character in visible:
        if _is_han_char(character):
            han += 1
            in_token = False
        elif _is_token_char(character):
            if not in_token:
                tokens += 1
                in_token = True
        else:
            in_token = False
    return han + tokens


@dataclass(frozen=True)
class DetailsShape:
    """Visibility computation over the Markdown outside ``<details>`` regions."""

    text: str
    balanced: bool
    details_count: int
    all_collapsed: bool


def extract_outside_details(body: str) -> DetailsShape:
    """Return Markdown outside balanced details elements.

    Args:
        body: Markdown body.

    Returns:
        Visible source and the details shape.
    """
    source = re.sub(r"<!--[\s\S]*?-->", "", body)
    tag = re.compile(r"</?details\b[^>]*>", re.IGNORECASE)
    depth = 0
    cursor = 0
    balanced = True
    text = ""
    details_count = 0
    all_collapsed = True
    for match in tag.finditer(source):
        if depth == 0:
            text += source[cursor : match.start()]
        if match.group(0).startswith("</"):
            if depth == 0:
                balanced = False
            else:
                depth -= 1
        else:
            depth += 1
            details_count += 1
            if re.search(r"\sopen(?:\s|=|>)", match.group(0), re.IGNORECASE):
                all_collapsed = False
        cursor = match.end()
    if depth == 0:
        text += source[cursor:]
    if depth != 0:
        balanced = False
    return DetailsShape(
        text=text, balanced=balanced, details_count=details_count, all_collapsed=all_collapsed
    )


@dataclass(frozen=True)
class VisibleUnits:
    """Visible unit count and details shape for one Markdown body."""

    units: int
    balanced: bool
    details_count: int
    all_collapsed: bool


def count_visible_units(body: str) -> VisibleUnits:
    """Count Chinese characters and contiguous Latin, numeric, or code tokens.

    Args:
        body: Markdown body.

    Returns:
        Visible unit count and details shape.
    """
    outside = extract_outside_details(body)
    visible = outside.text
    replacements = (
        (r"!\[([^\]]*)\]\([^)]*\)", r"\1"),
        (r"\[([^\]]+)\]\([^)]*\)", r"\1"),
        (r"\[([^\]]+)\]\[[^\]]*\]", r"\1"),
        (r"<((?:https?://|mailto:)[^>]+)>", r"\1"),
        (r"<[^>]+>", " "),
        (r"&(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);", " "),
        (r"[`*~\[\]{}()<>#!|]", " "),
    )
    for pattern, replacement in replacements:
        visible = re.sub(
            pattern, replacement, visible, flags=re.IGNORECASE if "<" in pattern else 0
        )
    units = _script_units(visible)
    return VisibleUnits(
        units=units,
        balanced=outside.balanced,
        details_count=outside.details_count,
        all_collapsed=outside.all_collapsed,
    )


def _first_nonblank_line(body: str) -> str | None:
    for line in body.splitlines():
        if line.strip():
            return line.strip()
    return None


def validate_body(
    body: str,
    assignees: list[str],
    config: PolicyConfig,
) -> list[str]:
    """Validate required body sections and check Owner against assignees.

    Args:
        body: Issue or pull-request Markdown body.
        assignees: Assignee logins.
        config: Policy configuration.

    Returns:
        Validation errors.
    """
    errors: list[str] = []
    count = count_visible_units(body)
    first_line = _first_nonblank_line(body)
    owner_match = OWNER_LINE.match(first_line) if first_line else None
    owner = owner_match.group(1) if owner_match is not None else None
    normalized = sorted({login.lower() for login in assignees})

    if not count.balanced:
        errors.append("details tags must be balanced")
    if count.details_count == 0:
        errors.append("the body must contain a default-collapsed <details> region")
    if not count.all_collapsed:
        errors.append("details regions must be collapsed by default; do not set open")
    if count.units > BODY_LIMIT:
        errors.append(f"visible body is {count.units} units, exceeding {BODY_LIMIT} units")
    if len(normalized) >= _MULTI_ASSIGNEE_MIN and owner is None:
        errors.append("with multiple assignees the first non-blank line must be Owner: @login")
    elif (
        len(normalized) >= _MULTI_ASSIGNEE_MIN
        and owner is not None
        and owner.lower() not in normalized
    ):
        errors.append("Owner must be one of the assignees")
    elif (
        len(normalized) < _MULTI_ASSIGNEE_MIN
        and owner is not None
        and not (len(normalized) == 0 and config.allow_unassigned_owner)
    ):
        errors.append("with zero or one assignee an Owner line must not be written")
    return errors


def requires_pull_request_policy(
    is_draft: bool,
    author_type: str,
    review_request_count: int,
    review_count: int,
) -> bool:
    """Decide whether the human-review policy applies to a pull request.

    Args:
        is_draft: Whether the pull request is a draft.
        author_type: ``User``, ``Bot``, or ``App``.
        review_request_count: Outstanding reviewer requests.
        review_count: Submitted reviews.

    Returns:
        Whether the pull-request policy is mandatory.
    """
    automated = author_type in ("Bot", "App")
    return not is_draft and not automated and (review_request_count > 0 or review_count > 0)


def resolving_issue_status_command(event_name: str, event: dict[str, Any]) -> str | None:
    """Translate a repository event into one resolving-Issue lifecycle command.

    Args:
        event_name: GitHub event name.
        event: GitHub event payload.

    Returns:
        ``implementation``, ``review-requested``, ``changes-requested``, or None.
    """
    if event_name == "pull_request":
        if event.get("action") == "review_requested":
            return "review-requested"
        return (
            "implementation" if event.get("action") in IMPLEMENTATION_PULL_REQUEST_ACTIONS else None
        )
    if (
        event_name == "pull_request_review"
        and event.get("action") == "submitted"
        and str(event.get("review", {}).get("state", "")).lower() == "changes_requested"
    ):
        return "changes-requested"
    return None


def next_resolving_issue_status(
    current_status: str | None,
    command: str,
    current_status_actor: str | None,
    config: PolicyConfig,
) -> str | None:
    """Plan one event-directed resolving-Issue status transition.

    Args:
        current_status: Current Project status.
        command: Lifecycle command.
        current_status_actor: Actor that last set the current status.
        config: Policy configuration.

    Returns:
        Status to write, or None when no permitted transition exists.

    Raises:
        ValueError: On an unknown lifecycle command.
    """
    if command == "review-requested":
        target = "In review"
    elif command in ("implementation", "changes-requested"):
        target = "In progress"
    else:
        msg = f"unknown lifecycle command: {command}"
        raise ValueError(msg)
    order = config.active_statuses
    if (
        command == "changes-requested"
        and current_status == "In review"
        and current_status_actor == config.lifecycle_actor
    ):
        return target
    if current_status not in order:
        return None
    current_index = order.index(current_status)
    target_index = order.index(target)
    return target if current_index < target_index else None


def project_date(timestamp: str, time_zone: str) -> str:
    """Convert a GitHub timestamp to a Project date in one configured zone.

    Args:
        timestamp: ISO timestamp.
        time_zone: IANA time-zone name.

    Returns:
        Calendar date in YYYY-MM-DD form.

    Raises:
        ValueError: When the timestamp is invalid.
    """
    try:
        instant = datetime.fromisoformat(timestamp)
    except ValueError as error:
        msg = f"invalid pull-request creation time: {timestamp}"
        raise ValueError(msg) from error
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(zoneinfo.ZoneInfo(time_zone)).strftime("%Y-%m-%d")


def _strip_ignored_markdown(body: str) -> str:
    """Drop comments, fenced blocks, and inline code spans from one body."""
    lines = re.sub(r"<!--[\s\S]*?-->", "", body).splitlines()
    kept: list[str] = []
    fence: str | None = None
    for line in lines:
        marker = re.match(r"^\s*([`~]{3,})", line)
        if marker:
            fence_char = marker.group(1)[0]
            if fence is None:
                fence = fence_char
            elif fence_char == fence:
                fence = None
            continue
        if fence is None:
            kept.append(line)
    return re.sub(r"`[^`]*`", " ", "\n".join(kept))


@dataclass(frozen=True)
class References:
    """Parsed same-repository Issue references."""

    all: list[int]
    resolving: list[int]
    related: list[int]


def parse_references(body: str, repository: str) -> References:
    """Parse same-repository resolving and informational references.

    Args:
        body: Pull-request Markdown body.
        repository: ``owner/name`` of the referencing repository.

    Returns:
        The deduplicated, sorted reference lists.
    """
    source = _strip_ignored_markdown(body)
    expected = repository.lower()
    all_refs: set[int] = set()
    resolving: set[int] = set()
    reference = re.compile(
        r"(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#|#)(\d+)"
        r"|https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/(\d+)",
        re.IGNORECASE,
    )
    closing = re.compile(
        r"\b(?:close(?:s|d)?|fix(?:es|ed)?|resolve(?:s|d)?)\s*:?\s+"
        r"(?:(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#|#)(\d+)"
        r"|https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/(\d+))",
        re.IGNORECASE,
    )
    for match in reference.finditer(source):
        explicit = (match.group(1) or match.group(3) or "").lower()
        number = int(match.group(2) or match.group(4))
        if not explicit or explicit == expected:
            all_refs.add(number)
    for match in closing.finditer(source):
        explicit = (match.group(1) or match.group(3) or "").lower()
        number = int(match.group(2) or match.group(4))
        if not explicit or explicit == expected:
            all_refs.add(number)
            resolving.add(number)
    return References(
        all=sorted(all_refs),
        resolving=sorted(resolving),
        related=sorted(all_refs - resolving),
    )


def retain_issue_references(references: References, issues: dict[int, Any]) -> References:
    """Retain only references that resolve to Issues rather than pull requests.

    Args:
        references: Parsed references.
        issues: Resolved same-repository Issues keyed by number.

    Returns:
        Issue-only references.
    """
    return References(
        all=[n for n in references.all if n in issues],
        resolving=[n for n in references.resolving if n in issues],
        related=[n for n in references.related if n in issues],
    )


def classification_from_labels(labels: list[str]) -> str | None:
    """Normalize the user-account ``type/*`` label carrier to its canonical name.

    Args:
        labels: Issue label names.

    Returns:
        The canonical classification, or ``None`` without exactly one known label.
    """
    candidates = [TYPE_LABELS[label] for label in labels if label in TYPE_LABELS]
    return candidates[0] if len(candidates) == 1 else None


def validate_issue(issue: dict[str, Any], config: PolicyConfig) -> list[str]:
    """Validate one Issue with its Project status.

    Args:
        issue: Issue snapshot with title, body, assignees, labels, type,
            priority, status, state, and stateReason. The ``type`` value is
            already normalized to its carrier-independent form: the native
            Issue Type on organization accounts, the ``type/*`` label on
            user accounts.
        config: Policy configuration.

    Returns:
        Validation errors.
    """
    errors = validate_body(issue["body"], issue["assignees"], config)
    status = issue.get("status")
    invalid_labels = [label for label in issue["labels"] if label.startswith("kind/")]
    if invalid_labels:
        errors.append(f"Issue must not use PR kind labels: {', '.join(invalid_labels)}")
    type_labels = [label for label in issue["labels"] if label.startswith("type/")]
    if config.account_type == "organization" and type_labels:
        errors.append(
            f"Issue must not use type/* labels on organization accounts: {', '.join(type_labels)}"
        )
    if _TITLE_PREFIX_PATTERN.match(issue["title"]):
        errors.append("Issue title must not carry a Type, Priority, Status, area, or Owner prefix")
    if issue.get("type") not in TYPES:
        errors.append("Type must be one of the five English Types")
    if not status or status not in config.statuses:
        errors.append("Issue must be in the Project with a legal Status")
    priority = issue.get("priority")
    if priority is not None and priority.lower() not in PRIORITIES:
        errors.append("Priority must be empty or one of P0–P3")
    if status == "Done" and (issue["state"] != "closed" or issue["stateReason"] != "completed"):
        errors.append("Done must correspond to a Completed close reason")
    if status == "No action" and (
        issue["state"] != "closed" or issue["stateReason"] != "not_planned"
    ):
        errors.append("No action must correspond to a Not planned close reason")
    if status not in ("Done", "No action") and issue["state"] != "open":
        errors.append(f"{status} must correspond to an open Issue")
    return errors


def validate_pull_request(snapshot: dict[str, Any]) -> list[str]:
    """Validate pull-request metadata and its referenced Issues.

    Args:
        snapshot: Pull-request snapshot with authorType, labels, references,
            and issues.

    Returns:
        Validation errors.
    """
    if not requires_pull_request_policy(
        is_draft=snapshot["isDraft"],
        author_type=snapshot["authorType"],
        review_request_count=snapshot["reviewRequestCount"],
        review_count=snapshot["reviewCount"],
    ):
        return []
    errors: list[str] = []
    labels = snapshot["labels"]
    references = snapshot["references"]
    kinds = [label for label in labels if label in PR_KINDS]
    unknown_kinds = [
        label for label in labels if label.startswith("kind/") and label not in PR_KINDS
    ]
    source_labels = [label for label in labels if label.startswith("source/")]
    type_labels = [label for label in labels if label.startswith("type/")]
    priorities = [label for label in labels if label in PRIORITIES]
    areas = [label for label in labels if label.startswith("area/")]

    if not references["all"]:
        errors.append("PR body must reference at least one same-repository Issue")
    if len(kinds) != 1:
        errors.append(f"PR must carry exactly one allowed kind/*, currently {len(kinds)}")
    if unknown_kinds:
        errors.append(f"PR carries unsupported kind/*: {', '.join(unknown_kinds)}")
    if source_labels:
        errors.append(f"source/* is for Issues only: {', '.join(source_labels)}")
    if type_labels:
        errors.append(f"type/* is for Issues only: {', '.join(type_labels)}")
    if len(priorities) > 1:
        errors.append(f"PR carries at most one p0–p3, currently {len(priorities)}")
    if not areas:
        errors.append("PR must carry at least one area/*")
    errors.extend(
        f"#{number} is not a same-repository Issue"
        for number in references["all"]
        if number not in snapshot["issues"]
    )

    resolving = [(n, snapshot["issues"].get(n)) for n in references["resolving"]]
    resolving = [(n, issue) for n, issue in resolving if issue is not None]
    if not resolving:
        return errors
    issue_priorities = sorted(
        (
            priority.lower()
            for priority in (issue.get("priority") for _, issue in resolving)
            if priority and priority.lower() in PRIORITIES
        ),
        key=PRIORITIES.index,
    )
    if not priorities and issue_priorities:
        errors.append(f"PR Priority should be {issue_priorities[0]}")
    elif len(priorities) == 1 and len(issue_priorities) != len(resolving):
        errors.append("a prioritized resolving PR requires every resolved Issue to set Priority")
    elif len(priorities) == 1 and priorities[0] != issue_priorities[0]:
        errors.append(f"PR Priority should be {issue_priorities[0]}")
    return errors
