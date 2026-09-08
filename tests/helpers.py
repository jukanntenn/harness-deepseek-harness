"""Shared test helpers: disposable Git repositories, pair templates, payloads."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hdsh import cliargs

if TYPE_CHECKING:
    import argparse


def parse_command(register: Callable[[Any], None], argv: list[str]) -> argparse.Namespace:
    """Parse ``argv`` through one module's registered command leaves.

    ``argv[0]`` names the command (``scope`` for the single-command domain),
    so tests exercise the real registered parser rather than a double.
    """
    parser = cliargs.ArgumentParser(prog="hdsh")
    commands = parser.add_subparsers(required=True)
    register(commands)
    return parser.parse_args(argv)


MANIFEST = {
    "excluded": [
        ".agents/rfcs/AGENTS.md",
        ".agents/rfcs/implemented/AGENTS.md",
        ".agents/rfcs/archived/AGENTS.md",
        "docs/AGENTS.md",
        "docs/i18n/terminology.md",
        "docs/i18n/style-samples.md",
    ]
}


def completed_run[T](
    completed: subprocess.CompletedProcess[T],
) -> Callable[..., subprocess.CompletedProcess[T]]:
    """A ``subprocess.run`` double whose every call returns one fixed result."""

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[T]:
        return completed

    return run


def git(
    *args: str,
    cwd: Path,
    check: bool = True,
    input: str | bytes | None = None,  # noqa: A002 - subprocess-compatible name
) -> subprocess.CompletedProcess[str]:
    """Run one Git subprocess inside ``cwd`` and return the completed process."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        check=False,
        input=input,
    )
    completed = subprocess.CompletedProcess(
        args,
        result.returncode,
        result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout,
        result.stderr.decode("utf-8") if isinstance(result.stderr, bytes) else result.stderr,
    )
    if check and completed.returncode != 0:
        raise AssertionError(f"git {args} failed: {completed.stderr}")
    return completed


class Repo:
    """Helpers over one disposable repository root."""

    def __init__(self, root: Path) -> None:
        self.root: Path = root

    def write(self, relative: str, content: str) -> Path:
        """Write one working-tree file, creating parent directories."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def add_all(self) -> None:
        """Stage every worktree change."""
        git("add", "-A", cwd=self.root)

    def commit(self, message: str = "commit") -> str:
        """Create one commit from the index and return its commit ID."""
        self.add_all()
        git("commit", "-m", message, cwd=self.root)
        return git("rev-parse", "HEAD", cwd=self.root).stdout.strip()

    def branch(self, name: str) -> None:
        """Create and check out one branch."""
        git("checkout", "-b", name, cwd=self.root)


def en_pair(zh_target: str) -> str:
    """A structurally valid English side whose switcher names ``zh_target``."""
    return (
        "# Title\n"
        "\n"
        f"English | [中文]({zh_target})\n"
        "\n"
        "Body paragraph.\n"
        "\n"
        "```python\n"
        'print("shared")\n'
        "```\n"
        "\n"
        "- one\n"
        "- two\n"
    )


def zh_pair(en_target: str) -> str:
    """A structurally valid Chinese side whose switcher names ``en_target``."""
    return (
        "# 标题\n"
        "\n"
        f"[English]({en_target}) | 中文\n"
        "\n"
        "正文段落。\n"
        "\n"
        "```python\n"
        'print("shared")\n'
        "```\n"
        "\n"
        "- 一\n"
        "- 二\n"
    )


def write_pair(
    repo: Repo,
    anchor: str,
    *,
    source: Callable[[str], str] | None = None,
    zh: Callable[[str], str] | None = None,
) -> None:
    """Write a plausible bilingual pair without its sidecar.

    ``source``/``zh`` default to the structurally valid templates; both take
    the switcher target as produced from ``anchor``.
    """
    stem = anchor[: -len(".md")]
    name = anchor.rsplit("/", 1)[-1][: -len(".md")]
    repo.write(anchor, (source or en_pair)(f"{name}.zh.md"))
    repo.write(f"{stem}.zh.md", (zh or zh_pair)(f"{name}.md"))


#: Fixed templates for the canonical ``docs/guide.md`` pair.
EN_PAIR = en_pair("guide.zh.md")
ZH_PAIR = zh_pair("guide.md")


#: Well-formed RFC bodies for the format gate tests.
VALID_IMPLEMENTED = """# RFC: Sample decision

Status: implemented

English | [中文](sample.zh.md)

## Problem

Something needed a decision.

## Decision

We decided the thing.

## Alternatives considered

**Do nothing.** It left the problem unsolved.

## Consequences

The thing is decided.
"""

VALID_PROPOSED = """# RFC: Sample proposal

Status: proposed

English | [中文](sample.zh.md)

## Problem

Something needs a proposal.

## Proposal

We propose the thing.

## Alternatives considered

**Do nothing.** It leaves the problem unsolved.

## Acceptance criteria

The gate passes.

## Risks

The thing might be wrong.
"""

VALID_REJECTED = """# RFC: Sample rejection

