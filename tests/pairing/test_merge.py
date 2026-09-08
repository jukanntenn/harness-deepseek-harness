"""Fail-closed merge composition for pairing records over real repositories."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import hdsh.pairing.merge as merge_module
import hdsh.pairing.verify as verify_module
from hdsh.pairing.git import GitError, blob_hash
from hdsh.pairing.merge import (
    PairingMergeResult,
    merge_records,
    pairing_source,
    resolve_conflicts,
)
from hdsh.pairing.merge import (
    main as merge_main,
)
from hdsh.pairing.records import PairingRecord, pair_paths, parse_record, render_record
from hdsh.pairing.verify import record_request, run_gate, verify_request
from tests.helpers import Repo, en_pair, git, parse_command, write_pair, zh_pair

ANCHOR = "docs/guide.md"
META = "docs/guide.i18n.yaml"
MANUAL_ANCHOR = "docs/manual.md"
MANUAL_META = "docs/manual.i18n.yaml"
DRIVER = Path(__file__).resolve().parents[2] / "scripts" / "pairing-merge-driver.sh"


def gate_write(repo: Repo, anchor: str = ANCHOR) -> None:
    """Record one pair through the gate CLI."""
    request = record_request(parse_command(verify_module.register, ["record", anchor]))
    assert run_gate(request, str(repo.root)) == 0


def gate_check(repo: Repo, anchor: str) -> int:
    """Run one named-pair verify through the gate CLI."""
    request = verify_request(parse_command(verify_module.register, ["verify", anchor]))
    return run_gate(request, str(repo.root))


def merge_cli(*args: str) -> int:
    """Run ``hdsh pairing merge`` with parsed arguments."""
    return merge_main(parse_command(merge_module.register, ["merge", *args]))


def build_divergent_pair(repo: Repo) -> dict[str, str]:
    """Create a base pair and two branches whose owner merges stay clean.

    The main branch rewrites the body paragraph; the side branch appends a
    new paragraph. Git therefore merges both owners cleanly while the two
    re-recorded sidecars conflict on their hash lines.

    Returns:
        The ``base``, ``main``, and ``side`` sidecar texts.
    """
    write_pair(repo, ANCHOR)
    gate_write(repo)
    base_text = (repo.root / META).read_text(encoding="utf-8")
    repo.commit("base pair")
    git("branch", "side", cwd=repo.root)
    repo.write(
        ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote the paragraph.")
    )
    repo.write(
        "docs/guide.zh.md", zh_pair("guide.md").replace("正文段落。", "主分支改写了这一段。")
    )
    gate_write(repo)
    main_text = (repo.root / META).read_text(encoding="utf-8")
    repo.commit("main-side pair")
    git("checkout", "side", cwd=repo.root)
    repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends a paragraph.\n")
    repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增一段。\n")
    gate_write(repo)
    side_text = (repo.root / META).read_text(encoding="utf-8")
    repo.commit("side-side pair")
    return {"base": base_text, "main": main_text, "side": side_text}


def compose(repo: Repo, texts: dict[str, str], *, meta: str = META) -> PairingMergeResult:
    """Run the composition with the fixture's three sidecar texts."""
    return merge_records(
        str(repo.root),
        meta,
        texts["base"],
        texts["main"],
        texts["side"],
        is_pair_source=pairing_source(str(repo.root)),
        generated=(),
        public_blob_root="",
    )


def start_conflicted_merge(repo: Repo) -> None:
    """Run ``git merge`` so only the sidecar conflicts."""
    merge = git("merge", "main", cwd=repo.root, check=False)
    assert merge.returncode != 0
    assert META in git("ls-files", "--unmerged", cwd=repo.root).stdout


def stage_text(repo: Repo, stage: str) -> str:
    """Read one unmerged stage of the sidecar."""
    output = git("ls-files", "--unmerged", cwd=repo.root).stdout
    for line in output.splitlines():
        meta, name = line.split("\t")
        fields = meta.split(" ")
        if fields[2] == stage and name == META:
            return git("cat-file", "blob", fields[1], cwd=repo.root).stdout
    raise AssertionError(f"no stage {stage} entry for {META}")


