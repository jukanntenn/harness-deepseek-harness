"""Rendering and link rewriting for the adoptable corpus."""

from __future__ import annotations

import dataclasses

import pytest

from hdsh.adopt.corpus import (
    UPSTREAM_BLOB_ROOT,
    AdoptParameters,
    installed_destinations,
    parse_slots,
    render_tokens,
    rewrite_upstream_links,
    splice_slots,
)

PARAMETERS = AdoptParameters(
    hdsh_ref="v0.1.0",
    owner="consumer-org",
    repository="consumer-repo",
    account_type="user",
    project_number=3,
    project_title="Consumer Issues",
    lifecycle_actor="consumer-bot",
    time_zone="Asia/Shanghai",
    priority_field="Priority",
    start_date_field="Start date",
    allow_unassigned_owner=False,
    public_blob_root="https://github.com/consumer-org/consumer-repo/blob/main/",
)


class TestInstalledDestinations:
    def test_covers_every_asset_class(self) -> None:
        installed = installed_destinations("2026-01-02")
        assert ".agents/skills/pushing/SKILL.md" in installed
        assert "docs/AGENTS.md" in installed
        assert ".agents/rfcs/README.zh.md" in installed
        assert (
            ".agents/rfcs/implemented/process/2026-01-02-adopting-the-hdsh-harness.md" in installed
        )
        assert (
            ".agents/rfcs/implemented/process/2026-01-02-adopting-the-hdsh-harness.zh.md"
            in installed
        )
        assert ".github/workflows/issue-policy.yml" in installed
        assert ".gitattributes" in installed
        assert "prek.toml" in installed


class TestRenderTokens:
    def test_replaces_every_token(self) -> None:
        text = "__HDSH_REF__ __HDSH_DATE__ __HDSH_OWNER__ __HDSH_REPOSITORY_NAME__ "
        text += "__HDSH_REPOSITORY_SLUG__ __HDSH_PUBLIC_BLOB_ROOT__\n"
        text += "__HDSH_CREDENTIAL_INPUTS__\n"
        rendered = render_tokens(text, PARAMETERS, "2026-01-02")
        assert "__HDSH_" not in rendered
        assert "v0.1.0" in rendered
        assert "2026-01-02" in rendered
        assert "consumer-org/consumer-repo" in rendered
        assert "project-token: ${{ secrets.HDSH_ISSUE_PROJECT_TOKEN }}" in rendered

    def test_organization_flavor_renders_app_credentials(self) -> None:
        organization = dataclasses.replace(PARAMETERS, account_type="organization")
        rendered = render_tokens("__HDSH_CREDENTIAL_INPUTS__\n", organization, "2026-01-02")
        assert "app-client-id: ${{ vars.HDSH_ISSUE_APP_CLIENT_ID }}" in rendered
        assert "app-private-key: ${{ secrets.HDSH_ISSUE_APP_PRIVATE_KEY }}" in rendered


