"""The adoptable corpus: mirrored files, templates, and their rendering.

Everything a consumer needs travels as package data inside this domain,
versioned with the installed hdsh. Mirrors are byte-equal copies of live
repository files (proven by an executed gate in this repository); templates
carry ``__HDSH_<NAME>__`` tokens that rendering replaces; link rewriting
points references into this repository's own content at tagged upstream URLs
so the consumer's links gate stays green.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

HDSH_REPOSITORY = "jukanntenn/harness-deepseek-harness"
UPSTREAM_BLOB_ROOT = f"https://github.com/{HDSH_REPOSITORY}/blob"

#: Marker pair around the adopt-managed prek block; the block is replaced
#: whole on every apply, never merged line-by-line.
MANAGED_PREK_BEGIN = "# BEGIN hdsh adopt (managed by hdsh adopt apply)"
MANAGED_PREK_END = "# END hdsh adopt"

GITATTRIBUTES_DRIVER_LINE = "*.i18n.yaml merge=hdsh-pairing"

STANDARD_STATUSES: tuple[str, ...] = (
    "Inbox",
    "Backlog",
    "Ready",
    "In progress",
    "In review",
    "Done",
    "No action",
)

#: The adopt-decision RFC anchor; the date is the adoption date.
ADOPT_RFC_ANCHOR = ".agents/rfcs/implemented/process/{date}-adopting-the-hdsh-harness.md"

#: Live repository files mirrored verbatim: mechanism and skill instruction
#: files that carry no consumer-specific content and no pairing record.
MIRRORED_FILES: tuple[tuple[str, str], ...] = (
    (".agents/rfcs/AGENTS.md", ".agents/rfcs/AGENTS.md"),
    (".agents/rfcs/implemented/AGENTS.md", ".agents/rfcs/implemented/AGENTS.md"),
    (".agents/rfcs/archived/AGENTS.md", ".agents/rfcs/archived/AGENTS.md"),
    (".agents/rfcs/archived/manifest.json", ".agents/rfcs/archived/manifest.json"),
    (".agents/skills/archiving-rfcs/SKILL.md", ".agents/skills/archiving-rfcs/SKILL.md"),
    (".agents/skills/documenting/SKILL.md", ".agents/skills/documenting/SKILL.md"),
    (".agents/skills/editing-prose/SKILL.md", ".agents/skills/editing-prose/SKILL.md"),
    (
        ".agents/skills/editing-prose/references/examples.md",
        ".agents/skills/editing-prose/references/examples.md",
    ),
    (
        ".agents/skills/finding-simplifications/SKILL.md",
        ".agents/skills/finding-simplifications/SKILL.md",
    ),
    (".agents/skills/merging-stacked-prs/SKILL.md", ".agents/skills/merging-stacked-prs/SKILL.md"),
    (".agents/skills/pushing/SKILL.md", ".agents/skills/pushing/SKILL.md"),
    (".agents/skills/reviewing/SKILL.md", ".agents/skills/reviewing/SKILL.md"),
    (".agents/skills/translating-docs/SKILL.md", ".agents/skills/translating-docs/SKILL.md"),
    (
        ".agents/skills/trimming-cot-leakage/SKILL.md",
        ".agents/skills/trimming-cot-leakage/SKILL.md",
    ),
    (
        ".agents/skills/trimming-cot-leakage/references/examples.md",
        ".agents/skills/trimming-cot-leakage/references/examples.md",
    ),
    (
        ".agents/skills/trimming-cot-leakage/references/recall-batteries.md",
        ".agents/skills/trimming-cot-leakage/references/recall-batteries.md",
    ),
    ("docs/AGENTS.md", "docs/AGENTS.md"),
    ("docs/i18n/terminology.md", "docs/i18n/terminology.md"),
    ("docs/i18n/style-samples.md", "docs/i18n/style-samples.md"),
    (".github/ISSUE_TEMPLATE/config.yml", ".github/ISSUE_TEMPLATE/config.yml"),
    (".github/ISSUE_TEMPLATE/bug.md", ".github/ISSUE_TEMPLATE/bug.md"),
    (".github/ISSUE_TEMPLATE/feature.md", ".github/ISSUE_TEMPLATE/feature.md"),
    (".github/ISSUE_TEMPLATE/idea.md", ".github/ISSUE_TEMPLATE/idea.md"),
    (".github/ISSUE_TEMPLATE/research.md", ".github/ISSUE_TEMPLATE/research.md"),
    (".github/ISSUE_TEMPLATE/task.md", ".github/ISSUE_TEMPLATE/task.md"),
    (".github/pull_request_template.md", ".github/pull_request_template.md"),
)

#: Mirrored bilingual pairs by English anchor: the two language files are
#: mirrored with upstream link rewriting and the pair is recorded in the
#: consumer repository after writing, so their consistency records describe
#: the rewritten bytes, not this repository's.
MIRRORED_PAIRS: tuple[str, ...] = (
    ".agents/rfcs/README.md",
    "docs/i18n/README.md",
    "docs/i18n/translation-rules.md",
    "docs/cookbook/responding-to-pr-review-on-a-stack.md",
)

#: In-package templates rendered with the adoption parameters.
TEMPLATE_FILES: tuple[tuple[str, str], ...] = (
    ("github/workflows/issue-policy.yml", ".github/workflows/issue-policy.yml"),
    ("github/workflows/issue-lifecycle.yml", ".github/workflows/issue-lifecycle.yml"),
    ("docs/architecture.md", "docs/architecture.md"),
    ("docs/architecture.zh.md", "docs/architecture.zh.md"),
    ("docs/development.md", "docs/development.md"),
    ("docs/development.zh.md", "docs/development.zh.md"),
    ("root/AGENTS.md", "AGENTS.md"),
    ("hdsh/docs.manifest.json", ".hdsh/docs.manifest.json"),
    ("hdsh/pairing.manifest.json", ".hdsh/pairing.manifest.json"),
)

#: Templated bilingual pairs by English anchor, recorded in the consumer
#: repository after writing like the mirrored pairs.
TEMPLATE_PAIRS: tuple[str, ...] = (
    "docs/architecture.md",
    "docs/development.md",
)

#: Destinations the consumer is expected to complete: verify counts their
#: ``TODO(adopt):`` placeholders instead of pinning their digest, because
#: completing the placeholders is the intended change.
EDITABLE_DESTINATIONS: frozenset[str] = frozenset(
    {
        "AGENTS.md",
        "docs/architecture.md",
        "docs/architecture.zh.md",
        "docs/development.md",
        "docs/development.zh.md",
    }
)

_USER_CREDENTIAL_INPUTS = "          project-token: ${{ secrets.HDSH_ISSUE_PROJECT_TOKEN }}"
_ORGANIZATION_CREDENTIAL_INPUTS = (
    "          app-client-id: ${{ vars.HDSH_ISSUE_APP_CLIENT_ID }}\n"
    "          app-private-key: ${{ secrets.HDSH_ISSUE_APP_PRIVATE_KEY }}"
)

_MARKDOWN_LINK = re.compile(r"(\]\()([^)\s]+)(\))")
_OPENING_FENCE = re.compile(r"^\s*(?:```|~~~)")


@dataclass(frozen=True)
class AdoptParameters:
    """The resolved inputs every rendered asset derives from."""

    #: Pinned git ref of harness-deepseek-harness (tag or full SHA).
    hdsh_ref: str
    #: Consumer repository owner parsed from the origin remote.
    owner: str
    #: Consumer repository name parsed from the origin remote.
    repository: str
    #: Deployment flavor: ``user`` or ``organization``.
    account_type: str
    #: GitHub Project number backing issue management.
    project_number: int
    #: GitHub Project title backing issue management.
    project_title: str
    #: The identity whose Project mutations the lifecycle trusts.
    lifecycle_actor: str
    #: Project time zone for date fields, an IANA zone name.
    time_zone: str
    #: Project field name holding the priority.
    priority_field: str
    #: Project field name holding the start date.
    start_date_field: str
    #: Whether resolving Issues may be unassigned.
    allow_unassigned_owner: bool
    #: Absolute-URL prefix accepted before switcher counterparts.
    public_blob_root: str

    @property
    def repository_slug(self) -> str:
        """The ``owner/repository`` slug."""
        return f"{self.owner}/{self.repository}"


def installed_destinations(date: str) -> frozenset[str]:
    """Every consumer path adoption installs, for link rewriting decisions.

    Args:
        date: The adoption date used in the adopt-decision RFC anchor.

    Returns:
        The complete set of installed destination paths.
    """
    destinations = {dest for _, dest in MIRRORED_FILES}
    destinations.update(TEMPLATE_FILES[index][1] for index in range(len(TEMPLATE_FILES)))
    for anchor in MIRRORED_PAIRS:
        destinations.add(anchor)
        destinations.add(f"{anchor[: -len('.md')]}.zh.md")
    adopt_anchor = ADOPT_RFC_ANCHOR.format(date=date)
    destinations.add(adopt_anchor)
    destinations.add(f"{adopt_anchor[: -len('.md')]}.zh.md")
    destinations.update(
        {
            ".gitattributes",
            ".github/issue-management/config.json",
            ".hdsh/adopt.manifest.json",
            ".hdsh/pairing.manifest.json",
            ".hdsh/docs.manifest.json",
            "prek.toml",
        }
    )
    return frozenset(destinations)


def render_tokens(text: str, parameters: AdoptParameters, date: str) -> str:
    """Replace every adoption token in one template text.

    Args:
        text: Template content carrying ``__HDSH_<NAME>__`` tokens.
        parameters: The resolved adoption parameters.
        date: The adoption date in ``yyyy-mm-dd`` form.

    Returns:
        The rendered text with every token replaced.
    """
    credentials = (
        _ORGANIZATION_CREDENTIAL_INPUTS
        if parameters.account_type == "organization"
        else _USER_CREDENTIAL_INPUTS
    )
    for token, value in (
        ("__HDSH_REF__", parameters.hdsh_ref),
        ("__HDSH_DATE__", date),
        ("__HDSH_OWNER__", parameters.owner),
        ("__HDSH_REPOSITORY_NAME__", parameters.repository),
        ("__HDSH_REPOSITORY_SLUG__", parameters.repository_slug),
        ("__HDSH_PUBLIC_BLOB_ROOT__", parameters.public_blob_root),
        ("__HDSH_CREDENTIAL_INPUTS__", credentials),
    ):
        text = text.replace(token, value)
    return text


def rewrite_upstream_links(
    text: str, *, dest: str, installed: frozenset[str], hdsh_ref: str
) -> str:
    """Point relative links that leave the installed set at tagged upstream URLs.

    Links inside fenced code blocks are left alone: they are examples, not
    references. Links whose resolved target is installed keep their relative
    form; everything else resolves against the pinned upstream ref.

    Args:
        text: Markdown content about to be installed at ``dest``.
        dest: Consumer destination path of the content.
        installed: Every path adoption installs.
        hdsh_ref: Pinned ref used for upstream URLs.

    Returns:
        The content with outbound links rewritten to upstream URLs.
    """
    lines: list[str] = []
    fenced = False
    directory = posixpath.dirname(dest)
    for line in text.split("\n"):
        if _OPENING_FENCE.match(line):
            fenced = not fenced
            lines.append(line)
            continue
        if fenced:
            lines.append(line)
            continue
        lines.append(
            _rewrite_line_links(line, directory=directory, installed=installed, hdsh_ref=hdsh_ref)
        )
    return "\n".join(lines)


def _rewrite_line_links(
    line: str, *, directory: str, installed: frozenset[str], hdsh_ref: str
) -> str:
    """Rewrite the markdown links of one prose line."""

    def replace(match: re.Match[str]) -> str:
        target = match.group(2)
        if "://" in target or target.startswith(("#", "mailto:")):
            return match.group(0)
        path, separator, fragment = target.partition("#")
        resolved = posixpath.normpath(posixpath.join(directory, path))
        if resolved in installed:
            return match.group(0)
        upstream = f"{UPSTREAM_BLOB_ROOT}/{hdsh_ref}/{resolved}"
        return f"{match.group(1)}{upstream}{separator}{fragment}{match.group(3)}"

    return _MARKDOWN_LINK.sub(replace, line)
