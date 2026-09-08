"""End-to-end pairing gate behavior and subcommand argument parsing."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

import hdsh.pairing.verify as tp_verify_module
from hdsh.pairing.verify import (
    PairingRepository,
    PairingRequest,
    _check_pair,
    list_request,
    record_request,
    run_gate,
    verify_request,
)
from tests.helpers import EN_PAIR, MANIFEST, Repo, en_pair, parse_command, write_pair, zh_pair

_REQUEST_BUILDERS = {
    "verify": verify_request,
    "record": record_request,
    "list": list_request,
}


def parse(*args: str) -> argparse.Namespace:
    """Parse one ``hdsh pairing`` invocation through the registered leaves."""
    return parse_command(tp_verify_module.register, list(args))


def run(repo: Repo, *args: str) -> tuple[int, list[str], list[str]]:
    """Run one subcommand's gate request and capture both output planes."""
    out: list[str] = []
    err: list[str] = []
    name, rest = args[0], args[1:]
    try:
        parsed = parse(name, *rest)
        request = _REQUEST_BUILDERS[name](parsed)
    except ValueError as error:
        err.append(str(error))
        return 2, out, err
    code = run_gate(request, str(repo.root), stdout=out.append, stderr=err.append)
    return code, out, err


def record(repo: Repo, anchor: str) -> None:
    """Record one pair through the gate's own write path."""
    code, _, err = run(repo, "record", anchor)
    assert code == 0, err