class TestRewriteUpstreamLinks:
    INSTALLED: frozenset[str] = installed_destinations("2026-01-02")

    def rewrites(self, markdown: str, dest: str = "docs/architecture.md") -> str:
        return rewrite_upstream_links(
            markdown, dest=dest, installed=self.INSTALLED, hdsh_ref="v0.1.0"
        )

    def test_installed_targets_keep_relative_form(self) -> None:
        markdown = "[standard](AGENTS.md) and [guide](i18n/README.md)\n"
        assert self.rewrites(markdown) == markdown

    def test_outbound_targets_move_to_the_pinned_upstream_ref(self) -> None:
        rewritten = self.rewrites("[rules](../.agents/rfcs/implemented/process/2026-09-07-x.md)\n")
        expected = (
            f"[rules]({UPSTREAM_BLOB_ROOT}/v0.1.0/"
            ".agents/rfcs/implemented/process/2026-09-07-x.md)\n"
        )
        assert rewritten == expected

    def test_fragments_travel_with_the_rewritten_target(self) -> None:
        rewritten = self.rewrites("[rules](../src/hdsh/rfc/format.py#header)\n")
        assert rewritten == (
            f"[rules]({UPSTREAM_BLOB_ROOT}/v0.1.0/src/hdsh/rfc/format.py#header)\n"
        )

    def test_zh_outbound_targets_keep_their_authored_locale_suffix(self) -> None:
        rewritten = self.rewrites(
            "[rules](../.agents/rfcs/implemented/process/2026-09-07-x.zh.md)\n"
        )
        assert rewritten == (
            f"[rules]({UPSTREAM_BLOB_ROOT}/v0.1.0/.agents/rfcs/implemented/process/2026-09-07-x.zh.md)\n"
        )

    def test_external_and_fragment_and_mailto_targets_are_untouched(self) -> None:
        markdown = (
            "[web](https://example.com/a.md) [within](#section) "
            "[mail](mailto:t@t.t) [ftp](ftp://example.com/x.md)\n"
        )
        assert self.rewrites(markdown) == markdown

    def test_fenced_code_blocks_are_untouched(self) -> None:
        markdown = "```markdown\n[example](gone.md)\n```\n\n[real](gone-too.md)\n"
        rewritten = self.rewrites(markdown)
        assert "[example](gone.md)" in rewritten
        assert f"[real]({UPSTREAM_BLOB_ROOT}/v0.1.0/docs/gone-too.md)" in rewritten

    def test_inline_code_spans_are_untouched(self) -> None:
        markdown = (
            "The zh file opens with `[English](foo.md) | 中文` and the en file with "
            "`English | [中文](foo.zh.md)`; see also [the real guide](guide.md).\n"
        )
        rewritten = self.rewrites(markdown, dest="docs/i18n/README.md")
        assert "`[English](foo.md) | 中文`" in rewritten
        assert "`English | [中文](foo.zh.md)`" in rewritten
        assert f"[the real guide]({UPSTREAM_BLOB_ROOT}/v0.1.0/docs/i18n/guide.md)" in rewritten

    def test_images_are_rewritten_like_links(self) -> None:
        rewritten = self.rewrites("![logo](assets/brand.png)\n")
        assert rewritten == f"![logo]({UPSTREAM_BLOB_ROOT}/v0.1.0/docs/assets/brand.png)\n"


class TestSlots:
    TEMPLATE: str = (
        "# Title\n\n"
        "<!-- hdsh:slot command -->\n"
        "TODO(adopt): State the command (hdsh: `uv run pytest`).\n"
        "<!-- /hdsh:slot -->\n\n"
        "Prose stays outside.\n\n"
        "<!-- hdsh:slot second -->\n"
        "line one\nline two\n"
        "<!-- /hdsh:slot -->\n"
    )

    def test_parse_slots_reads_every_region(self) -> None:
        slots = parse_slots(self.TEMPLATE)
        assert slots == {
            "command": "TODO(adopt): State the command (hdsh: `uv run pytest`).",
            "second": "line one\nline two",
        }

    def test_splice_slots_replaces_contents(self) -> None:
        spliced = splice_slots(self.TEMPLATE, {"command": "`cargo test`", "second": "x"})
        assert "`cargo test`" in spliced
        assert "uv run pytest" not in spliced
        assert "<!-- hdsh:slot command -->\n`cargo test`\n<!-- /hdsh:slot -->" in spliced

    def test_splice_slots_requires_every_value(self) -> None:
        with pytest.raises(ValueError, match="slots without values: command"):
            splice_slots(self.TEMPLATE, {"second": "x"})

    def test_parse_rejects_a_slot_that_never_ends(self) -> None:
        with pytest.raises(ValueError, match="never ends"):
            parse_slots("<!-- hdsh:slot a -->\nbody\n")

    def test_parse_rejects_an_unmatched_end(self) -> None:
        with pytest.raises(ValueError, match="without a begin"):
            parse_slots("body\n<!-- /hdsh:slot -->\n")

    def test_parse_rejects_nested_slots(self) -> None:
        with pytest.raises(ValueError, match="begins again"):
            parse_slots("<!-- hdsh:slot a -->\n<!-- hdsh:slot b -->\nx\n<!-- /hdsh:slot -->\n")

    def test_parse_rejects_duplicate_names(self) -> None:
        text = (
            "<!-- hdsh:slot a -->\nx\n<!-- /hdsh:slot -->\n"
            "<!-- hdsh:slot a -->\ny\n<!-- /hdsh:slot -->\n"
        )
        with pytest.raises(ValueError, match="defined twice"):
            parse_slots(text)

    def test_parse_rejects_an_empty_body(self) -> None:
        with pytest.raises(ValueError, match="empty body"):
            parse_slots("<!-- hdsh:slot a -->\n\n<!-- /hdsh:slot -->\n")