Status: rejected — the mechanism it enabled was removed

English | [中文](sample.zh.md)

## Problem

Something was proposed.

## Proposal

We proposed the thing.

## Alternatives considered

**Do nothing.** It leaves the problem unsolved.

## Acceptance criteria

The gate passes.

## Risks

The thing might be wrong.
"""


def project_payload(
    *,
    title: str | None = "HDSH Issue Management",
    status_field: bool = True,
    account: str = "organization",
) -> dict[str, Any]:
    """A minimal ProjectV2 GraphQL response for policy-client tests."""

    fields: list[dict[str, object]] = []
    if status_field:
        fields.append(
            {
                "id": "s",
                "name": "Status",
                "dataType": "SINGLE_SELECT",
                "isIssueField": False,
                "options": [
                    {"id": f"{s}-i", "name": s}
                    for s in (
                        "Inbox",
                        "Backlog",
                        "Ready",
                        "In progress",
                        "In review",
                        "Done",
                        "No action",
                    )
                ],
            }
        )
    fields.append(
        {
            "id": "p",
            "name": "Priority",
            "dataType": "SINGLE_SELECT",
            "isIssueField": False,
            "options": [],
        }
    )
    return {
        account: {"projectV2": {"id": "project-id", "title": title, "fields": {"nodes": fields}}},
        "repository": {
            "issue": {
                "id": "issue-id",
                "projectItems": {
                    "nodes": [
                        {
                            "id": "item-id",
                            "project": {"id": "project-id"},
                            "fieldValueByName": {"name": "Inbox", "optionId": "i"},
                            "priorityValue": None,
                            "startDateValue": None,
                        }
                    ]
                },
            }
        },
    }


def write_manifest(repo: Repo, manifest: dict[str, object] | None = None) -> None:
    """(Re)write the disposable repository's pairing manifest."""
    payload = json.dumps(MANIFEST if manifest is None else manifest, indent=2) + "\n"
    (repo.root / ".hdsh" / "pairing.manifest.json").write_text(payload, encoding="utf-8")


def sealed_sides(archive_date: str = "2026-02-01") -> tuple[str, str]:
    """A valid sealed English/Chinese pair for ``2026-01-01-sample`` triplets."""
    source = (
        f"# RFC: Sample decision\n"
        "\n"
        "Status: implemented\n"
        f"Archived: {archive_date}\n"
        "\n"
        "English | [中文](2026-01-01-sample.zh.md)\n"
        "\n"
        "## Problem\n"
        "\n"
        "Something needed a decision.\n"
        "\n"
        "## Decision\n"
        "\n"
        "We decided the thing.\n"
        "\n"
        "## Alternatives considered\n"
        "\n"
        "**Do nothing.** It left the problem unsolved.\n"
        "\n"
        "## Consequences\n"
        "\n"
        "The thing is decided.\n"
    )
    zh = (
        f"# RFC: 示例决策\n"
        "\n"
        "Status: implemented\n"
        f"Archived: {archive_date}\n"
        "\n"
        "[English](2026-01-01-sample.md) | 中文\n"
        "\n"
        "## Problem\n"
        "\n"
        "某件事需要决策。\n"
        "\n"
        "## Decision\n"
        "\n"
        "我们决定了这件事。\n"
        "\n"
        "## Alternatives considered\n"
        "\n"
        "**什么都不做。** 问题仍未解决。\n"
        "\n"
        "## Consequences\n"
        "\n"
        "这件事已决定。\n"
    )
    return source, zh


def sidecar_for(source: str, zh: str) -> str:
    """The consistency sidecar recording both sides' current blob hashes."""
    from hdsh.rfc.archive import blob_hash

    source_bytes = source.encode("utf-8")
    zh_bytes = zh.encode("utf-8")
    return (
        "# Bilingual-pair consistency record (docs/i18n/README.md).\n"
        f"2026-01-01-sample.md: {blob_hash(source_bytes)}\n"
        f"2026-01-01-sample.zh.md: {blob_hash(zh_bytes)}\n"
    )


def write_sealed_triplet(
    repo: Repo,
    *,
    archive_date: str = "2026-02-01",
    note_class: str = "process",
    source: str | None = None,
    zh: str | None = None,
    sidecar: str | None = None,
) -> None:
    """Write one complete, well-formed sealed triplet under ``archived/``."""
    default_source, default_zh = sealed_sides(archive_date)
    base = f".agents/rfcs/archived/{note_class}/2026-01-01-sample"
    repo.write(f"{base}.md", source if source is not None else default_source)
    repo.write(f"{base}.zh.md", zh if zh is not None else default_zh)
    final_source = repo.root / f"{base}.md"
    final_zh = repo.root / f"{base}.zh.md"
    if sidecar is None:
        source_text = final_source.read_text(encoding="utf-8")
        zh_text = final_zh.read_text(encoding="utf-8")
        sidecar = sidecar_for(source_text, zh_text)
    repo.write(f"{base}.i18n.yaml", sidecar)
