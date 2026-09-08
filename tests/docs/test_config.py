"""Docs-manifest parsing and loading."""

from __future__ import annotations

import json
import pathlib

import pytest

from hdsh.docs.config import (
    CorpusScope,
    DocsConfigError,
    load_docs_manifest,
    missing_section_error,
    parse_docs_manifest,
)
from tests.helpers import Repo


def write_manifest(repo: Repo, **sections: object) -> None:
    """Write a docs manifest into the disposable repository."""
    repo.write(".hdsh/docs.manifest.json", json.dumps(sections, indent=2) + "\n")


class TestManifestParsing:
    def test_full_manifest_parses_every_section(self) -> None:
        manifest = parse_docs_manifest(
            json.dumps(
                {
                    "markdownWrap": {"include": ["README.md"], "exclude": ["draft/**"]},
                    "markdownLinks": {"include": ["docs/**"], "exclude": []},
                    "docBudgets": {"AGENTS.md": 10},
                }
            )
        )
        assert manifest.markdown_wrap == CorpusScope(include=("README.md",), exclude=("draft/**",))
        assert manifest.markdown_links == CorpusScope(include=("docs/**",), exclude=())
        assert manifest.doc_budgets == {"AGENTS.md": 10}

    def test_omitted_sections_are_none(self) -> None:
        manifest = parse_docs_manifest('{"docBudgets": {"AGENTS.md": 10}}')
        assert manifest.markdown_wrap is None
        assert manifest.markdown_links is None
        assert manifest.doc_budgets == {"AGENTS.md": 10}

    def test_non_object_rejected(self) -> None:
        with pytest.raises(TypeError, match="expected an object"):
            parse_docs_manifest("[]")

    def test_unknown_section_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported section"):
            parse_docs_manifest('{"docWrap": {}}')

    def test_duplicate_keys_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate object key"):
            parse_docs_manifest(
                '{"markdownWrap": {"include": ["a"], "exclude": []},'
                ' "markdownWrap": {"include": ["b"], "exclude": []}}'
            )

    @pytest.mark.parametrize(
        "section",
        [
            '{"markdownWrap": 3}',
            '{"markdownWrap": {"include": ["a"]}}',
            '{"markdownWrap": {"include": [], "exclude": []}}',
            '{"markdownWrap": {"include": "docs/**", "exclude": []}}',
            '{"markdownWrap": {"include": [3], "exclude": []}}',
            '{"markdownWrap": {"include": ["a"], "exclude": "draft"}}',
            '{"markdownWrap": {"include": ["a"], "exclude": [""]}}',
            '{"markdownWrap": {"include": ["/etc/**"], "exclude": []}}',
            '{"markdownWrap": {"include": ["a/../../b"], "exclude": []}}',
        ],
    )
    def test_malformed_scope_sections_rejected(self, section: str) -> None:
        with pytest.raises(ValueError, match="markdownWrap"):
            parse_docs_manifest(section)

    @pytest.mark.parametrize(
        "section",
        [
            '{"docBudgets": 3}',
            '{"docBudgets": {}}',
            '{"docBudgets": {"": 3}}',
            '{"docBudgets": {"a.md": "5"}}',
            '{"docBudgets": {"a.md": true}}',
            '{"docBudgets": {"a.md": 0}}',
            '{"docBudgets": {"a.md": -1}}',
        ],
    )
    def test_malformed_budget_sections_rejected(self, section: str) -> None:
        with pytest.raises(ValueError, match="docBudgets"):
            parse_docs_manifest(section)


class TestManifestLoading:
    def test_missing_manifest_fails_loud(self, repo: Repo) -> None:
        with pytest.raises(DocsConfigError, match="not found"):
            load_docs_manifest(repo.root)

    def test_invalid_manifest_names_the_file(self, repo: Repo) -> None:
        repo.write(".hdsh/docs.manifest.json", "{ not json")
        with pytest.raises(DocsConfigError, match=r"\.hdsh/docs\.manifest\.json: "):
            load_docs_manifest(repo.root)

    def test_unreadable_manifest_fails_loud(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_manifest(repo, markdownWrap={"include": ["docs/**/*.md"], "exclude": []})

        def boom(self: pathlib.Path, encoding: str) -> str:
            raise OSError("device gone")

        monkeypatch.setattr(pathlib.Path, "read_text", boom)
        with pytest.raises(DocsConfigError, match="cannot be read"):
            load_docs_manifest(repo.root)

    def test_missing_section_error_names_tool_and_section(self) -> None:
        message = str(missing_section_error("docBudgets", "hdsh docs budgets"))
        assert "docBudgets" in message
        assert "hdsh docs budgets" in message