class TestVerifyArgs:
    def test_corpus_check(self) -> None:
        request = verify_request(parse("verify"))
        assert (request.input, request.mode, request.scope, request.anchors) == (
            "worktree",
            "check",
            "corpus",
            (),
        )

    def test_named_pairs_check(self) -> None:
        request = verify_request(parse("verify", "docs/a.md", "docs/b.zh.md"))
        assert request.scope == "pairs"
        assert request.anchors == ("docs/a.md", "docs/b.md")

    def test_cached_check(self) -> None:
        request = verify_request(parse("verify", "--cached", "docs/a.md"))
        assert request.input == "index"

    def test_unknown_flag(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse("verify", "--wat")

    def test_record_flag_is_not_a_verify_flag(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse("verify", "--all")

    def test_cached_requires_paths(self) -> None:
        with pytest.raises(ValueError, match="--cached requires"):
            verify_request(parse("verify", "--cached"))

    def test_three_spellings_of_one_pair_dedupe_to_one_anchor(self) -> None:
        request = verify_request(
            parse("verify", "docs/foo.zh.md", "docs/foo.i18n.yaml", "docs/bar.md")
        )
        assert request.anchors == ("docs/bar.md", "docs/foo.md")


class TestRecordArgs:
    def test_record_requires_explicit_pairs(self) -> None:
        with pytest.raises(ValueError, match="record requires"):
            record_request(parse("record"))

    def test_record_rejects_pairs_and_all(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            record_request(parse("record", "--all", "docs/a.md"))

    def test_record_all(self) -> None:
        request = record_request(parse("record", "--all"))
        assert (request.mode, request.scope) == ("write", "corpus")

    def test_record_rejects_verify_flags(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse("record", "--cached", "docs/a.md")


class TestListArgs:
    def test_list_reports_the_whole_corpus(self) -> None:
        request = list_request(parse("list"))
        assert (request.mode, request.scope) == ("list", "corpus")

    def test_list_takes_no_arguments(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse("list", "docs/a.md")
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse("list", "--write")


class TestCorpusCheck:
    def test_green_corpus(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        write_pair(repo, "README.md")
        record(repo, "docs/guide.md")
        record(repo, "README.md")
        code, out, err = run(repo, "verify")
        assert code == 0, err
        assert "2 pair(s) checked" in out[0]

    def test_missing_counterpart_is_required(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        (repo.root / "docs/guide.zh.md").unlink()
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("must merge bilingual" in line for line in err)

    def test_half_deleted_pair_from_sidecar(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        record(repo, "docs/guide.md")
        (repo.root / "docs/guide.md").unlink()
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("incomplete pair" in line for line in err)

    def test_edited_side_without_rerecord_goes_red(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        record(repo, "docs/guide.md")
        repo.write("docs/guide.md", EN_PAIR + "\nadded\n")
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("out of sync" in line for line in err)

    def test_malformed_record(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        repo.write("docs/guide.i18n.yaml", "guide.md: nothex\n")
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("malformed consistency record" in line for line in err)

    def test_missing_zh_switcher(self, repo: Repo) -> None:
        write_pair(
            repo,
            "docs/guide.md",
            zh=lambda target: zh_pair(target).replace(f"[English]({target}) | 中文", "no switcher"),
        )
        record(repo, "docs/guide.md")
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("missing language switcher" in line and "guide.zh.md" in line for line in err)

    def test_missing_en_switcher(self, repo: Repo) -> None:
        write_pair(
            repo,
            "docs/guide.md",
            source=lambda target: en_pair(target).replace(
                f"English | [中文]({target})", "no switcher"
            ),
        )
        record(repo, "docs/guide.md")
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("missing language switcher" in line and "docs/guide.md" in line for line in err)

    def test_generated_source_exempt_from_en_switcher(self, repo: Repo) -> None:
        repo.write(
            ".hdsh/pairing.manifest.json",
            json.dumps({**MANIFEST, "generated": ["docs/guide.md"]}, indent=2) + "\n",
        )
        write_pair(
            repo,
            "docs/guide.md",
            source=lambda target: en_pair(target).replace(
                f"English | [中文]({target})", "generated: no switcher"
            ),
        )
        record(repo, "docs/guide.md")
        code, _, err = run(repo, "verify")
        assert code == 0, err

    def test_generated_source_zh_switcher_still_required(self, repo: Repo) -> None:
        repo.write(
            ".hdsh/pairing.manifest.json",
            json.dumps({**MANIFEST, "generated": ["docs/guide.md"]}, indent=2) + "\n",
        )
        write_pair(
            repo,
            "docs/guide.md",
            source=lambda target: en_pair(target).replace(
                f"English | [中文]({target})", "generated: no switcher"
            ),
            zh=lambda target: zh_pair(target).replace(f"[English]({target}) | 中文", "no switcher"),
        )
        record(repo, "docs/guide.md")
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("missing language switcher" in line and "guide.zh.md" in line for line in err)

    def test_structural_divergence(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md", zh=lambda target: zh_pair(target) + "\n- extra\n")
        record(repo, "docs/guide.md")
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("list" in line and "diverges" in line for line in err)

    def test_cross_pair_links_normalize_to_one_target(self, repo: Repo) -> None:
        repo.write(
            "docs/guide.md",
            en_pair("guide.zh.md").replace("Body paragraph.", "See [other](other.md)."),
        )
        repo.write(
            "docs/guide.zh.md",
            zh_pair("guide.md").replace("正文段落。", "参见[另一文档](other.zh.md)。"),
        )
        write_pair(repo, "docs/other.md")
        record(repo, "docs/guide.md")
        record(repo, "docs/other.md")
        code, _, err = run(repo, "verify")
        assert code == 0, err

    def test_excluded_source_rejects_artifacts(self, repo: Repo) -> None:
        repo.write("docs/AGENTS.md", "# Agent instructions\n")
        repo.write("docs/AGENTS.zh.md", "# 说明\n")
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("excluded from pairing" in line for line in err)

    def test_locale_violation_in_pair(self, repo: Repo) -> None:
        repo.write(
            "docs/guide.md",
            en_pair("guide.zh.md").replace("Body paragraph.", "See [guide](guide.zh.md)."),
        )
        repo.write("docs/guide.zh.md", zh_pair("guide.md"))
        write_pair(repo, "docs/other.md")
        record(repo, "docs/guide.md")
        record(repo, "docs/other.md")
        code, _, err = run(repo, "verify")
        assert code == 1
        assert any("wrong locale" in line for line in err)


class TestListMode:
    def test_list_reports_states(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        record(repo, "docs/guide.md")
        write_pair(repo, "docs/missing.md")
        (repo.root / "docs/missing.zh.md").unlink()
        write_pair(repo, "docs/edited.md")
        record(repo, "docs/edited.md")
        repo.write("docs/edited.md", en_pair("edited.zh.md") + "\ndrift\n")
        code, out, _ = run(repo, "list")
        assert code == 0
        text = "\n".join(out)
        assert f"{'ok':<11} docs/guide.md" in text
        assert f"{'missing':<11} docs/missing.md  (required)" in text
        assert f"{'out-of-sync':<11} docs/edited.md" in text
        assert "1 ok, 1 out-of-sync, 1 missing" in text


class TestPairsScope:
    def test_named_pair_check_only(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        record(repo, "docs/guide.md")
        code, out, _ = run(repo, "verify", "docs/guide.zh.md")
        assert code == 0
        assert "named pair(s) consistent" in out[0]

    def test_rejects_out_of_scope_anchor(self, repo: Repo) -> None:
        code, _, err = run(repo, "verify", "src/code.md")
        assert code == 2
        assert any("not an in-scope pair" in line for line in err)

    def test_rejects_absent_anchor(self, repo: Repo) -> None:
        code, _, err = run(repo, "verify", "docs/ghost.md")
        assert code == 2
        assert any("names no pair on disk" in line for line in err)

    def test_record_named_pair(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        code, out, _ = run(repo, "record", "docs/guide.md")
        assert code == 0
        assert any("recorded docs/guide.i18n.yaml" in line for line in out)
        assert (repo.root / "docs/guide.i18n.yaml").is_file()

    def test_record_named_pair_missing_counterpart(self, repo: Repo) -> None:
        repo.write("docs/guide.md", EN_PAIR)
        code, _, err = run(repo, "record", "docs/guide.md")
        assert code == 2
        assert any("cannot record" in line for line in err)

    def test_record_all_skips_pairless_sources(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        repo.write("docs/lonely.md", EN_PAIR)
        code, out, _ = run(repo, "record", "--all")
        assert code == 0
        assert any("1 record(s) written" in line for line in out)

    def test_missing_manifest_exits_two(self, repo: Repo) -> None:
        (repo.root / ".hdsh/pairing.manifest.json").unlink()
        code, _, err = run(repo, "verify")
        assert code == 2
        assert any("manifest" in line.lower() for line in err)


class TestCachedMode:
    def test_cached_accepts_complete_staged_pair(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        record(repo, "docs/guide.md")
        repo.add_all()
        code, out, _ = run(repo, "verify", "--cached", "docs/guide.md")
        assert code == 0
        assert "staged pair(s) consistent" in out[0]

    def test_cached_rejects_drifted_staged_side(self, repo: Repo) -> None:
        write_pair(repo, "docs/guide.md")
        record(repo, "docs/guide.md")
        repo.write("docs/guide.md", EN_PAIR + "\ndrift\n")
        repo.add_all()
        code, _, err = run(repo, "verify", "--cached", "docs/guide.md")
        assert code == 1
        assert any("out of sync" in line for line in err)


def test_request_dataclass_defaults() -> None:
    request = PairingRequest(input="worktree", mode="check", scope="pairs")
    assert request.anchors == ()


class _UnreadableRepository:
    """Content-plane stub whose files exist but cannot be read."""

    inner: PairingRepository
    root: str
    index_mode: bool

    def __init__(self, inner: PairingRepository) -> None:
        self.inner = inner
        self.root = inner.root
        self.index_mode = inner.index_mode

    def repository_file_exists(self, file: str) -> bool:
        return self.inner.repository_file_exists(file)

    def read_repository_file(self, file: str) -> bytes | None:
        return None


def _run(repo: Repo, *args: str) -> tuple[int, list[str], list[str]]:
    out: list[str] = []
    err: list[str] = []
    request = _REQUEST_BUILDERS[args[0]](parse(args[0], *args[1:]))
    code = run_gate(request, str(repo.root), stdout=out.append, stderr=err.append)
    return code, out, err


ANCHOR = "docs/guide.md"
META = "docs/guide.i18n.yaml"


def gate_record(repo: Repo, anchor: str = ANCHOR) -> None:
    assert run_gate(record_request(parse("record", anchor)), str(repo.root)) == 0


class TestVerifyPlanes:
    def test_discovery_skips_excluded_directories(self, repo: Repo) -> None:
        repo.write("node_modules/x/README.md", "# x\n")
        repo.write(".local/contexts/prek/README.md", "# y\n")
        repo.write("docs/guide.md", en_pair("guide.zh.md"))
        repository = PairingRepository(str(repo.root))
        assert "docs/guide.md" in repository.discover_scope_files()
        assert "node_modules/x/README.md" not in repository.discover_scope_files()
        assert ".local/contexts/prek/README.md" not in repository.discover_scope_files()

    def test_write_unreadable_pair_fails_loud(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_pair(repo, ANCHOR)
        real_read = PairingRepository.read_repository_file

        def selective_read(self: PairingRepository, file: str) -> bytes | None:
            if file == ".hdsh/pairing.manifest.json":
                return real_read(self, file)
            return None

        monkeypatch.setattr(PairingRepository, "read_repository_file", selective_read)

        def always_exists(self: PairingRepository, file: str) -> bool:
            return True

        monkeypatch.setattr(PairingRepository, "repository_file_exists", always_exists)
        err: list[str] = []
        code = run_gate(
            record_request(parse("record", ANCHOR)),
            str(repo.root),
            stdout=print,
            stderr=err.append,
        )
        assert code == 2
        assert any("became unreadable" in line for line in err)

    def test_check_unreadable_pair_raises(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_record(repo)
        repository = PairingRepository(str(repo.root))
        # All three files exist, but their bytes cannot be read anymore.
        errors: list[str] = []
        state: dict[str, str] = {}
        with pytest.raises(RuntimeError, match="became unreadable"):
            _check_pair(
                ANCHOR,
                _UnreadableRepository(repository),
                lambda p: True,
                excluded=lambda p: False,
                generated=(),
                public_blob_root="",
                errors=errors,
                state=state,
            )

    def test_generated_region_mismatch_detected(self, repo: Repo) -> None:
        source = (
            en_pair("guide.zh.md")
            + "\n<!-- BEGIN GENERATED catalog -->\nalpha\n<!-- END GENERATED catalog -->\n"
        )
        zh = (
            zh_pair("guide.md")
            + "\n<!-- BEGIN GENERATED catalog -->\nbeta\n<!-- END GENERATED catalog -->\n"
        )
        repo.write(ANCHOR, source)
        repo.write("docs/guide.zh.md", zh)
        assert run_gate(record_request(parse("record", ANCHOR)), str(repo.root)) == 0
        err: list[str] = []
        code = run_gate(verify_request(parse("verify", ANCHOR)), str(repo.root), stderr=err.append)
        assert code == 1
        assert any(
            "generated regions differ beyond paired-document locale paths" in line for line in err
        )

    def test_generated_region_locale_only_difference_passes(self, repo: Repo) -> None:
        write_pair(repo, "docs/other.md")
        begin = "\n<!-- BEGIN GENERATED catalog -->\n"
        end = "\n<!-- END GENERATED catalog -->\n"
        source = en_pair("guide.zh.md") + begin + "See [x](other.md)." + end
        zh = zh_pair("guide.md") + begin + "See [x](other.zh.md)." + end
        repo.write(ANCHOR, source)
        repo.write("docs/guide.zh.md", zh)
        assert run_gate(record_request(parse("record", ANCHOR)), str(repo.root)) == 0
        assert run_gate(record_request(parse("record", "docs/other.md")), str(repo.root)) == 0
        code, _out, err = run(repo, "verify", ANCHOR)
        assert code == 0, err

    def test_generated_region_switcher_shaped_lines_normalize(self, repo: Repo) -> None:
        # Region normalization skips no switcher. The exemption is observable
        # only on an already-red pair —
        # a link the skip would exempt is by construction a wrong-locale body
        # link — so this pair fails for the locale violations, but its
        # switcher-shaped region lines normalize to the pair anchor and add no
        # "generated regions differ" violation.
        begin = "\n<!-- BEGIN GENERATED catalog -->\n"
        end = "\n<!-- END GENERATED catalog -->\n"
        source = en_pair("guide.zh.md") + begin + "# T\n\nEnglish | [中文](guide.zh.md)\n" + end
        zh = zh_pair("guide.md") + begin + "# T\n\nEnglish | [中文](guide.md)\n" + end
        repo.write(ANCHOR, source)
        repo.write("docs/guide.zh.md", zh)
        assert run_gate(record_request(parse("record", ANCHOR)), str(repo.root)) == 0
        code, _out, err = run(repo, "verify", ANCHOR)
        assert code == 1
        assert any("wrong locale" in line for line in err)
        assert not any("generated regions differ" in line for line in err)

    def test_generated_region_parse_error_detected(self, repo: Repo) -> None:
        source = en_pair("guide.zh.md") + "\n<!-- BEGIN GENERATED catalog -->\nno end marker\n"
        repo.write(ANCHOR, source)
        repo.write("docs/guide.zh.md", zh_pair("guide.md"))
        assert run_gate(record_request(parse("record", ANCHOR)), str(repo.root)) == 0
        err: list[str] = []
        code = run_gate(verify_request(parse("verify", ANCHOR)), str(repo.root), stderr=err.append)
        assert code == 1
        assert any("without an END" in line for line in err)

    def test_excluded_pair_meta_only_artifact(self, repo: Repo) -> None:
        repo.write("docs/AGENTS.i18n.yaml", "AGENTS.md: x\n")
        err: list[str] = []
        code = run_gate(verify_request(parse("verify")), str(repo.root), stderr=err.append)
        assert code == 1
        assert any("excluded from pairing" in line for line in err)

    def test_index_mode_named_anchor_absent_accepted(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_record(repo)
        repo.add_all()
        code, _out, _ = _run(repo, "verify", "--cached", "docs/guide.md", "docs/absent.md")
        assert code == 0

    def test_corpus_write_skips_unreadable(self, repo: Repo) -> None:
        repo.write("docs/lonely.md", en_pair("lonely.zh.md"))
        code, _out, _ = _run(repo, "record", "--all")
        assert code == 0

    def test_main_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("boom")

        monkeypatch.setattr(subprocess, "run", raising_run)
        with pytest.raises(SystemExit) as excinfo:
            tp_verify_module.verify_main(parse("verify"))
        assert excinfo.value.code == 2

    def test_gate_corpus_ignores_non_markdown_artifacts(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_record(repo)
        repo.write("docs/notes.txt", "not markdown\n")
        code, _, _ = _run(repo, "verify")
        assert code == 0

    def test_gate_write_pairs_scope_skips_unrecordable(self, repo: Repo) -> None:
        repo.write("docs/lonely.md", en_pair("lonely.zh.md"))
        code, _out, _ = _run(repo, "record", "docs/lonely.md")
        assert code == 2

    def test_gate_discovery_skips_out_of_scope_root_documents(self, repo: Repo) -> None:
        repo.write("NOTES.md", "# scratch notes\n")
        repo.write("docs/guide.md", en_pair("guide.zh.md"))
        repo.write("docs/guide.zh.md", zh_pair("guide.md"))
        gate_record(repo)
        code, _out, _ = _run(repo, "verify")
        assert code == 0

    def test_gate_write_twice_is_stable(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_record(repo)
        code, out, _ = _run(repo, "record", "--all")
        assert code == 0
        assert "0 record(s) written" in out[-1]

    def test_gate_corpus_with_excluded_source_and_sibling(self, repo: Repo) -> None:
        repo.write("docs/AGENTS.md", "# Agent instructions\n")
        repo.write("docs/AGENTS.zh.md", "# 说明\n")
        err: list[str] = []
        code = run_gate(verify_request(parse("verify")), str(repo.root), stderr=err.append)
        assert code == 1

    def test_write_all_skips_excluded_sources(self, repo: Repo) -> None:
        repo.write("docs/AGENTS.md", "# Agent instructions\n")
        write_pair(repo, ANCHOR)
        code, out, _ = _run(repo, "record", "--all")
        assert code == 0
        assert "1 record(s) written" in out[-1]


class TestGateMains:
    def test_gate_violations_print_to_stderr(
        self,
        repo: Repo,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        write_pair(repo, ANCHOR)
        record(repo, ANCHOR)
        repo.write("docs/guide.md", EN_PAIR + "\ndrift\n")
        monkeypatch.chdir(repo.root)
        assert tp_verify_module.verify_main(parse("verify")) == 1
        captured = capsys.readouterr()
        assert "bilingual pairing rules violated" in captured.err
        assert "out of sync" in captured.err
        assert "bilingual pairing rules violated" not in captured.out

    def test_absolute_switcher_accepted_when_root_configured(self, repo: Repo) -> None:
        root = "https://github.com/example/repo/blob/main/"
        repo.write(
            ".hdsh/pairing.manifest.json",
            json.dumps({**MANIFEST, "public_blob_root": root}, indent=2) + "\n",
        )
        repo.write(
            ANCHOR,
            en_pair("guide.zh.md").replace(
                "English | [中文](guide.zh.md)",
                f"English | [中文]({root}docs/guide.zh.md)",
            ),
        )
        repo.write("docs/guide.zh.md", zh_pair("guide.md"))
        record(repo, ANCHOR)
        code, _out, err = run(repo, "verify")
        assert code == 0, err

    def test_manifest_type_error_exits_two(self, repo: Repo) -> None:
        repo.write(".hdsh/pairing.manifest.json", "[]")
        err: list[str] = []
        code = run_gate(
            verify_request(parse("verify")), str(repo.root), stdout=print, stderr=err.append
        )
        assert code == 2
        assert any("expected an object" in line for line in err)

    def test_repository_root_outside_repo_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as excinfo:
            tp_verify_module._repository_root()
        assert excinfo.value.code == 2

    def test_repository_root_oserror_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("boom")

        monkeypatch.setattr(subprocess, "run", raising_run)
        with pytest.raises(SystemExit) as excinfo:
            tp_verify_module._repository_root()
        assert excinfo.value.code == 2

    def test_verify_main_records_and_checks(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_pair(repo, ANCHOR)
        repo.add_all()
        monkeypatch.chdir(repo.root)
        assert tp_verify_module.record_main(parse("record", ANCHOR)) == 0
        assert "record(s) written" in capsys.readouterr().out

    def test_record_main_usage_error(self, repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
        assert tp_verify_module.record_main(parse("record")) == 2
        assert "record requires" in capsys.readouterr().err

    def test_list_main_reports_corpus(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_pair(repo, ANCHOR)
        monkeypatch.chdir(repo.root)
        assert tp_verify_module.list_main(parse("list")) == 0
        assert "0 ok" in capsys.readouterr().out
