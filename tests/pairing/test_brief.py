"""Brief assembly and the ``hdsh pairing brief`` command leaf."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest
from markdown_it.token import Token

import hdsh.pairing.brief as brief_module
from hdsh.pairing.brief import (
    BriefBundle,
    DocumentScope,
    MarkdownSpan,
    MechanicalScope,
    TerminologyRow,
    TranslationBriefInput,
    UnitsScope,
    changed_span_indices,
    compute_mechanical_update,
    first_occurrence_context,
    markdown_units,
    parse_terminology_rows,
    relevant_terminology_rows,
    render_translation_brief,
    section_spans,
    spans_aligned,
    term_offsets,
)
from hdsh.pairing.git import GitError
from tests.helpers import Repo, parse_command, write_pair

TERMINOLOGY = """# 术语表

| English | 中文 | 首次出现 | 不要译作 | 备注 |
|---|---|---|---|---|
| agent | agent | agent（智能体） | | |
| registry | 注册表 | | | |
| blob hash | blob hash | | | |
| 真源 | truth | 真源（source of truth） | | |
| no-first | 无首现 | | | |
"""

_SAMPLE = (
    "# Title\n"
    "\n"
    "English | [中文](x.zh.md)\n"
    "\n"
    "Intro paragraph.\n"
    "\n"
    "## Section\n"
    "\n"
    "```sh\n"
    "ls\n"
    "```\n"
    "\n"
    "- item one\n"
    "- item two\n"
)


def _span(index: int, kind: str, text: str) -> MarkdownSpan:
    return MarkdownSpan(
        index=index, kind=kind, label=kind, start_line=index + 1, end_line=index + 1, text=text
    )


class TestMarkdownUnits:
    def test_outermost_blocks_are_units(self) -> None:
        kinds = [span.kind for span in markdown_units(_SAMPLE)]
        assert kinds == [
            "root.0:heading:1",
            "root.1:paragraph",
            "root.2:paragraph",
            "root.3:heading:2",
            "root.4:code",
            "root.5.0:listItem",
            "root.5.1:listItem",
        ]

    def test_unit_text_covers_its_lines(self) -> None:
        units = markdown_units(_SAMPLE)
        fence = units[4]
        assert (fence.start_line, fence.end_line, fence.text) == (9, 11, "```sh\nls\n```\n")

    def test_unit_labels_name_the_node_type(self) -> None:
        assert [unit.label for unit in markdown_units(_SAMPLE)] == [
            "heading",
            "paragraph",
            "paragraph",
            "heading",
            "code",
            "listItem",
            "listItem",
        ]

    def test_table_rows_are_direct_table_children(self) -> None:
        markdown = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"
        assert [span.kind for span in markdown_units(markdown)] == [
            "root.0.0:tableRow",
            "root.0.1:tableRow",
            "root.0.2:tableRow",
        ]

    def test_nested_blocks_inside_containers_stay_one_unit(self) -> None:
        markdown = "> quoted\n>\n> more quoted\n"
        assert [span.kind for span in markdown_units(markdown)] == ["root.0:blockquote"]

    def test_solo_leaves(self) -> None:
        markdown = "    indented\n\n<div>\nblock\n</div>\n\n---\n"
        assert [span.kind for span in markdown_units(markdown)] == [
            "root.0:code",
            "root.1:html",
            "root.2:thematicBreak",
        ]


class TestSectionSpans:
    def test_preamble_and_sections(self) -> None:
        spans = section_spans(_SAMPLE)
        assert [(span.kind, span.label, span.start_line, span.end_line) for span in spans] == [
            ("section:1", "Title", 1, 6),
            ("section:2", "Section", 7, 14),
        ]

    def test_content_before_first_heading_is_preamble(self) -> None:
        spans = section_spans("switcher line\n\n# Only\n\nbody\n")
        assert [span.kind for span in spans] == ["preamble", "section:1"]
        assert spans[0].end_line == 2

    def test_empty_heading_label(self) -> None:
        spans = section_spans("#\nbody\n")
        assert spans[0].label == "(untitled section)"

    def test_document_without_headings(self) -> None:
        spans = section_spans("just prose\n")
        assert [span.kind for span in spans] == ["preamble"]

    def test_heading_label_drops_inline_markers(self) -> None:
        spans = section_spans("# **Bold** and `code` [link](target.md) text\n")
        assert spans[0].label == "Bold and code link text"

    def test_inline_text_without_children_is_empty(self) -> None:
        assert brief_module._inline_text(Token(type="inline", tag="", nesting=0)) == ""

    def test_translated_heading_text_still_aligns_by_depth(self) -> None:
        en = "# Title\n\nbody\n"
        zh = "# 标题\n\n正文\n"
        assert spans_aligned(section_spans(en), section_spans(zh))


class TestAlignment:
    def test_alignment_requires_equal_nonempty_kinds(self) -> None:
        one = [_span(0, "root.0:paragraph", "a\n")]
        same = [_span(0, "root.0:paragraph", "b\n")]
        other = [_span(0, "root.0:code", "b\n")]
        assert spans_aligned(one, same)
        assert not spans_aligned(one, other)
        assert not spans_aligned([], [])
        assert not spans_aligned(one, [_span(0, "root.0:paragraph", "a\n"), _span(1, "k", "b\n")])

    def test_changed_indices_follow_text(self) -> None:
        before = [_span(0, "k", "a\n"), _span(1, "k", "b\n")]
        after = [_span(0, "k", "a\n"), _span(1, "k", "B\n")]
        assert changed_span_indices(before, after) == [1]


class TestMechanicalUpdate:
    CONFIRMED: str = "P.\n\n```sh\nls\n```\n"
    CURRENT: str = "P.\n\n```sh\nls -la\n```\n"
    COUNTERPART: str = "段落。\n\n```sh\nls\n```\n"

    def test_code_only_change_splices(self) -> None:
        assert (
            compute_mechanical_update(self.CONFIRMED, self.CURRENT, self.COUNTERPART)
            == "段落。\n\n```sh\nls -la\n```\n"
        )

    def test_no_fences_is_not_mechanical(self) -> None:
        assert compute_mechanical_update("P.\n", "Q.\n", "段。\n") is None

    def test_count_mismatch_is_not_mechanical(self) -> None:
        added = "P.\n\n```sh\nls\n```\n\n```sh\npwd\n```\n"
        assert compute_mechanical_update(self.CONFIRMED, added, self.COUNTERPART) is None

    def test_prose_change_is_not_mechanical(self) -> None:
        current = "P changed.\n\n```sh\nls -la\n```\n"
        assert compute_mechanical_update(self.CONFIRMED, current, self.COUNTERPART) is None

    def test_drifted_counterpart_fence_is_not_mechanical(self) -> None:
        counterpart = "段落。\n\n```sh\nother\n```\n"
        assert compute_mechanical_update(self.CONFIRMED, self.CURRENT, counterpart) is None

    def test_no_change_is_not_mechanical(self) -> None:
        assert compute_mechanical_update(self.CONFIRMED, self.CONFIRMED, self.COUNTERPART) is None


class TestTerminology:
    def test_parse_skips_headers_and_separators(self) -> None:
        rows = parse_terminology_rows(TERMINOLOGY)
        assert [row.english for row in rows] == [
            "agent",
            "registry",
            "blob hash",
            "真源",
            "no-first",
        ]

    def test_parse_strips_emphasis(self) -> None:
        rows = parse_terminology_rows("| `code` | **bold** | x | | |\n")
        assert rows == [
            TerminologyRow(
                english="code", chinese="bold", first="x", line="| `code` | **bold** | x | | |"
            )
        ]

    def test_parse_pads_short_rows(self) -> None:
        rows = parse_terminology_rows("| only |\n")
        assert rows[0].chinese == ""
        assert rows[0].first == ""

    def test_term_offsets(self) -> None:
        assert term_offsets("an agent uses agents", "agent", True) == [3, 14]
        assert term_offsets("a registry of registries", "registry", True) == [2, 14]
        assert term_offsets("an agent uses agents", "agent") == [3]
        assert term_offsets("agents", "agent", True) == [0]
        assert term_offsets("some agents", "agents", True) == [5]
        assert term_offsets("reagents", "agent", True) == []
        assert term_offsets("", "agent", True) == []
        assert term_offsets("术语真源与表", "真源") == [2]
        assert term_offsets("anything", "") == []

    def test_relevant_rows_by_direction(self) -> None:
        en = relevant_terminology_rows(TERMINOLOGY, "en-to-zh", "the agent and blob hash")
        assert [row.english for row in en] == ["agent", "blob hash"]
        zh = relevant_terminology_rows(TERMINOLOGY, "zh-to-en", "真源（source of truth）与注册表")
        assert [row.english for row in zh] == ["registry", "真源"]
        assert relevant_terminology_rows(TERMINOLOGY, "en-to-zh", "delegate the work") == []


class TestFirstOccurrence:
    def _rows(self, terminology: str = TERMINOLOGY) -> list[TerminologyRow]:
        return parse_terminology_rows(terminology)

    def test_moved_occurrence_adds_extras_and_note(self) -> None:
        confirmed = "First talks of agents.\n\nSecond mentions nothing.\n"
        current = "First mentions nothing.\n\nSecond talks of agents.\n"
        confirmed_spans = markdown_units(confirmed)
        current_spans = markdown_units(current)
        context = first_occurrence_context(
            confirmed,
            current,
            confirmed_spans,
            current_spans,
            rows=self._rows(),
            changed={0, 1},
        )
        assert context.extra_span_indices == []
        assert context.notes
        assert "moved from #0 to #1" in context.notes[0]

    def test_moved_occurrence_pulls_only_the_vacated_span(self) -> None:
        confirmed = "# T\n\nAlpha paragraph.\n\nThe agent runs.\n"
        current = "# T\n\nAlpha paragraph with an agent.\n\nThe agent runs.\n"
        rows = [row for row in parse_terminology_rows(TERMINOLOGY) if row.english == "agent"]
        context = first_occurrence_context(
            confirmed,
            current,
            markdown_units(confirmed),
            markdown_units(current),
            rows=rows,
            changed={1},
        )
        assert context.extra_span_indices == [2]
        assert "moved from #2 to #1" in context.notes[0]

    def test_extras_exclude_changed_indices(self) -> None:
        confirmed = "agent here.\n\nplain.\n"
        current = "plain.\n\nagent here.\n"
        context = first_occurrence_context(
            confirmed,
            current,
            markdown_units(confirmed),
            markdown_units(current),
            rows=self._rows(),
            changed=set(),
        )
        assert context.extra_span_indices == [0, 1]

    def test_stable_occurrence_notes_nothing(self) -> None:
        text = "agent first.\n\nagent again.\n"
        spans = markdown_units(text)
        context = first_occurrence_context(
            text,
            text + "tail\n",
            spans,
            markdown_units(text + "tail\n"),
            rows=self._rows(),
            changed=set(),
        )
        assert context.notes == []
        assert context.extra_span_indices == []

    def test_row_without_first_occurrence_is_skipped(self) -> None:
        rows = [row for row in self._rows() if row.english == "no-first"]
        context = first_occurrence_context(
            "no-first a.\n",
            "no-first b.\n",
            markdown_units("x\n"),
            markdown_units("y\n"),
            rows=rows,
            changed=set(),
        )
        assert context.notes == []

    def test_absent_occurrences_note_absent(self) -> None:
        context = first_occurrence_context(
            "nothing here.\n",
            "still nothing.\n",
            markdown_units("nothing here.\n"),
            markdown_units("still nothing.\n"),
            rows=self._rows(),
            changed=set(),
        )
        assert context.notes == []


class TestFence:
    def test_minimum_fence(self) -> None:
        assert brief_module._fence_for("plain text\n", "`") == "```"
        assert brief_module._fence_for("plain text\n", "~") == "~~~"

    def test_fence_grows_past_nested_runs(self) -> None:
        assert brief_module._fence_for("```\ncode\n```\n", "`") == "````"
        assert brief_module._fence_for("~~~\ncode\n~~~\n", "~") == "~~~~"
        assert brief_module._fence_for("  ````\ncode\n", "`") == "`````"


class TestRender:
    def _input(
        self,
        scope: MechanicalScope | UnitsScope | DocumentScope,
        direction: brief_module.BriefDirection = "en-to-zh",
        terminology: list[TerminologyRow] | None = None,
    ) -> TranslationBriefInput:
        return TranslationBriefInput(
            source_path="docs/guide.md" if direction == "en-to-zh" else "docs/guide.zh.md",
            counterpart_path="docs/guide.zh.md" if direction == "en-to-zh" else "docs/guide.md",
            direction=direction,
            diff="@@ -1 +1 @@\n-a\n+b\n",
            scope=scope,
            terminology=terminology or [],
        )

    def test_mechanical_scope(self) -> None:
        text = render_translation_brief(self._input(MechanicalScope()))
        assert "## Mechanical update" in text
        assert "`uv run hdsh pairing brief --apply docs/guide.md`" in text
        assert "2. `uv run hdsh pairing record docs/guide.md`" in text
        assert "3. `uv run hdsh pairing verify docs/guide.md`" in text
        assert "Binding terminology rows" not in text

    def test_units_scope_with_bundle_and_terminology(self) -> None:
        scope = UnitsScope(
            kind="units",
            bundles=[
                BriefBundle(
                    index=1,
                    label="paragraph",
                    confirmed_source_text="old\n",
                    current_source_text="new\n",
                    counterpart_text="旧\n",
                    counterpart_start_line=5,
                ),
                BriefBundle(
                    index=2,
                    label="paragraph",
                    reason="first-occurrence",
                    confirmed_source_text="same\n",
                    current_source_text="same\n",
                    counterpart_text="同样\n",
                    counterpart_start_line=7,
                ),
            ],
            first_occurrence_notes=["agent: the document-wide first occurrence moved"],
        )
        text = render_translation_brief(
            self._input(scope, terminology=parse_terminology_rows(TERMINOLOGY)[:1])
        )
        assert "## Changed units" in text
        assert "### #1 paragraph — counterpart at docs/guide.zh.md:5" in text
        assert "Last-confirmed English:" in text
        assert "Current Chinese (bring this along):" in text
        assert "### #2 paragraph — unchanged; included for a first-occurrence move" in text
        second_body = text.split("### #2", 1)[1].split("\n## ", 1)[0]
        assert "Last-confirmed" not in second_body
        assert "Current English:" in second_body
        assert "## First-occurrence notes" in text
        assert "| English | 中文 | 首次出现 | 不要译作 | 备注 |" in text
        assert "- Write natural institutional technical Chinese" in text

    def test_sections_scope(self) -> None:
        scope = UnitsScope(kind="sections", bundles=[], first_occurrence_notes=[])
        text = render_translation_brief(self._input(scope))
        assert "## Changed sections" in text

    def test_document_scope(self) -> None:
        text = render_translation_brief(self._input(DocumentScope(reason="Because.")))
        assert "## Whole-document update required" in text
        assert "Because. Open `docs/guide.zh.md` directly" in text

    def test_zh_direction_uses_english_digest_and_anchor(self) -> None:
        text = render_translation_brief(self._input(MechanicalScope(), direction="zh-to-en"))
        assert "The Chinese side changed" in text
        assert "- Write concise professional developer prose" in text
        assert "2. `uv run hdsh pairing record docs/guide.md`" in text


class TestPlanScope:
    def test_both_drifted_forces_document_scope(self) -> None:
        planned = brief_module._plan_scope(
            TERMINOLOGY,
            "old en\n",
            "new en\n",
            "new zh\n",
            direction="en-to-zh",
            both_drifted=True,
        )
        assert isinstance(planned.scope, DocumentScope)
        assert "BOTH sides changed" in planned.scope.reason

    def test_mechanical_scope_short_circuits(self) -> None:
        planned = brief_module._plan_scope(
            TERMINOLOGY,
            "P.\n\n```sh\nls\n```\n",
            "P.\n\n```sh\nls -la\n```\n",
            "段。\n\n```sh\nls\n```\n",
            direction="en-to-zh",
            both_drifted=False,
        )
        assert isinstance(planned.scope, MechanicalScope)
        assert planned.mechanical_result is not None

    def test_units_scope_maps_changed_spans(self) -> None:
        planned = brief_module._plan_scope(
            TERMINOLOGY,
            "one\n\ntwo\n",
            "one\n\nTWO\n",
            "一\n\n二\n",
            direction="en-to-zh",
            both_drifted=False,
        )
        assert isinstance(planned.scope, UnitsScope)
        assert planned.scope.kind == "units"
        assert [bundle.index for bundle in planned.scope.bundles] == [1]

    def test_sections_scope_when_units_do_not_align(self) -> None:
        planned = brief_module._plan_scope(
            TERMINOLOGY,
            "# H\n\nold\n",
            "# H\n\nnew\n\n- item\n",
            "# H 中文\n\n新\n",
            direction="en-to-zh",
            both_drifted=False,
        )
        assert isinstance(planned.scope, UnitsScope)
        assert planned.scope.kind == "sections"

    def test_document_scope_when_nothing_aligns(self) -> None:
        planned = brief_module._plan_scope(
            TERMINOLOGY,
            "# A\n\nold\n",
            "## B\n\nnew\n",
            "# C 中文\n\n新\n",
            direction="en-to-zh",
            both_drifted=False,
        )
        assert isinstance(planned.scope, DocumentScope)
        assert "Neither fine-grained units nor heading sections align" in planned.scope.reason

    def test_span_change_outside_any_unit_escalates_to_document(self) -> None:
        planned = brief_module._plan_scope(
            TERMINOLOGY,
            "one\n\ntwo\n",
            "one\r\n\r\ntwo\r\n",
            "一\n\n二\n",
            direction="en-to-zh",
            both_drifted=False,
        )
        assert isinstance(planned.scope, DocumentScope)
        assert "Neither fine-grained units nor heading sections align" in planned.scope.reason

    def test_lines_of_without_trailing_newline(self) -> None:
        assert brief_module._lines_of("no trailing newline") == ["no trailing newline"]

    def test_zh_direction_skips_first_occurrence_tracking(self) -> None:
        planned = brief_module._plan_scope(
            TERMINOLOGY,
            "one\n",
            "ONE\n",
            "一\n",
            direction="zh-to-en",
            both_drifted=False,
        )
        assert isinstance(planned.scope, UnitsScope)
        assert planned.scope.first_occurrence_notes == []


def parse_brief(*args: str) -> argparse.Namespace:
    """Parse one ``hdsh pairing brief`` invocation through the real leaf."""
    return parse_command(brief_module.register, ["brief", *args])


def run_brief(repo: Repo, *args: str) -> tuple[int, list[str], list[str]]:
    """Run the brief request pipeline against a repository, capturing output."""
    out: list[str] = []
    err: list[str] = []
    parsed = parse_brief(*args)
    code = brief_module._run(
        str(repo.root),
        list(parsed.anchors),
        apply=parsed.apply,
        stdout=out.append,
        stderr=err.append,
    )
    return code, out, err


def _record(repo: Repo, anchor: str) -> None:
    from hdsh.pairing import verify as pairing_verify

    request = pairing_verify.record_request(
        parse_command(pairing_verify.register, ["record", anchor])
    )
    assert pairing_verify.run_gate(request, str(repo.root)) == 0


def _write_terminology(repo: Repo) -> None:
    repo.write("docs/i18n/terminology.md", TERMINOLOGY)


class TestBriefCommand:
    def test_no_drift_reports_nothing_to_brief(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        _record(repo, "docs/guide.md")
        code, out, err = run_brief(repo)
        assert code == 0
        assert any("nothing to brief" in line for line in out)

    def test_named_in_sync_pair_is_a_usage_error(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        _record(repo, "docs/guide.md")
        code, _, err = run_brief(repo, "docs/guide.md")
        assert code == 2
        assert any("nothing to brief" in line for line in err)

    def test_named_out_of_scope_pair_is_rejected(self, repo: Repo) -> None:
        _write_terminology(repo)
        code, _, err = run_brief(repo, "outside/x.md")
        assert code == 2
        assert any("not an in-scope documentation pair" in line for line in err)

    def test_named_incomplete_pair_is_rejected(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        (repo.root / "docs/guide.zh.md").unlink()
        code, _, err = run_brief(repo, "docs/guide.md")
        assert code == 2
        assert any("incomplete pair" in line for line in err)

    def test_malformed_record_is_rejected(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        repo.write("docs/guide.i18n.yaml", "guide.md: nothex\n")
        code, _, err = run_brief(repo, "docs/guide.md")
        assert code == 2
        assert any("malformed consistency record" in line for line in err)

    def test_missing_terminology_exits_two(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        _record(repo, "docs/guide.md")
        code, _, err = run_brief(repo, "docs/guide.md")
        assert code == 2
        assert any("terminology.md is missing from the repository root" in line for line in err)

    @pytest.mark.parametrize("vanished", ["docs/guide.md", "docs/guide.zh.md"])
    def test_vanished_pair_file_after_load_exits_two(
        self,
        repo: Repo,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        vanished: str,
    ) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        _record(repo, "docs/guide.md")
        repo.write(
            "docs/guide.md",
            (repo.root / "docs/guide.md").read_text().replace("Body paragraph.", "Edited."),
        )
        real_read = brief_module._read_pair_file

        def vanishing(root: str, path: str) -> str | None:
            return None if path == vanished else real_read(root, path)

        monkeypatch.setattr(brief_module, "_read_pair_file", vanishing)
        monkeypatch.chdir(repo.root)
        assert brief_module.main(parse_brief("docs/guide.md")) == 2
        assert f"{vanished} was removed after the pair was loaded" in capsys.readouterr().err

    def test_drifted_english_side_briefs_units(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        _record(repo, "docs/guide.md")
        repo.write(
            "docs/guide.md",
            (repo.root / "docs/guide.md").read_text().replace("Body paragraph.", "Rewritten body."),
        )
        code, out, err = run_brief(repo, "docs/guide.md")
        assert code == 0, err
        assert any("# Translation update briefing: docs/guide.md" in line for line in out)
        assert any("## Changed units" in line for line in out)
        assert any("## Rules digest" in line for line in out)

    def test_mechanical_apply_writes_counterpart(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/other.md")
        _record(repo, "docs/other.md")
        en = (
            "# Guide\n\nEnglish | [中文](guide.zh.md)\n\nBody with [other](other.md).\n\n"
            "```sh\nls\n```\n"
        )
        zh = (
            "# 指南\n\n[English](guide.md) | 中文\n\n带 [other](other.zh.md) 的正文。\n\n"
            "```sh\nls\n```\n"
        )
        repo.write("docs/guide.md", en)
        repo.write("docs/guide.zh.md", zh)
        _record(repo, "docs/guide.md")
        repo.write("docs/guide.md", en.replace("ls\n", "ls -la\n"))
        code, out, err = run_brief(repo, "--apply", "docs/guide.md")
        assert code == 0, err
        counterpart = (repo.root / "docs/guide.zh.md").read_text()
        assert "```sh\nls -la\n```" in counterpart
        assert "的正文。" in counterpart
        assert any("applied code-fence splice to docs/guide.zh.md" in line for line in err)

    def test_both_sides_drifted_maps_document_scope(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        _record(repo, "docs/guide.md")
        repo.write(
            "docs/guide.md",
            (repo.root / "docs/guide.md").read_text().replace("Body paragraph.", "En edit."),
        )
        repo.write(
            "docs/guide.zh.md",
            (repo.root / "docs/guide.zh.md").read_text().replace("正文段落。", "中文改动。"),
        )
        code, out, err = run_brief(repo, "docs/guide.md")
        assert code == 0, err
        assert any("## Whole-document update required" in line for line in out)

    def test_drifted_zh_side_briefs_zh_to_en(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        _record(repo, "docs/guide.md")
        repo.write(
            "docs/guide.zh.md",
            (repo.root / "docs/guide.zh.md").read_text().replace("正文段落。", "中文改动。"),
        )
        code, out, err = run_brief(repo, "docs/guide.md")
        assert code == 0, err
        assert any("# Translation update briefing: docs/guide.zh.md" in line for line in out)

    def test_missing_manifest_exits_two(self, repo: Repo) -> None:
        (repo.root / ".hdsh/pairing.manifest.json").unlink()
        code, _, err = run_brief(repo)
        assert code == 2
        assert any("manifest" in line.lower() for line in err)

    def test_invalid_manifest_exits_two(self, repo: Repo) -> None:
        repo.write(".hdsh/pairing.manifest.json", "[]")
        code, _, err = run_brief(repo)
        assert code == 2
        assert any("expected an object" in line for line in err)

    def test_apply_mechanical_rejects_structural_violation(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        en_current = (repo.root / "docs/guide.md").read_text()
        with pytest.raises(ValueError, match="violates the pair structure"):
            brief_module._apply_mechanical(
                str(repo.root),
                lambda path: path == "docs/guide.md",
                "docs/guide.zh.md",
                en_current,
                "# Different\n\n[English](guide.md) | 中文\n\n结构不同。\n\n- extra\n",
                public_blob_root="",
                stderr=print,
            )

    def test_mechanical_apply_zh_to_en_direction(self, repo: Repo) -> None:
        _write_terminology(repo)
        en = "# Guide\n\nEnglish | [中文](guide.zh.md)\n\nBody paragraph.\n\n```sh\nls\n```\n"
        zh = "# 指南\n\n[English](guide.md) | 中文\n\n正文段落。\n\n```sh\nls\n```\n"
        repo.write("docs/guide.md", en)
        repo.write("docs/guide.zh.md", zh)
        _record(repo, "docs/guide.md")
        repo.write("docs/guide.zh.md", zh.replace("ls\n", "ls -la\n"))
        code, out, err = run_brief(repo, "--apply", "docs/guide.zh.md")
        assert code == 0, err
        assert "```sh\nls -la\n```" in (repo.root / "docs/guide.md").read_text()
        assert any("applied code-fence splice to docs/guide.md" in line for line in err)

    def test_discovery_skips_unbriefable_pairs(self, repo: Repo) -> None:
        _write_terminology(repo)
        write_pair(repo, "docs/guide.md")
        _record(repo, "docs/guide.md")
        repo.write("docs/broken.i18n.yaml", "broken.md: " + "0" * 40 + "\n")
        code, out, err = run_brief(repo)
        assert code == 0
        assert any("nothing to brief" in line for line in out)

    def test_unreadable_recorded_blob_exits_two(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_pair(repo, "docs/guide.md")
        _write_terminology(repo)
        repo.write("docs/guide.i18n.yaml", f"guide.md: {'0' * 40}\nguide.zh.md: {'0' * 40}\n")
        monkeypatch.chdir(repo.root)
        assert brief_module.main(parse_brief("docs/guide.md")) == 2

    def test_apply_mechanical_writes_valid_result(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        en_current = (repo.root / "docs/guide.md").read_text()
        zh_current = (repo.root / "docs/guide.zh.md").read_text()
        receipts: list[str] = []
        brief_module._apply_mechanical(
            str(repo.root),
            lambda path: path == "docs/guide.md",
            "docs/guide.zh.md",
            en_current,
            zh_current,
            public_blob_root="",
            stderr=receipts.append,
        )
        assert (repo.root / "docs/guide.zh.md").read_text() == zh_current
        assert any("applied code-fence splice" in line for line in receipts)


class TestMainEdges:
    def test_outside_repository_exits_two(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert brief_module.main(parse_brief()) == 2

    def test_root_lookup_oserror_exits_two(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("no git")

        monkeypatch.setattr(brief_module.subprocess, "run", raising_run)
        assert brief_module.main(parse_brief()) == 2

    def test_git_failure_exits_two(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["git"], 128, b"", b"fatal")
        monkeypatch.setattr(
            brief_module.subprocess,
            "run",
            lambda *args, **kwargs: completed,
        )
        assert brief_module.main(parse_brief()) == 2

    def test_diff_subprocess_failure_raises(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = subprocess.CompletedProcess(["git"], 128, b"", b"fatal: not a repository")
        monkeypatch.setattr(brief_module.subprocess, "run", lambda *args, **kwargs: completed)
        with pytest.raises(GitError, match="diff --no-index"):
            brief_module._diff_texts(str(repo.root), "a\n", "b\n")