class TestMergeComposition:
    def test_composes_clean_three_way_record(self, repo: Repo) -> None:
        texts = build_divergent_pair(repo)
        start_conflicted_merge(repo)
        result = compose(repo, texts)
        source = result.source_content.decode("utf-8")
        assert "Main rewrote the paragraph." in source
        assert "Side appends a paragraph." in source
        record = parse_record(result.record_text, pair_paths(ANCHOR))
        assert record is not None
        assert record.source_hash == result.source_hash

    def test_conflicting_owner_merge_fails_closed(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("base pair")
        git("branch", "side", cwd=repo.root)
        for checkout_side, word in ((False, "MAIN"), (True, "SIDE")):
            if checkout_side:
                git("checkout", "side", cwd=repo.root)
            repo.write(ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", f"{word} VERSION"))
            repo.write(
                "docs/guide.zh.md", zh_pair("guide.md").replace("正文段落。", f"{word}版本正文。")
            )
            gate_write(repo)
            repo.commit(f"{word.lower()} edit")
        git("merge", "main", cwd=repo.root, check=False)
        with pytest.raises(ValueError, match="has content conflicts"):
            compose(
                repo,
                {
                    "base": stage_text(repo, "1"),
                    "main": stage_text(repo, "2"),
                    "side": stage_text(repo, "3"),
                },
            )

    def test_out_of_corpus_meta_is_rejected(self, repo: Repo) -> None:
        texts = build_divergent_pair(repo)
        with pytest.raises(ValueError, match="outside the active bilingual documentation corpus"):
            compose(repo, texts, meta="outside/guide.i18n.yaml")

    def test_excluded_meta_is_rejected(self, repo: Repo) -> None:
        texts = build_divergent_pair(repo)
        with pytest.raises(
            ValueError, match="excluded from the active bilingual documentation corpus"
        ):
            compose(repo, texts, meta="docs/AGENTS.i18n.yaml")

    def test_absolute_meta_path_is_rejected(self, repo: Repo) -> None:
        texts = build_divergent_pair(repo)
        with pytest.raises(ValueError, match="repository-relative"):
            compose(repo, texts, meta="/docs/guide.i18n.yaml")

    def test_custom_merge_attribute_is_rejected(self, repo: Repo) -> None:
        texts = build_divergent_pair(repo)
        repo.write(".gitattributes", "*.md merge=ours\n")
        repo.commit("attributes")
        with pytest.raises(ValueError, match="only composes Git's default text merge"):
            compose(repo, texts)

    def test_foreign_merge_default_is_rejected(self, repo: Repo) -> None:
        texts = build_divergent_pair(repo)
        git("config", "merge.default", "ours", cwd=repo.root)
        with pytest.raises(ValueError, match="merge.default=ours"):
            compose(repo, texts)

    def test_malformed_input_record_is_rejected(self, repo: Repo) -> None:
        texts = build_divergent_pair(repo)
        with pytest.raises(ValueError, match="not a valid two-hash pairing record"):
            compose(repo, {**texts, "base": "garbage"})

    def test_missing_object_is_rejected(self, repo: Repo) -> None:
        texts = build_divergent_pair(repo)
        with pytest.raises(Exception, match="failed|not its SHA-1"):
            compose(repo, {**texts, "base": f"guide.md: {'0' * 40}\nguide.zh.md: {'0' * 40}\n"})

    def test_structure_breaking_clean_merge_is_rejected(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        base_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("base pair")
        git("branch", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md").replace("English | [中文](guide.zh.md)", "plain"))
        gate_write(repo)
        main_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("main drops en switcher")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends a paragraph.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增一段。\n")
        gate_write(repo)
        side_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("side keeps structure")
        with pytest.raises(ValueError, match="lost its language-switcher link"):
            compose(repo, {"base": base_text, "main": main_text, "side": side_text})

    def test_composes_with_a_corpus_target_present_only_in_the_index(self, repo: Repo) -> None:
        # Link resolution during composition reads the merge input plane —
        # the index (plus merge heads), never the working tree — so a target
        # staged and then deleted from the worktree still resolves.
        write_pair(repo, "docs/reference.md")
        repo.add_all()
        source = en_pair("guide.zh.md").replace("Body paragraph.", "See [ref](reference.md#sec).")
        zh = zh_pair("guide.md").replace("正文段落。", "参见[参考](reference.zh.md#sec)。")
        repo.write(ANCHOR, source)
        repo.write("docs/guide.zh.md", zh)
        gate_write(repo)
        record_text = (repo.root / META).read_text(encoding="utf-8")
        (repo.root / "docs/reference.md").unlink()
        (repo.root / "docs/reference.zh.md").unlink()
        result = merge_records(
            str(repo.root),
            META,
            record_text,
            record_text,
            record_text,
            is_pair_source=pairing_source(str(repo.root)),
            generated=(),
            public_blob_root="",
        )
        assert result.zh_content.decode("utf-8") == zh

    def test_dotted_meta_name_is_not_treated_as_an_escape(self, repo: Repo) -> None:
        # Only "", "..", and ".."-prefixed paths escape the repository; a
        # sibling literally named "...guide.i18n.yaml" stays inside and fails
        # the corpus check instead of the escape check.
        with pytest.raises(ValueError, match="outside the active bilingual documentation corpus"):
            merge_records(
                str(repo.root),
                "...guide.i18n.yaml",
                "a",
                "b",
                "c",
                is_pair_source=lambda path: True,
                generated=(),
                public_blob_root="",
            )


class TestResolveMode:
    def test_resolves_staged_sidecar_conflicts(self, repo: Repo) -> None:
        build_divergent_pair(repo)
        start_conflicted_merge(repo)
        resolved = resolve_conflicts(
            str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
        )
        assert resolved == [META]
        assert git("ls-files", "--unmerged", cwd=repo.root).stdout.strip() == ""
        git("commit", "--no-edit", cwd=repo.root)
        assert gate_check(repo, ANCHOR) == 0

    def test_edited_conflict_content_is_refused(self, repo: Repo) -> None:
        build_divergent_pair(repo)
        start_conflicted_merge(repo)
        meta = repo.root / META
        # Editing a staged data line (not merely appending a comment) is the
        # manual work the resolver refuses to overwrite.
        meta.write_text(
            meta.read_text(encoding="utf-8").replace("guide.md: ", "guide.md: 0", 1),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="refusing to overwrite manual work"):
            resolve_conflicts(
                str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
            )

    def test_no_conflicts_reports_empty(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("pair")
        assert (
            resolve_conflicts(
                str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
            )
            == []
        )

    def test_missing_worktree_sidecar_is_one_aggregate_failure(self, repo: Repo) -> None:
        # A sidecar deleted from the worktree mid-resolution is one sidecar's
        # failure, recorded and aggregated like any other: the other
        # composable pair is still resolved, written, and staged.
        write_pair(repo, ANCHOR)
        write_pair(repo, MANUAL_ANCHOR)
        gate_write(repo)
        gate_write(repo, MANUAL_ANCHOR)
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(
            ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote the paragraph.")
        )
        repo.write(
            MANUAL_ANCHOR, en_pair("manual.zh.md").replace("Body paragraph.", "Main rewrote it.")
        )
        gate_write(repo)
        gate_write(repo, MANUAL_ANCHOR)
        repo.commit("main edits sources")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends a paragraph.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增一段。\n")
        repo.write(MANUAL_ANCHOR, en_pair("manual.zh.md") + "\nSide appends a paragraph.\n")
        repo.write("docs/manual.zh.md", zh_pair("manual.md") + "\n侧分支新增一段。\n")
        gate_write(repo)
        gate_write(repo, MANUAL_ANCHOR)
        repo.commit("side appends")
        git("checkout", "main", cwd=repo.root)
        assert git("merge", "side", cwd=repo.root, check=False).returncode != 0
        (repo.root / MANUAL_META).unlink()
        with pytest.raises(ValueError, match=MANUAL_META) as error:
            resolve_conflicts(
                str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
            )
        assert "No such file or directory" in str(error.value)
        assert _unmerged_paths(repo) == {MANUAL_META}
        source = (repo.root / ANCHOR).read_text(encoding="utf-8")
        zh = (repo.root / "docs/guide.zh.md").read_text(encoding="utf-8")
        assert "Main rewrote the paragraph." in source
        assert "Side appends a paragraph." in source
        assert "侧分支新增一段。" in zh
        assert (repo.root / META).read_text(encoding="utf-8") == render_record(
            pair_paths(ANCHOR),
            PairingRecord(
                source_hash=blob_hash(source.encode("utf-8")),
                zh_hash=blob_hash(zh.encode("utf-8")),
            ),
        )


class TestMergeCli:
    def test_probe_succeeds(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert merge_cli("--probe") == 0
        assert capsys.readouterr().out == ""

    def test_resolve_reports_no_conflicts(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("pair")
        _in_repo(repo, lambda: merge_cli("--resolve"))
        assert "no unresolved pairing records" in capsys.readouterr().out

    def test_unknown_flags_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            merge_cli("--bogus", "a")

    def test_missing_mode_is_a_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert merge_cli() == 2
        assert "hdsh pairing merge: usage:" in capsys.readouterr().err

    def test_wrong_driver_arity_is_a_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert merge_cli("a", "b", "c") == 2
        assert "hdsh pairing merge: usage:" in capsys.readouterr().err

    def test_driver_form_with_unreadable_paths_fails(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert merge_cli("gone-ancestor", "gone-current", "gone-other", "gone-meta") == 1
        captured = capsys.readouterr()
        assert "hdsh pairing merge:" in captured.err
        assert "rerun `hdsh pairing merge --resolve`" in captured.err

    def test_driver_mode_writes_composed_record(self, repo: Repo, tmp_path: Path) -> None:
        build_divergent_pair(repo)
        start_conflicted_merge(repo)
        ancestor = tmp_path / "ancestor"
        current = tmp_path / "current"
        other = tmp_path / "other"
        ancestor.write_text(stage_text(repo, "1"), encoding="utf-8")
        current.write_text(stage_text(repo, "2"), encoding="utf-8")
        other.write_text(stage_text(repo, "3"), encoding="utf-8")
        _in_repo(
            repo,
            lambda: merge_cli(str(ancestor), str(current), str(other), META),
        )
        record = parse_record(current.read_text(encoding="utf-8"), pair_paths(ANCHOR))
        assert record is not None


def _in_repo(repo: Repo, action: Callable[[], object]) -> None:
    """Run one callable with the process cwd inside the repository."""
    previous = str(Path.cwd())
    os.chdir(repo.root)
    try:
        action()
    finally:
        os.chdir(previous)


def _merge_env(fake_bin: Path) -> dict[str, str]:
    """The merge environment with one fake-``uv`` directory prepended to PATH."""
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


def _fake_uv_bin(root: Path, script: str) -> Path:
    """One PATH directory whose ``uv`` runs ``script``."""
    directory = root / "fake-bin"
    directory.mkdir(parents=True, exist_ok=True)
    uv = directory / "uv"
    uv.write_text(script, encoding="utf-8")
    uv.chmod(0o755)
    return directory


def _runtime_uv_bin(root: Path) -> Path:
    """One PATH directory whose ``uv`` forwards to the real hdsh console module.

    The driver script probes and executes ``uv run --no-sync hdsh …``; the
    shim drops those three leading arguments and runs ``python -m hdsh`` with
    the rest, so the shell script, the real CLI, and real git all execute —
    only the environment linkage is synthetic.
    """
    return _fake_uv_bin(root, f'#!/bin/sh\nshift 3\nexec "{sys.executable}" -m hdsh "$@"\n')


def _install_driver(repo: Repo, runtime_bin: Path) -> dict[str, str]:
    """Register the shipped driver for ``*.i18n.yaml`` and return the env."""
    git(
        "config",
        "merge.hdsh-pairing.driver",
        f"{shlex.quote(str(DRIVER))} %O %A %B %P",
        cwd=repo.root,
    )
    return _merge_env(runtime_bin)


def _git_merge(repo: Repo, ref: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run one real ``git merge`` with the given environment."""
    return subprocess.run(
        ["git", "-C", str(repo.root), "merge", "--no-edit", ref],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _expect_merged_pair(repo: Repo) -> None:
    """Assert the guide pair's worktree bytes equal the clean composition."""
    source = (repo.root / ANCHOR).read_text(encoding="utf-8")
    zh = (repo.root / "docs/guide.zh.md").read_text(encoding="utf-8")
    assert "Main rewrote the paragraph." in source
    assert "Side appends a paragraph." in source
    assert "主分支改写了这一段。" in zh
    assert "侧分支新增一段。" in zh
    assert (repo.root / META).read_text(encoding="utf-8") == render_record(
        pair_paths(ANCHOR),
        PairingRecord(
            source_hash=blob_hash(source.encode("utf-8")),
            zh_hash=blob_hash(zh.encode("utf-8")),
        ),
    )


def _unmerged_paths(repo: Repo) -> set[str]:
    """Every path with unresolved index stages."""
    listing = git("ls-files", "--unmerged", cwd=repo.root).stdout
    return {line.split("\t")[1] for line in listing.split("\n") if line}


def test_repository_predicate_reads_staged_manifest(repo: Repo) -> None:
    write_pair(repo, ANCHOR)
    gate_write(repo)
    repo.commit("pair")
    predicate = pairing_source(str(repo.root))
    assert predicate(ANCHOR)
    assert not predicate("docs/AGENTS.md")


class TestMergeGuardBranches:
    def test_read_git_blob_hash_mismatch(self, repo: Repo) -> None:
        from hdsh.pairing.git import blob_hash

        content = b"data\n"
        real = blob_hash(content)
        wrong = "0" * 40 if real[0] != "0" else "1" * 40
        monkey = pytest.MonkeyPatch()
        monkey.setattr(merge_module, "run_git", lambda root, args, op, *, input_bytes=None: content)
        try:
            with pytest.raises(ValueError, match="not its SHA-1 git blob hash"):
                merge_module._read_git_blob(str(repo.root), wrong, "owner")
        finally:
            monkey.undo()

    def test_read_merge_default_oserror(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("boom")

        monkeypatch.setattr(merge_module.subprocess, "run", raising_run)
        with pytest.raises(GitError, match="reading merge.default failed"):
            merge_module._read_merge_default(str(repo.root))

    def test_read_merge_default_bad_status(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = subprocess.CompletedProcess(["git"], 128, b"", b"fatal")
        monkeypatch.setattr(merge_module.subprocess, "run", lambda a, **k: completed)
        with pytest.raises(GitError, match="status 128"):
            merge_module._read_merge_default(str(repo.root))

    def test_run_text_merge_oserror(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("no git")

        monkeypatch.setattr(merge_module.subprocess, "run", raising_run)
        with pytest.raises(GitError, match="merging x failed"):
            merge_module._run_text_merge(str(repo.root), "x", b"a\n", b"b\n", b"c\n")

    def test_zh_switcher_loss_rejected(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        base_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(
            "docs/guide.zh.md", zh_pair("guide.md").replace("[English](guide.md) | 中文", "plain")
        )
        gate_write(repo)
        main_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("main drops zh switcher")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增。\n")
        gate_write(repo)
        side_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("side keeps")
        with pytest.raises(ValueError, match="guide.zh.md clean merge lost"):
            merge_records(
                str(repo.root),
                META,
                base_text,
                main_text,
                side_text,
                is_pair_source=lambda path: path == ANCHOR,
                generated=(),
                public_blob_root="",
            )

    def test_generated_source_en_switcher_exempt_in_merge(self, repo: Repo) -> None:
        plain_en = en_pair("guide.zh.md").replace(
            "English | [中文](guide.zh.md)", "generated: no switcher"
        )
        write_pair(repo, ANCHOR, source=lambda target: plain_en)
        gate_write(repo)
        base_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(ANCHOR, plain_en.replace("Body paragraph.", "Main rewrote it."))
        gate_write(repo)
        main_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("main rewrote")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, plain_en + "\nSide appends.\n")
        gate_write(repo)
        side_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("side appends")
        result = merge_records(
            str(repo.root),
            META,
            base_text,
            main_text,
            side_text,
            is_pair_source=pairing_source(str(repo.root)),
            generated=(ANCHOR,),
            public_blob_root="",
        )
        assert result.record_text
        with pytest.raises(ValueError, match="guide.md clean merge lost"):
            merge_records(
                str(repo.root),
                META,
                base_text,
                main_text,
                side_text,
                is_pair_source=pairing_source(str(repo.root)),
                generated=(),
                public_blob_root="",
            )

    def test_locale_violation_in_clean_merge_rejected(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        write_pair(repo, "docs/other.md")
        gate_write(repo)
        gate_write_other = run_gate(
            record_request(parse_command(verify_module.register, ["record", "docs/other.md"])),
            str(repo.root),
        )
        assert gate_write_other == 0
        base_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(
            ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "See [other](other.zh.md).")
        )
        gate_write(repo)
        main_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("main adds wrong-locale link")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增。\n")
        gate_write(repo)
        side_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("side keeps")
        predicate = pairing_source(str(repo.root))
        with pytest.raises(ValueError, match="clean merge uses"):
            merge_records(
                str(repo.root),
                META,
                base_text,
                main_text,
                side_text,
                is_pair_source=predicate,
                generated=(),
                public_blob_root="",
            )

    def test_structural_divergence_in_clean_merge_rejected(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        base_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\n- extra en item\n")
        gate_write(repo)
        main_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("main adds en-only list")
        git("checkout", "side", cwd=repo.root)
        repo.write(
            ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "Side rewrote the paragraph.")
        )
        repo.write(
            "docs/guide.zh.md", zh_pair("guide.md").replace("正文段落。", "侧分支改写了这一段。")
        )
        gate_write(repo)
        side_text = (repo.root / META).read_text(encoding="utf-8")
        repo.commit("side keeps")
        with pytest.raises(ValueError, match="diverge structurally"):
            merge_records(
                str(repo.root),
                META,
                base_text,
                main_text,
                side_text,
                is_pair_source=lambda path: path == ANCHOR,
                generated=(),
                public_blob_root="",
            )

    def test_meta_escaping_repository_rejected(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        with pytest.raises(ValueError, match="escapes the repository"):
            merge_records(
                str(repo.root),
                "../outside.i18n.yaml",
                "a",
                "b",
                "c",
                is_pair_source=lambda path: True,
                generated=(),
                public_blob_root="",
            )

    def test_unmerged_listing_malformed_entry(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            merge_module, "run_git", lambda root, args, op, *, input_bytes=None: b"garbage entry\0"
        )
        with pytest.raises(GitError, match="malformed unmerged entry"):
            resolve_conflicts(str(repo.root), lambda p: True, generated=(), public_blob_root="")

    def test_unmerged_listing_skips_non_sidecars(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            merge_module,
            "run_git",
            lambda root, args, op, *, input_bytes=None: b"100644 abcdef 1\tREADME.md\0",
        )
        assert (
            resolve_conflicts(str(repo.root), lambda p: True, generated=(), public_blob_root="")
            == []
        )

    def test_assert_unedited_accepts_text_merge_result(self, repo: Repo) -> None:
        from hdsh.pairing.records import PairingRecord, PairPaths, render_record

        paths = PairPaths(ANCHOR, "docs/guide.zh.md", META)

        def record(first: str, second: str) -> str:
            return render_record(paths, PairingRecord(source_hash=first, zh_hash=second))

        # The resolver only text-merges and compares here, so synthetic texts
        # with separable changes exercise the clean-merge acceptance path.
        ancestor = "header\nguide.md: one\nspacer\nguide.zh.md: two\n"
        current = "header\nguide.md: ONE\nspacer\nguide.zh.md: two\n"
        other = "header\nguide.md: one\nspacer\nguide.zh.md: two\ntail\n"
        clean = merge_module._run_text_merge(str(repo.root), META, ancestor, current, other)
        assert clean[1] == 0
        (repo.root / META).parent.mkdir(parents=True, exist_ok=True)
        (repo.root / META).write_bytes(clean[0])
        merge_module._assert_unedited_sidecar(str(repo.root), META, ancestor, current, other)

    def test_resolve_add_delete_conflict_reports_manual(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        (repo.root / ANCHOR).unlink()
        (repo.root / "docs/guide.zh.md").unlink()
        (repo.root / META).unlink()
        repo.commit("main deletes pair")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增。\n")
        gate_write(repo)
        repo.commit("side edits pair")
        git("merge", "main", cwd=repo.root, check=False)
        with pytest.raises(ValueError, match="add/delete or incomplete-stage"):
            resolve_conflicts(
                str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
            )

    def test_resolve_refuses_unstaged_owner_bytes(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(
            ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote the paragraph.")
        )
        repo.write(
            "docs/guide.zh.md", zh_pair("guide.md").replace("正文段落。", "主分支改写了这一段。")
        )
        gate_write(repo)
        repo.commit("main side")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends a paragraph.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增一段。\n")
        gate_write(repo)
        repo.commit("side side")
        git("merge", "main", cwd=repo.root, check=False)
        # Tamper with the worktree owner bytes after the merge staged them.
        (repo.root / ANCHOR).write_text(
            (repo.root / ANCHOR).read_text(encoding="utf-8") + "unstaged drift\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unstaged content"):
            resolve_conflicts(
                str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
            )

    def test_resolve_reports_staged_owner_mismatch(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(
            ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote the paragraph.")
        )
        repo.write(
            "docs/guide.zh.md", zh_pair("guide.md").replace("正文段落。", "主分支改写了这一段。")
        )
        gate_write(repo)
        repo.commit("main side")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends a paragraph.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增一段。\n")
        gate_write(repo)
        repo.commit("side side")
        git("merge", "main", cwd=repo.root, check=False)
        original = merge_module.read_git_index_blob

        def skewed(root: str, path: str) -> tuple[str, bytes] | None:
            staged = original(root, path)
            if staged is not None and path == ANCHOR:
                return ("f" * 40, staged[1])
            return staged

        monkeypatch.setattr(merge_module, "read_git_index_blob", skewed)
        with pytest.raises(ValueError, match="staged merge does not match"):
            resolve_conflicts(
                str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
            )

    def test_resolve_staged_zh_owner_mismatch(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote it."))
        repo.write("docs/guide.zh.md", zh_pair("guide.md").replace("正文段落。", "主分支改写。"))
        gate_write(repo)
        repo.commit("main")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增。\n")
        gate_write(repo)
        repo.commit("side")
        git("merge", "main", cwd=repo.root, check=False)
        original = merge_module.read_git_index_blob

        def skewed(root: str, path: str) -> tuple[str, bytes] | None:
            staged = original(root, path)
            if staged is not None and path == "docs/guide.zh.md":
                return ("f" * 40, staged[1])
            return staged

        monkeypatch.setattr(merge_module, "read_git_index_blob", skewed)
        with pytest.raises(ValueError, match="guide.zh.md staged merge does not match"):
            resolve_conflicts(
                str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
            )

    def test_merge_cli_resolve_prints_resolved_paths(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Build one composable sidecar conflict through the shared fixture flow.
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote it."))
        repo.write("docs/guide.zh.md", zh_pair("guide.md").replace("正文段落。", "主分支改写。"))
        gate_write(repo)
        repo.commit("main")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增。\n")
        gate_write(repo)
        repo.commit("side")
        git("merge", "main", cwd=repo.root, check=False)
        _in_repo(repo, lambda: merge_cli("--resolve"))
        assert "resolved docs/guide.i18n.yaml" in capsys.readouterr().out

    def test_merge_text_and_set_attributes_accepted(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.write(".gitattributes", "*.md merge=text\n")
        repo.commit("text attribute")
        texts = {
            "base": (repo.root / META).read_text(encoding="utf-8"),
            "main": (repo.root / META).read_text(encoding="utf-8"),
            "side": (repo.root / META).read_text(encoding="utf-8"),
        }
        result = merge_records(
            str(repo.root),
            META,
            texts["base"],
            texts["main"],
            texts["side"],
            is_pair_source=pairing_source(str(repo.root)),
            generated=(),
            public_blob_root="",
        )
        assert result.record_text

    def test_bare_merge_attribute_set_value(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.write(".gitattributes", "*.md merge\n")
        repo.commit("bare merge attribute")
        record = (repo.root / META).read_text(encoding="utf-8")
        result = merge_records(
            str(repo.root),
            META,
            record,
            record,
            record,
            is_pair_source=pairing_source(str(repo.root)),
            generated=(),
            public_blob_root="",
        )
        assert result.record_text

    def test_unspecified_attribute_with_text_merge_default(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        git("config", "merge.default", "text", cwd=repo.root)
        record = (repo.root / META).read_text(encoding="utf-8")
        result = merge_records(
            str(repo.root),
            META,
            record,
            record,
            record,
            is_pair_source=pairing_source(str(repo.root)),
            generated=(),
            public_blob_root="",
        )
        assert result.record_text

    def test_resolve_accepts_stage_sidecar_worktree(self, repo: Repo) -> None:
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote it."))
        repo.write("docs/guide.zh.md", zh_pair("guide.md").replace("正文段落。", "主分支改写。"))
        gate_write(repo)
        repo.commit("main")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增。\n")
        gate_write(repo)
        repo.commit("side")
        git("merge", "main", cwd=repo.root, check=False)
        # Restore the current stage's sidecar bytes: the unedited guard accepts
        # a worktree that equals either recorded stage.
        git("checkout", "--ours", META, cwd=repo.root)
        resolved = resolve_conflicts(
            str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
        )
        assert resolved == [META]


class TestPairingMergeDriver:
    """The shipped ``scripts/pairing-merge-driver.sh`` under real git merges.

    Integration cases: the registered driver composes and
    commits through a working runtime, sees merge-head-only link targets,
    leaves an ordinary text conflict when the runtime is unavailable, keeps a
    clean text fallback unresolved, survives a pre-merge-commit rejection,
    and resolves safe pairs while aggregating owner conflicts.
    """

    def _setup_attributes(self, repo: Repo) -> None:
        """Commit the merge-driver attribute into the fixture's base commit."""
        repo.write(".gitattributes", "*.i18n.yaml merge=hdsh-pairing\n")

    def test_composes_and_commits_through_the_real_runtime(
        self, repo: Repo, tmp_path: Path
    ) -> None:
        self._setup_attributes(repo)
        build_divergent_pair(repo)
        env = _install_driver(repo, _runtime_uv_bin(tmp_path))
        head_before = git("rev-parse", "HEAD", cwd=repo.root).stdout.strip()

        merge = _git_merge(repo, "main", env)

        assert merge.returncode == 0, merge.stderr
        assert git("diff", "--name-only", "--diff-filter=U", cwd=repo.root).stdout.strip() == ""
        assert git("rev-parse", "HEAD", cwd=repo.root).stdout.strip() != head_before
        _expect_merged_pair(repo)

    def test_sees_a_pair_target_added_by_the_merged_branch(
        self, repo: Repo, tmp_path: Path
    ) -> None:
        self._setup_attributes(repo)
        write_pair(repo, ANCHOR)
        gate_write(repo)
        repo.commit("base")
        git("branch", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md").replace("Body paragraph.", "See [x](other.md)."))
        repo.write(
            "docs/guide.zh.md",
            zh_pair("guide.md").replace("正文段落。", "参见[另一个](other.zh.md)。"),
        )
        gate_write(repo)
        repo.commit("main links the new pair")
        git("checkout", "side", cwd=repo.root)
        repo.write(ANCHOR, en_pair("guide.zh.md") + "\nSide appends a paragraph.\n")
        repo.write("docs/guide.zh.md", zh_pair("guide.md") + "\n侧分支新增一段。\n")
        gate_write(repo)
        write_pair(repo, "docs/other.md")
        gate_write(repo, "docs/other.md")
        repo.commit("side edits guide and adds the target")
        git("checkout", "main", cwd=repo.root)
        env = _install_driver(repo, _runtime_uv_bin(tmp_path))

        merge = _git_merge(repo, "side", env)

        assert merge.returncode == 0, merge.stderr
        assert "See [x](other.md)." in (repo.root / ANCHOR).read_text(encoding="utf-8")
        assert "参见[另一个](other.zh.md)。" in (repo.root / "docs/guide.zh.md").read_text(
            encoding="utf-8"
        )

    def test_unavailable_runtime_leaves_a_recoverable_conflict(
        self, repo: Repo, tmp_path: Path
    ) -> None:
        self._setup_attributes(repo)
        build_divergent_pair(repo)
        env = _install_driver(repo, _fake_uv_bin(tmp_path, "#!/bin/sh\nexit 72\n"))
        head_before = git("rev-parse", "HEAD", cwd=repo.root).stdout.strip()

        merge = _git_merge(repo, "main", env)

        assert merge.returncode == 1
        assert "runtime is unavailable; leaving an ordinary text conflict" in merge.stderr
        assert git("rev-parse", "HEAD", cwd=repo.root).stdout.strip() == head_before
        assert git("rev-parse", "--verify", "MERGE_HEAD", cwd=repo.root).stdout.strip() != ""
        assert git("diff", "--name-only", "--diff-filter=U", cwd=repo.root).stdout.strip() == META
        stages = git("ls-files", "--unmerged", "--", META, cwd=repo.root).stdout
        assert len([line for line in stages.split("\n") if line]) == 3
        conflicted = (repo.root / META).read_text(encoding="utf-8")
        assert "<<<<<<< docs/guide.i18n.yaml:current" in conflicted
        for stage in ("2", "3"):
            for line in stage_text(repo, stage).split("\n"):
                if line and not line.startswith("#"):
                    assert line in conflicted
        assert resolve_conflicts(
            str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
        ) == [META]
        _expect_merged_pair(repo)

    def test_probe_failure_is_not_rescued_by_unrelated_runtime_success(
        self, repo: Repo, tmp_path: Path
    ) -> None:
        self._setup_attributes(repo)
        build_divergent_pair(repo)
        script = (
            "#!/bin/sh\n"
            'for argument in "$@"; do\n'
            '  if [ "$argument" = "--version" ]; then exit 0; fi\n'
            "done\n"
            "exit 72\n"
        )
        env = _install_driver(repo, _fake_uv_bin(tmp_path, script))

        merge = _git_merge(repo, "main", env)

        assert merge.returncode == 1
        assert "runtime is unavailable" in merge.stderr
        assert "<<<<<<< docs/guide.i18n.yaml:current" in (repo.root / META).read_text(
            encoding="utf-8"
        )

    def test_clean_text_fallback_stays_unresolved_until_confirmed(
        self, repo: Repo, tmp_path: Path
    ) -> None:
        def commit_with_separator(source: str, zh: str, message: str) -> None:
            repo.write(ANCHOR, source)
            repo.write("docs/guide.zh.md", zh)
            gate_write(repo)
            meta = repo.root / META
            meta.write_text(
                meta.read_text(encoding="utf-8").replace(
                    "\nguide.zh.md:",
                    "\n# Stable separator for independent line merges.\nguide.zh.md:",
                ),
                encoding="utf-8",
            )
            repo.commit(message)

        main_source = en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote it.")
        side_zh = zh_pair("guide.md").replace("正文段落。", "主分支改写。")
        self._setup_attributes(repo)
        commit_with_separator(en_pair("guide.zh.md"), zh_pair("guide.md"), "base")
        git("branch", "side", cwd=repo.root)
        commit_with_separator(main_source, zh_pair("guide.md"), "main changes the source")
        git("checkout", "side", cwd=repo.root)
        commit_with_separator(en_pair("guide.zh.md"), side_zh, "side changes the translation")
        git("checkout", "main", cwd=repo.root)
        env = _install_driver(repo, _fake_uv_bin(tmp_path, "#!/bin/sh\nexit 72\n"))

        merge = _git_merge(repo, "side", env)

        assert merge.returncode == 1
        assert _unmerged_paths(repo) == {META}
        canonical = render_record(
            pair_paths(ANCHOR),
            PairingRecord(
                source_hash=blob_hash(main_source.encode("utf-8")),
                zh_hash=blob_hash(side_zh.encode("utf-8")),
            ),
        )
        with_separator = canonical.replace(
            "\nguide.zh.md:", "\n# Stable separator for independent line merges.\nguide.zh.md:"
        )
        assert (repo.root / META).read_text(encoding="utf-8") == with_separator
        assert resolve_conflicts(
            str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
        ) == [META]
        assert (repo.root / ANCHOR).read_text(encoding="utf-8") == main_source
        assert (repo.root / "docs/guide.zh.md").read_text(encoding="utf-8") == side_zh
        assert (repo.root / META).read_text(encoding="utf-8") == canonical

    def test_pre_merge_commit_hook_rejection_leaves_a_staged_merge(
        self, repo: Repo, tmp_path: Path
    ) -> None:
        self._setup_attributes(repo)
        build_divergent_pair(repo)
        env = _install_driver(repo, _runtime_uv_bin(tmp_path))
        hooks = repo.root / "hooks"
        hooks.mkdir()
        hook = hooks / "pre-merge-commit"
        hook.write_text(
            "#!/bin/sh\necho 'fixture pre-merge-commit rejection' >&2\nexit 77\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        git("config", "core.hooksPath", "hooks", cwd=repo.root)
        head_before = git("rev-parse", "HEAD", cwd=repo.root).stdout.strip()

        merge = _git_merge(repo, "main", env)

        assert merge.returncode == 1
        assert "fixture pre-merge-commit rejection" in merge.stderr
        assert git("rev-parse", "HEAD", cwd=repo.root).stdout.strip() == head_before
        assert git("rev-parse", "--verify", "MERGE_HEAD", cwd=repo.root).stdout.strip() != ""
        assert git("diff", "--name-only", "--diff-filter=U", cwd=repo.root).stdout.strip() == ""
        staged = git("diff", "--cached", "--name-only", cwd=repo.root).stdout.split("\n")
        assert META in staged
        _expect_merged_pair(repo)

    def test_mixed_merge_resolves_safe_pairs_and_aggregates_owner_conflicts(
        self, repo: Repo, tmp_path: Path
    ) -> None:
        def commit_mixed(guide: tuple[str, str], manual: tuple[str, str], message: str) -> None:
            repo.write(ANCHOR, guide[0])
            repo.write("docs/guide.zh.md", guide[1])
            repo.write(MANUAL_ANCHOR, manual[0])
            repo.write("docs/manual.zh.md", manual[1])
            gate_write(repo)
            gate_write(repo, MANUAL_ANCHOR)
            repo.commit(message)

        self._setup_attributes(repo)
        commit_mixed(
            (en_pair("guide.zh.md"), zh_pair("guide.md")),
            (en_pair("manual.zh.md"), zh_pair("manual.md")),
            "base",
        )
        git("branch", "side", cwd=repo.root)
        commit_mixed(
            (
                en_pair("guide.zh.md").replace("Body paragraph.", "Main rewrote the paragraph."),
                zh_pair("guide.md").replace("正文段落。", "主分支改写了这一段。"),
            ),
            (
                en_pair("manual.zh.md").replace("Body paragraph.", "Main rewrote it."),
                zh_pair("manual.md").replace("正文段落。", "主分支改写。"),
            ),
            "main edits both",
        )
        git("checkout", "side", cwd=repo.root)
        commit_mixed(
            (
                en_pair("guide.zh.md") + "\nSide appends a paragraph.\n",
                zh_pair("guide.md") + "\n侧分支新增一段。\n",
            ),
            (
                en_pair("manual.zh.md").replace("Body paragraph.", "SIDE rewrote it."),
                zh_pair("manual.md").replace("正文段落。", "侧分支改写。"),
            ),
            "side edits both",
        )
        git("checkout", "main", cwd=repo.root)
        env = _install_driver(repo, _fake_uv_bin(tmp_path, "#!/bin/sh\nexit 72\n"))

        merge = _git_merge(repo, "side", env)

        assert merge.returncode == 1
        with pytest.raises(
            ValueError, match=r"docs/manual\.i18n\.yaml: docs/manual\.md has content conflicts"
        ):
            resolve_conflicts(
                str(repo.root), pairing_source(str(repo.root)), generated=(), public_blob_root=""
            )
        assert _unmerged_paths(repo) == {MANUAL_META, "docs/manual.md", "docs/manual.zh.md"}
        _expect_merged_pair(repo)
