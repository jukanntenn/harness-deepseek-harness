"""The frozen RFC archive gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import hdsh.rfc.archive as archive_module
from hdsh.rfc.archive import (
    ArchiveManifest,
    blob_hash,
    manifest_extension_errors,
    parse_manifest,
    read_baseline_manifest,
    render_manifest,
    seal_state,
    validate_artifacts,
)
from hdsh.rfc.archive import (
    archive_content_hash as content_hash,
)
from hdsh.rfc.archive import main as archive_main
from hdsh.rfc.archive import run as run_archive
from tests.helpers import Repo, parse_command, sealed_sides, sidecar_for, write_sealed_triplet

ARCHIVE = ".agents/rfcs/archived"
MANIFEST = f"{ARCHIVE}/manifest.json"
VALID_SOURCE, VALID_ZH = sealed_sides()

ARTIFACTS = (
    "process/2026-01-01-sample.md",
    "process/2026-01-01-sample.zh.md",
    "process/2026-01-01-sample.i18n.yaml",
)


def archive_cli(argv: list[str]) -> int:
    """Run one archive leaf with parsed arguments."""
    return archive_main(parse_command(archive_module.register, argv))


def seed_commit(repo: Repo) -> None:
    """Give the disposable repository its initial commit."""
    repo.write(".anchor", "x\n")
    repo.commit()


def seal_green(repo: Repo) -> None:
    """Prepare one fully sealed, green archive."""
    repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
    write_sealed_triplet(repo)
    assert run_archive(repo.root, seal=True) == 0


class TestSealGreen:
    def test_unborn_branch_seals_from_empty_baseline(self, repo: Repo) -> None:
        seal_green(repo)
        assert run_archive(repo.root, seal=False) == 0

    def test_seal_appends_and_verify_checks(self, repo: Repo) -> None:
        seal_green(repo)
        manifest = parse_manifest((repo.root / MANIFEST).read_text(encoding="utf-8"))
        assert set(manifest.files) == set(ARTIFACTS)
        assert manifest.files[ARTIFACTS[0]] == content_hash(VALID_SOURCE.encode("utf-8"))
        assert run_archive(repo.root, seal=False) == 0

    def test_seal_is_idempotent(self, repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
        seal_green(repo)
        before = (repo.root / MANIFEST).read_text(encoding="utf-8")
        assert run_archive(repo.root, seal=True) == 0
        assert (repo.root / MANIFEST).read_text(encoding="utf-8") == before
        assert "sealed 0 new artifact(s)" in capsys.readouterr().out

    def test_missing_archive_directory_is_green(self, tmp_path: Path) -> None:
        assert run_archive(tmp_path, seal=False) == 0

    def test_baseline_before_manifest_extends_freely(self, repo: Repo) -> None:
        seed_commit(repo)
        seal_green(repo)
        assert run_archive(repo.root, seal=False) == 0


class TestStructure:
    def test_missing_agents_instructions(self, repo: Repo) -> None:
        (repo.root / ARCHIVE).mkdir(parents=True)
        assert run_archive(repo.root, seal=False) == 1

    def test_unexpected_root_file(self, repo: Repo) -> None:
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        repo.write(f"{ARCHIVE}/README.md", "# no\n")
        assert run_archive(repo.root, seal=False) == 1

    def test_unknown_class_directory(self, repo: Repo) -> None:
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        repo.write(f"{ARCHIVE}/other/2026-01-01-sample.md", VALID_SOURCE)
        assert run_archive(repo.root, seal=False) == 1

    def test_class_directories_hold_regular_files_only(self, repo: Repo) -> None:
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        (repo.root / f"{ARCHIVE}/process" / "nested").mkdir(parents=True)
        assert run_archive(repo.root, seal=False) == 1

    def test_root_entries_must_be_files_or_class_directories(self, repo: Repo) -> None:
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        (repo.root / f"{ARCHIVE}/dangling").symlink_to(repo.root / "nowhere")
        assert run_archive(repo.root, seal=False) == 1

    def test_manifest_is_required_for_verification(self, repo: Repo) -> None:
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        write_sealed_triplet(repo)
        assert run_archive(repo.root, seal=False) == 1

    def test_symlinked_artifact_is_not_a_regular_file(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        write_sealed_triplet(repo)
        target = repo.write("outside.md", "content\n")
        (repo.root / f"{ARCHIVE}/process" / "2026-01-02-y.md").symlink_to(target)
        assert run_archive(repo.root, seal=True) == 1
        assert "regular files only" in capsys.readouterr().out

    def test_root_symlink_is_not_a_regular_file(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        target = repo.write("outside.md", "content\n")
        (repo.root / ARCHIVE / "README.md").symlink_to(target)
        assert run_archive(repo.root, seal=True) == 1
        assert "only regular files and class directories" in capsys.readouterr().out


class TestTriplets:
    def test_bad_artifact_name(self) -> None:
        assert validate_artifacts({"process/notadate.md": b"x"}) == [
            "process/notadate.md: expected {class}/yyyy-mm-dd-topic.{md,zh.md,i18n.yaml}"
        ]

    def test_unknown_class_in_artifact_map(self) -> None:
        assert validate_artifacts({"other/2026-01-01-x.md": b"x"}) == [
            "other/2026-01-01-x.md: unknown RFC class 'other'"
        ]

    def test_incomplete_triplet(self, repo: Repo) -> None:
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        repo.write(f"{ARCHIVE}/process/2026-01-01-sample.md", VALID_SOURCE)
        assert run_archive(repo.root, seal=False) == 1

    def test_header_violations(self) -> None:
        def artifacts(source: str, zh: str) -> dict[str, bytes]:
            return {
                "process/2026-01-01-sample.md": source.encode("utf-8"),
                "process/2026-01-01-sample.zh.md": zh.encode("utf-8"),
                "process/2026-01-01-sample.i18n.yaml": sidecar_for(source, zh).encode("utf-8"),
            }

        cases = {
            "title": artifacts(VALID_SOURCE.replace("# RFC: Sample decision", "# RFC:"), VALID_ZH),
            "blank-line-2": artifacts(
                VALID_SOURCE.replace("\n\nStatus:", "\nX\nStatus:"), VALID_ZH
            ),
            "status": artifacts(
                VALID_SOURCE.replace("Status: implemented", "Status: proposed"), VALID_ZH
            ),
            "date-format": artifacts(VALID_SOURCE.replace("2026-02-01", "2026-2-01"), VALID_ZH),
            "date-calendar": artifacts(VALID_SOURCE.replace("2026-02-01", "2026-02-30"), VALID_ZH),
            "date-predates": artifacts(VALID_SOURCE.replace("2026-02-01", "2025-12-31"), VALID_ZH),
            "blank-line-5": artifacts(
                VALID_SOURCE.replace("\nArchived: 2026-02-01\n\n", "\nArchived: 2026-02-01\nX\n"),
                VALID_ZH,
            ),
            "switcher": artifacts(
                VALID_SOURCE.replace("English | [中文]", "中文 | [English]"), VALID_ZH
            ),
            "zh-switcher": artifacts(VALID_SOURCE, VALID_ZH.replace("[English]", "[英文]")),
            "short-file": artifacts("# RFC: Tiny\n", VALID_ZH),
        }
        for name, files in cases.items():
            assert validate_artifacts(files), name

    def test_archive_dates_must_match(self) -> None:
        zh = VALID_ZH.replace("Archived: 2026-02-01", "Archived: 2026-02-02")
        errors = validate_artifacts(
            {
                "process/2026-01-01-sample.md": VALID_SOURCE.encode("utf-8"),
                "process/2026-01-01-sample.zh.md": zh.encode("utf-8"),
                "process/2026-01-01-sample.i18n.yaml": sidecar_for(VALID_SOURCE, zh).encode(
                    "utf-8"
                ),
            }
        )
        assert any("archive dates differ" in error for error in errors)

    def test_sidecar_violations(self) -> None:
        files = {
            "process/2026-01-01-sample.md": VALID_SOURCE.encode("utf-8"),
            "process/2026-01-01-sample.zh.md": VALID_ZH.encode("utf-8"),
        }
        assert validate_artifacts({**files, "process/2026-01-01-sample.i18n.yaml": b"garbage\n"})
        assert validate_artifacts(
            {**files, "process/2026-01-01-sample.i18n.yaml": b"sample.md: " + b"0" * 40 + b"\n"}
        )
        assert validate_artifacts(
            {**files, "process/2026-01-01-sample.i18n.yaml": sidecar_for("x", "y").encode("utf-8")}
        )


class TestManifestSchema:
    def test_render_is_deterministic(self) -> None:
        manifest = ArchiveManifest(
            version=1, files={"b.md": "sha256:" + "0" * 64, "a.md": "sha256:" + "1" * 64}
        )
        assert render_manifest(manifest) == (
            "{\n"
            '  "version": 1,\n'
            '  "files": {\n'
            f'    "a.md": "sha256:{"1" * 64}",\n'
            f'    "b.md": "sha256:{"0" * 64}"\n'
            "  }\n"
            "}\n"
        )

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            ("not json", "invalid JSON"),
            ("[]", "expected a JSON object"),
            ('{"version": 1}', "expected exactly the fields"),
            ('{"version": 1, "files": {}, "extra": 0}', "expected exactly the fields"),
            ('{"version": 2, "files": {}}', "unsupported manifest version"),
            ('{"version": true, "files": {}}', "unsupported manifest version"),
            ('{"version": 1, "files": []}', "`files` must be an object"),
            ('{"version": 1, "files": {"a.md": "md5:00"}}', "invalid content hash"),
            ('{"version": 1, "files": {"a.md": 5}}', "invalid content hash"),
        ],
    )
    def test_schema_rejections(self, content: str, message: str) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            parse_manifest(content)

    def test_blob_hash_matches_git(self, repo: Repo) -> None:
        expected = (
            subprocess.run(
                ["git", "-C", str(repo.root), "hash-object", "--stdin"],
                input=b"content",
                capture_output=True,
                check=True,
            )
            .stdout.decode("utf-8")
            .strip()
        )
        assert blob_hash(b"content") == expected

    def test_extension_errors_name_missing_and_changed(self) -> None:
        baseline = ArchiveManifest(
            version=1,
            files={"gone.md": "sha256:" + "0" * 64, "changed.md": "sha256:" + "1" * 64},
        )
        current = ArchiveManifest(version=1, files={"changed.md": "sha256:" + "2" * 64})
        assert manifest_extension_errors(baseline, current) == [
            "gone.md: sealed manifest entry is missing",
            "changed.md: sealed manifest hash changed",
        ]


class TestBaseline:
    def test_sealed_content_may_not_change(self, repo: Repo) -> None:
        seed_commit(repo)
        seal_green(repo)
        repo.commit()
        repo.write(f"{ARCHIVE}/process/2026-01-01-sample.md", VALID_SOURCE + "\nextra\n")
        assert run_archive(repo.root, seal=False) == 1
        assert run_archive(repo.root, seal=True) == 1

    def test_sealed_artifact_may_not_disappear(self, repo: Repo) -> None:
        seed_commit(repo)
        seal_green(repo)
        repo.commit()
        (repo.root / f"{ARCHIVE}/process/2026-01-01-sample.zh.md").unlink()
        assert run_archive(repo.root, seal=False) == 1

    def test_manifest_entry_may_not_change_against_baseline(self, repo: Repo) -> None:
        seed_commit(repo)
        seal_green(repo)
        repo.commit()
        manifest = parse_manifest((repo.root / MANIFEST).read_text(encoding="utf-8"))
        manifest.files[ARTIFACTS[0]] = "sha256:" + "0" * 64
        (repo.root / MANIFEST).write_text(render_manifest(manifest), encoding="utf-8")
        assert run_archive(repo.root, seal=False) == 1

    def test_manifest_entry_may_not_disappear_against_baseline(self, repo: Repo) -> None:
        seed_commit(repo)
        seal_green(repo)
        repo.commit()
        manifest = parse_manifest((repo.root / MANIFEST).read_text(encoding="utf-8"))
        del manifest.files[ARTIFACTS[0]]
        (repo.root / MANIFEST).write_text(render_manifest(manifest), encoding="utf-8")
        assert run_archive(repo.root, seal=False) == 1

    def test_unreadable_worktree_manifest_fails_loud(
        self, repo: Repo, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seed_commit(repo)
        seal_green(repo)
        repo.commit()
        repo.write(MANIFEST, "not json\n")
        assert run_archive(repo.root, seal=False) == 1
        assert "invalid JSON" in capsys.readouterr().out

    def test_unreadable_baseline_ref_fails_loud(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed_commit(repo)
        seal_green(repo)
        monkeypatch.setenv("HDSH_ARCHIVE_BASE_REF", "no-such-ref")
        assert run_archive(repo.root, seal=False) == 1

    def test_baseline_manifest_schema_is_validated(self, repo: Repo) -> None:
        repo.write(".anchor", "x\n")
        repo.write(f"{ARCHIVE}/AGENTS.md", "# frozen\n")
        repo.write(MANIFEST, "[]\n")
        repo.commit()
        with pytest.raises(TypeError, match="expected a JSON object"):
            read_baseline_manifest(repo.root, "HEAD", MANIFEST)


class TestSealState:
    def test_extension_errors_and_added_paths(self) -> None:
        sealed = {"process/gone.md": "sha256:" + "0" * 64, "process/kept.md": content_hash(b"kept")}
        manifest = ArchiveManifest(version=1, files=sealed)
        extended, added, errors = seal_state(
            manifest, {"process/kept.md": b"kept", "process/new.md": b"new"}
        )
        assert errors == ["process/gone.md: sealed artifact is missing"]
        assert added == ["process/new.md"]
        assert extended.files["process/kept.md"] == content_hash(b"kept")
        assert extended.files["process/new.md"] == content_hash(b"new")

    def test_hash_change_is_reported(self) -> None:
        manifest = ArchiveManifest(version=1, files={"process/kept.md": "sha256:" + "9" * 64})
        _, _, errors = seal_state(manifest, {"process/kept.md": b"kept"})
        assert errors == ["process/kept.md: sealed content hash changed"]


class TestCli:
    def test_archive_cli_green(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo.root)
        seal_green(repo)
        assert archive_cli(["archive"]) == 0

    def test_main_exits_two_outside_repository(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 128, "", "not a repository")

        monkeypatch.setattr(subprocess, "run", failing_run)
        assert archive_cli(["archive"]) == 2

    def test_main_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: object, **kwargs: object) -> None:
            raise OSError("boom")

        monkeypatch.setattr("hdsh.rfc.archive.subprocess.run", raising_run)
        assert archive_cli(["archive"]) == 2

    @pytest.mark.parametrize("leaf", ["archive", "seal"])
    def test_extra_arguments_are_rejected(self, leaf: str) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse_command(archive_module.register, [leaf, "--nope"])
