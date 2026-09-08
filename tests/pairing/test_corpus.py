"""Bilingual corpus scope predicates."""

from __future__ import annotations

import pytest

from hdsh.pairing.corpus import is_scope_file, pair_source_predicate
from hdsh.pairing.manifest import parse_manifest


class TestScope:
    def test_scope_files(self) -> None:
        assert is_scope_file("README.md")
        assert is_scope_file("packages/x/readme.zh.md")
        assert is_scope_file("docs/guide.md")
        assert is_scope_file(".agents/rfcs/implemented/process/2026-01-01-a.md")
        assert not is_scope_file(".agents/rfcs/archived/process/2026-01-01-a.md")
        assert not is_scope_file("src/hdsh/core.py")
        assert not is_scope_file("node_modules/x/README.md")
        assert not is_scope_file(".local/contexts/prek/README.md")
        assert not is_scope_file("src/hdsh/__init__.py")

    def test_root_paired_documents(self) -> None:
        assert is_scope_file("CONTRIBUTING.md")
        assert is_scope_file("safety.zh.md")
        assert not is_scope_file("CONTRIBUTING-notes.md")
        assert is_scope_file("docs/CONTRIBUTING-notes.md")

    def test_predicate_combines_scope_and_manifest(self) -> None:
        manifest = parse_manifest('{"excluded": ["docs/guide.md"]}')
        predicate = pair_source_predicate(manifest)
        assert not predicate("docs/guide.md")
        assert predicate("docs/other.md")


class TestScopeMatrix:
    @pytest.mark.parametrize(
        "file",
        [
            "README.md",
            "README.i18n.yaml",
            "CONTRIBUTING.md",
            "CONTRIBUTING.zh.md",
            "CONTRIBUTING.i18n.yaml",
            "BRAND_GUIDELINES.md",
            "BRAND_GUIDELINES.zh.md",
            "BRAND_GUIDELINES.i18n.yaml",
            "SAFETY.md",
            "SAFETY.zh.md",
            "SAFETY.i18n.yaml",
            "apps/cli/README.md",
            "future/subtree/readme.md",
            "packages/example/README.zh.md",
            "native/example/README.i18n.yaml",
            ".agents/rfcs/proposed/feature.md",
            "docs/guide.md",
        ],
    )
    def test_includes(self, file: str) -> None:
        assert is_scope_file(file)

    @pytest.mark.parametrize(
        "file",
        [
            "packages/example/guide.md",
            "packages/example/CONTRIBUTING.md",
            "packages/example/BRAND_GUIDELINES.md",
            "sub/SAFETY.md",
            "other/tutorial.md",
            "website/reference.md",
            "packages/example/README.txt",
            "vendor/example/README.md",
            "packages/example/node_modules/dependency/README.md",
            "packages/example/lib/README.md",
            "coverage/report/README.md",
            "docs/.venv/README.md",
        ],
    )
    def test_excludes(self, file: str) -> None:
        assert not is_scope_file(file)
