"""The markdown cross-link gate."""

from __future__ import annotations

import json

import pytest

import hdsh.docs.links as links_module
from hdsh.docs.config import DocsConfigError
from hdsh.docs.corpus import CorpusFile
from hdsh.docs.links import AnchorCache, main, run
from hdsh.docs.links import find_violations as find_link_violations
from tests.helpers import Repo, parse_command

LINKS_SCOPE = {"include": ["docs/**/*.md"], "exclude": []}


def write_manifest(repo: Repo, **sections: object) -> None:
    """Write a docs manifest into the disposable repository."""
    repo.write(".hdsh/docs.manifest.json", json.dumps(sections, indent=2) + "\n")


def links_cli() -> int:
    """Run ``hdsh docs links`` with parsed arguments."""
    return main(parse_command(links_module.register, ["links"]))


class TestLinkViolations:
    def layout(self, repo: Repo, files: dict[str, str]) -> None:
        for name, content in files.items():
            repo.write(name, content)

    def violations(self, repo: Repo, source: str) -> list[tuple[str, str]]:
        repo.write("docs/scan.md", source)
        file = CorpusFile("docs/scan.md", repo.root / "docs" / "scan.md")
        return [(v.url, v.reason) for v in find_link_violations(source, file, AnchorCache())]

    def test_accepts_resolving_fragments_non_md_fragments_and_externals(self, repo: Repo) -> None:
        self.layout(
            repo,
            {
                "docs/target.md": "# B\n\n## Part two\n",
                "docs/x.ts": "export {}\n",
            },
        )
        assert (
            self.violations(
                repo,
                "# A\n\n## Deferred work\n\n[self](#deferred-work) [b](target.md#part-two) "
                "[code](x.ts#L10) [ext](https://x.example/#frag)\n",
            )
            == []
        )

    def test_rejects_same_file_fragment_naming_no_anchor(self, repo: Repo) -> None:
        assert self.violations(repo, "# A\n\n[gone](#deferred-work)\n") == [
            ("#deferred-work", "anchor")
        ]

    def test_rejects_case_variant_fragment(self, repo: Repo) -> None:
        assert self.violations(repo, "# A\n\n## Default Loop\n\n[case](#Default-Loop)\n") == [
            ("#Default-Loop", "anchor")
        ]

    def test_rejects_cross_file_fragment_missing_from_target(self, repo: Repo) -> None:
        repo.write("docs/target.md", "# B\n\n## New heading\n")
        assert self.violations(repo, "# A\n\n[stale](target.md#old-heading)\n") == [
            ("target.md#old-heading", "anchor")
        ]

    def test_missing_target_is_reported_as_target_not_anchor(self, repo: Repo) -> None:
        assert self.violations(repo, "# A\n\n[ghost](missing.md#anything)\n") == [
            ("missing.md#anything", "target")
        ]

    def test_percent_encoded_target_resolves_and_broken_escape_fails(self, repo: Repo) -> None:
        repo.write("docs/My File.md", "# Encoded\n")
        assert self.violations(repo, "# A\n\n[ok](My%20File.md)\n") == []
        # A malformed escape names no file any renderer resolves: it stays raw
        # through decoding and the existence check reports it broken.
        assert self.violations(repo, "# A\n\n[bad](%zz-file.md)\n") == [("%zz-file.md", "target")]

    def test_reference_definitions_are_checked_at_their_own_line(self, repo: Repo) -> None:
        source = "# A\n\n[lbl]: missing.md\n\nsee [lbl]\n"
        repo.write("docs/scan.md", source)
        file = CorpusFile("docs/scan.md", repo.root / "docs" / "scan.md")
        violations = find_link_violations(source, file, AnchorCache())
        assert [(v.url, v.reason, v.line) for v in violations] == [
            ("missing.md", "target", 3),
            ("missing.md", "target", 5),
        ]

    def test_shadowed_duplicate_definition_target_is_checked(self, repo: Repo) -> None:
        source = "# A\n\n[lbl]: target.md\n\n[lbl]: gone.md\n\nsee [lbl]\n"
        repo.write("docs/scan.md", source)
        repo.write("docs/target.md", "# B\n")
        file = CorpusFile("docs/scan.md", repo.root / "docs" / "scan.md")
        violations = find_link_violations(source, file, AnchorCache())
        # The shadowed definition's URL is checked even though rendering
        # resolves the label to the first definition.
        assert [(v.url, v.reason, v.line) for v in violations] == [("gone.md", "target", 5)]

    def test_link_in_wrapped_paragraph_reports_its_own_line(self, repo: Repo) -> None:
        source = "# A\n\nfirst\nsecond [ghost](missing.md)\n"
        repo.write("docs/scan.md", source)
        file = CorpusFile("docs/scan.md", repo.root / "docs" / "scan.md")
        violations = find_link_violations(source, file, AnchorCache())
        assert [(v.url, v.reason, v.line) for v in violations] == [("missing.md", "target", 4)]

    def test_anchor_cache_parses_each_target_once(self, repo: Repo) -> None:
        repo.write("docs/target.md", "# B\n")
        cache = AnchorCache()
        first = cache.anchors(repo.root / "docs" / "target.md")
        assert cache.anchors(repo.root / "docs" / "target.md") is first


class TestLinksGate:
    def test_green_corpus_reports_file_count(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_manifest(repo, markdownLinks=LINKS_SCOPE)
        repo.write("docs/a.md", "# A\n\n[b](b.md)\n")
        repo.write("docs/b.md", "# B\n")
        assert run(repo.root) == 0
        assert "2 file(s) checked, all relative cross-links and fragments resolve" in (
            capsys.readouterr().out
        )

    def test_broken_links_fail_with_reasons(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_manifest(repo, markdownLinks=LINKS_SCOPE)
        repo.write("docs/a.md", "# A\n\n[ghost](missing.md) [stale](a.md#nope)\n")
        assert run(repo.root) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "docs/a.md:3  missing.md  (target does not exist)" in captured.err
        assert "docs/a.md:3  a.md#nope  (no such anchor in target)" in captured.err

    def test_excluded_frozen_tree_is_not_scanned(self, repo: Repo) -> None:
        write_manifest(
            repo,
            markdownLinks={"include": ["docs/**/*.md"], "exclude": ["docs/frozen/**"]},
        )
        repo.write("docs/frozen/old.md", "[dead](gone.md)\n")
        assert run(repo.root) == 0

    def test_shadowed_duplicate_definition_fails_the_gate(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_manifest(repo, markdownLinks=LINKS_SCOPE)
        repo.write("docs/target.md", "# B\n")
        repo.write("docs/scan.md", "# A\n\n[lbl]: target.md\n\n[lbl]: gone.md\n\nsee [lbl]\n")
        assert run(repo.root) == 1
        assert "docs/scan.md:5  gone.md  (target does not exist)" in capsys.readouterr().err

    def test_missing_section_refuses_to_run(self, repo: Repo) -> None:
        write_manifest(repo, markdownWrap={"include": ["docs/**/*.md"], "exclude": []})
        with pytest.raises(DocsConfigError, match="markdownLinks section is required"):
            run(repo.root)

    def test_main_exits_two_on_config_error(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_manifest(repo, markdownWrap={"include": ["docs/**/*.md"], "exclude": []})
        monkeypatch.chdir(repo.root)
        assert links_cli() == 2
        assert "markdownLinks" in capsys.readouterr().err

    def test_extra_arguments_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse_command(links_module.register, ["links", "--nope"])
