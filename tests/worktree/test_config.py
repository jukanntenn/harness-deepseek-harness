"""The installer's config guards: helpers, migration, merge-driver registration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from hdsh.worktree import config as worktree_config
from hdsh.worktree import install as worktree_install
from hdsh.worktree.git import WorktreeError, nul_values, run_git, strip_git_line_terminator
from hdsh.worktree.install import install
from tests.helpers import Repo, git


def git_dir(repo: Repo) -> Path:
    return Path(git("rev-parse", "--absolute-git-dir", cwd=repo.root).stdout.strip())


def common_config(repo: Repo) -> Path:
    return git_dir(repo) / "config"


@pytest.fixture(autouse=True)
def no_prek(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the probe and prek invocation; config guards are under test."""
    monkeypatch.setattr(worktree_install, "run_prek", lambda root: None)
    monkeypatch.setattr(worktree_install, "probe_pairing_merge_driver", lambda root: None)


class TestGitHelpers:
    def test_git_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: Any, **kwargs: Any) -> None:
            raise OSError("gone")

        monkeypatch.setattr(subprocess, "run", raising_run)
        with pytest.raises(WorktreeError, match="failed: gone"):
            run_git(".", ["--version"])

    def test_git_failure_without_stderr_names_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["git"], 3, "", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="exit status 3"):
            run_git(".", ["--version"])

    def test_strip_git_line_terminator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import hdsh.worktree.git as git_module

        monkeypatch.setattr(git_module, "_WINDOWS", True)
        assert strip_git_line_terminator("root\r\n") == "root"
        monkeypatch.setattr(git_module, "_WINDOWS", False)
        assert strip_git_line_terminator("root\r\n") == "root\r"
        assert strip_git_line_terminator("root\n") == "root"
        assert strip_git_line_terminator("root") == "root"

    def test_nul_values_keeps_empty_fields(self) -> None:
        completed = subprocess.CompletedProcess(["git"], 0, "a\0\0b\0", "")
        assert nul_values(completed) == ["a", "", "b"]

    def test_nul_values_frames_empty_values(self) -> None:
        assert nul_values(subprocess.CompletedProcess(["git"], 0, "", "")) == [""]
        assert nul_values(subprocess.CompletedProcess(["git"], 0, "\0", "")) == [""]

    def test_nul_values_ignores_failed_output(self) -> None:
        assert nul_values(subprocess.CompletedProcess(["git"], 1, "a\0", "")) == []

    def test_included_entries_odd_fields_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["git"], 0, "one\0", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="invalid file entries"):
            worktree_config.included_config_entries(".", "/cfg", "k")

    def test_effective_entry_invalid_shape_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["git"], 0, "a\0b\0", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="invalid scoped value"):
            worktree_config.effective_config_entry(".", "k")

    def test_matching_entries_odd_fields_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["git"], 0, "one\0", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="invalid matching file entries"):
            worktree_config.direct_config_matching_entries(".", "/cfg", "^k")

    def test_matching_entries_without_separator_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = subprocess.CompletedProcess(["git"], 0, "file:x\0novalue\0", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="invalid name and value"):
            worktree_config.direct_config_matching_entries(".", "/cfg", "^k")

    def test_matching_entries_reads_names_and_values(self, repo: Repo) -> None:
        sample = repo.root / "sample.gitconfig"
        git("config", "--file", str(sample), "extensions.sample", "true", cwd=repo.root)
        entries = worktree_config.direct_config_matching_entries(
            str(repo.root), str(sample), "^extensions\\."
        )
        assert entries == [
            {
                "origin": f"file:{sample}",
                "name": "extensions.sample",
                "value": "true",
            }
        ]

    def test_parse_git_boolean_rejects_garbage(self) -> None:
        with pytest.raises(WorktreeError, match="invalid Boolean value"):
            worktree_config.parse_git_boolean("perhaps", "k")

    def test_parse_git_boolean_off_forms(self) -> None:
        assert worktree_config.parse_git_boolean("OFF", "k") is False
        assert worktree_config.parse_git_boolean("0", "k") is False
        assert worktree_config.parse_git_boolean("on", "k") is True
        assert worktree_config.parse_git_boolean("", "k") is True

    def test_assert_single_rejects_multiple(self) -> None:
        with pytest.raises(WorktreeError, match="multiple k values"):
            worktree_config.assert_single(["a", "b"], "k")


class TestFileGuards:
    def test_has_direct_config_entries(self, repo: Repo) -> None:
        config = common_config(repo)
        assert worktree_config.has_direct_config_entries(str(repo.root), str(config)) is True
        empty = repo.root / "empty.gitconfig"
        empty.touch()
        assert worktree_config.has_direct_config_entries(str(repo.root), str(empty)) is False

    def test_registered_worktree_config_paths_without_linked_worktrees(self, repo: Repo) -> None:
        paths = worktree_config.registered_worktree_config_paths(str(git_dir(repo)))
        assert paths == [str(git_dir(repo) / "config.worktree")]

    def test_registered_worktree_config_paths_lists_linked_worktrees(self, repo: Repo) -> None:
        linked = repo.root / "linked"
        git("worktree", "add", "-b", "linked", str(linked), cwd=repo.root)
        (git_dir(repo) / "worktrees" / "zzz").mkdir(parents=True)
        paths = worktree_config.registered_worktree_config_paths(str(git_dir(repo)))
        assert paths == [
            str(git_dir(repo) / "config.worktree"),
            str(git_dir(repo) / "worktrees" / "linked" / "config.worktree"),
            str(git_dir(repo) / "worktrees" / "zzz" / "config.worktree"),
        ]

    def test_assert_common_config_file_variants(self, repo: Repo, tmp_path: Path) -> None:
        config = common_config(repo)
        worktree_config.assert_common_config_file(str(config))
        missing = tmp_path / "missing.gitconfig"
        with pytest.raises(WorktreeError, match="not a regular file"):
            worktree_config.assert_common_config_file(str(missing))
        link = tmp_path / "linked.gitconfig"
        link.symlink_to(config)
        with pytest.raises(WorktreeError, match="not a regular file"):
            worktree_config.assert_common_config_file(str(link))

    def test_refuses_active_symlinked_worktree_config(self, repo: Repo, tmp_path: Path) -> None:
        common = common_config(repo)
        git("config", "--file", str(common), "core.repositoryFormatVersion", "1", cwd=repo.root)
        git("config", "--file", str(common), "extensions.worktreeConfig", "true", cwd=repo.root)
        external = tmp_path / "external.gitconfig"
        external.write_text("[user]\n\tname = External owner\n", encoding="utf-8")
        worktree_config_path = git_dir(repo) / "config.worktree"
        worktree_config_path.symlink_to(external)
        with pytest.raises(WorktreeError, match=r"active worktree config .* not a regular file"):
            worktree_config.assert_worktree_config_files(
                str(repo.root), str(git_dir(repo)), str(common), str(worktree_config_path)
            )

    def test_refuses_dormant_symlinked_worktree_config(self, repo: Repo, tmp_path: Path) -> None:
        common = common_config(repo)
        external = tmp_path / "external.gitconfig"
        external.write_text("[user]\n\tname = External owner\n", encoding="utf-8")
        worktree_config_path = git_dir(repo) / "config.worktree"
        worktree_config_path.symlink_to(external)
        with pytest.raises(WorktreeError, match=r"dormant worktree config .* not a regular file"):
            worktree_config.assert_worktree_config_files(
                str(repo.root), str(git_dir(repo)), str(common), str(worktree_config_path)
            )

    def test_refuses_sibling_dormant_config_with_settings(self, repo: Repo) -> None:
        linked_private = git_dir(repo) / "worktrees" / "linked"
        linked_private.mkdir(parents=True)
        sibling_config = linked_private / "config.worktree"
        sibling_config.write_text("[core]\n\thooksPath = /custom\n", encoding="utf-8")
        with pytest.raises(WorktreeError, match="sibling dormant worktree config"):
            worktree_config.assert_worktree_config_files(
                str(repo.root),
                str(git_dir(repo)),
                str(common_config(repo)),
                str(common_config(repo)),
            )

    def test_refuses_current_dormant_config_with_settings(self, repo: Repo) -> None:
        worktree_config_path = git_dir(repo) / "config.worktree"
        worktree_config_path.write_text("[core]\n\thooksPath = /custom\n", encoding="utf-8")
        with pytest.raises(WorktreeError, match="current dormant worktree config"):
            worktree_config.assert_worktree_config_files(
                str(repo.root),
                str(git_dir(repo)),
                str(common_config(repo)),
                str(worktree_config_path),
            )

    def test_ignores_an_empty_sibling_worktree_config(self, repo: Repo) -> None:
        linked_private = git_dir(repo) / "worktrees" / "linked"
        linked_private.mkdir(parents=True)
        (linked_private / "config.worktree").touch()
        worktree_config.assert_worktree_config_files(
            str(repo.root), str(git_dir(repo)), str(common_config(repo)), str(common_config(repo))
        )


class TestEnvironmentScrub:
    def test_command_git_config_is_scrubbed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'x=y'")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "k")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "v")
        env = worktree_config.environment_without_command_git_config()
        assert "GIT_CONFIG_PARAMETERS" not in env
        assert "GIT_CONFIG_COUNT" not in env
        assert "GIT_CONFIG_KEY_0" not in env
        assert "GIT_CONFIG_VALUE_0" not in env

    def test_run_prek_failure_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["prek"], 1, "", "boom\n")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="prek install --overwrite failed: boom"):
            worktree_config.run_prek("/repo")

    def test_run_prek_failure_without_stderr_names_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = subprocess.CompletedProcess(["prek"], 7, "", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="failed: exit status 7"):
            worktree_config.run_prek("/repo")

    def test_run_prek_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: Any, **kwargs: Any) -> None:
            raise OSError("no prek")

        monkeypatch.setattr(subprocess, "run", raising_run)
        with pytest.raises(WorktreeError, match="no prek"):
            worktree_config.run_prek("/repo")

    def test_probe_failure_raises_with_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["uv"], 1, "", "no runtime\n")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="--probe failed: no runtime"):
            worktree_config.probe_pairing_merge_driver("/repo")

    def test_probe_failure_without_stderr_names_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = subprocess.CompletedProcess(["uv"], 3, "", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        with pytest.raises(WorktreeError, match="--probe failed: exit status 3"):
            worktree_config.probe_pairing_merge_driver("/repo")

    def test_probe_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raising_run(*args: Any, **kwargs: Any) -> None:
            raise OSError("no uv")

        monkeypatch.setattr(subprocess, "run", raising_run)
        with pytest.raises(WorktreeError, match="probe failed: no uv"):
            worktree_config.probe_pairing_merge_driver("/repo")

    def test_probe_success_returns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["uv"], 0, "", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        worktree_config.probe_pairing_merge_driver("/repo")


class TestWorktreeConfigMigration:
    def test_rejects_unsupported_repository_format(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            worktree_config,
            "direct_config_values",
            lambda root, config_path, key: ["abc"] if key == "core.repositoryFormatVersion" else [],
        )
        with pytest.raises(WorktreeError, match="repositoryFormatVersion"):
            install(str(repo.root))

    def test_rejects_missing_repository_format(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            worktree_config, "direct_config_values", lambda root, config_path, key: []
        )
        with pytest.raises(WorktreeError, match="repositoryFormatVersion: None"):
            install(str(repo.root))

    def test_rejects_negative_repository_format(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            worktree_config,
            "direct_config_values",
            lambda root, config_path, key: ["-1"] if key == "core.repositoryFormatVersion" else [],
        )
        with pytest.raises(WorktreeError, match="repositoryFormatVersion: '-1'"):
            install(str(repo.root))

    def test_rejects_fractional_repository_format(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            worktree_config,
            "direct_config_values",
            lambda root, config_path, key: ["1.0"] if key == "core.repositoryFormatVersion" else [],
        )
        with pytest.raises(WorktreeError, match="repositoryFormatVersion: '1.0'"):
            install(str(repo.root))

    def test_empty_repository_format_string_parses_as_zero(self) -> None:
        # Git itself refuses to hand out an empty repositoryFormatVersion, so
        # this mirrors the grammar the parser implements rather than a live read.
        assert worktree_config._parse_format_version("") == 0
        assert worktree_config._parse_format_version(" 1 ") == 1

    def test_rejects_dormant_extension(self, repo: Repo) -> None:
        git("config", "core.repositoryFormatVersion", "0", cwd=repo.root)
        git("config", "extensions.dummyExtension", "true", cwd=repo.root)
        with pytest.raises(
            WorktreeError,
            match=r"dormant repository extension extensions\.dummyextension"
            r" is configured \(file:.*'true'\)",
        ):
            install(str(repo.root))

    def test_format_zero_migrates_to_one(self, repo: Repo) -> None:
        git("config", "core.repositoryFormatVersion", "0", cwd=repo.root)
        install(str(repo.root))
        assert git("config", "core.repositoryFormatVersion", cwd=repo.root).stdout.strip() == "1"

    def test_direct_bare_false_is_unset(self, repo: Repo) -> None:
        config = common_config(repo)
        text = config.read_text(encoding="utf-8")
        if "bare" not in text:
            text = text.replace("[core]", "[core]\n\tbare = false")
        config.write_text(text, encoding="utf-8")
        install(str(repo.root))
        assert git("config", "core.bare", cwd=repo.root, check=False).returncode == 1

    def test_refuses_direct_core_worktree_with_origin(self, repo: Repo) -> None:
        config = common_config(repo)
        text = config.read_text(encoding="utf-8")
        config.write_text(
            text.replace("[core]", "[core]\n\tworktree = /elsewhere"), encoding="utf-8"
        )
        with pytest.raises(WorktreeError, match=r"core.worktree is in the common config \(file:"):
            install(str(repo.root))

    def test_refuses_direct_bare_true_with_origin(self, repo: Repo) -> None:
        git("config", "core.bare", "true", cwd=repo.root)
        with pytest.raises(WorktreeError, match=r"core\.bare=true \(file:.*'true'\)"):
            install(str(repo.root))


class TestMergeDriverGuards:
    def test_refuses_included_file_entry(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        original = worktree_config.included_config_entries

        def fake_entries(root: str, config_path: str, key: str) -> list[dict[str, str]]:
            if key.startswith("merge."):
                return [{"origin": "file:/elsewhere/include", "value": "x"}]
            return original(root, config_path, key)

        monkeypatch.setattr(worktree_config, "included_config_entries", fake_entries)
        with pytest.raises(WorktreeError, match="included worktree file"):
            install(str(repo.root))

    def test_refuses_command_scoped_value(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_effective(root: str, key: str) -> dict[str, str] | None:
            if key.endswith((".driver", ".name")):
                return {"scope": "command", "origin": "cmd", "value": "x"}
            return None

        monkeypatch.setattr(worktree_config, "effective_config_entry", fake_effective)
        with pytest.raises(WorktreeError, match="command-scoped"):
            install(str(repo.root))

    def test_refuses_replacing_worktree_driver_value(self, repo: Repo) -> None:
        install(str(repo.root))
        git("config", "--worktree", "--unset-all", "core.hooksPath", cwd=repo.root)
        git(
            "config",
            "--worktree",
            "merge.hdsh-pairing.driver",
            "other-driver %O %A %B",
            cwd=repo.root,
        )
        with pytest.raises(WorktreeError, match="refusing to replace worktree"):
            install(str(repo.root))

    def test_verifies_installed_values(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        def fake_entries(root: str, config_path: str, key: str) -> list[dict[str, str]]:
            calls["n"] += 1
            if calls["n"] > 2:
                return [{"origin": f"file:{config_path}", "value": "unexpected"}]
            return []

        monkeypatch.setattr(worktree_config, "included_config_entries", fake_entries)
        with pytest.raises(WorktreeError, match="did not become the direct worktree value"):
            install(str(repo.root))

    def test_verifies_effective_installed_value(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = worktree_config.effective_config_entry
        state = {"seen": 0}

        def fake_effective(root: str, key: str) -> dict[str, str] | None:
            result = original(root, key)
            state["seen"] += 1
            if key.startswith("merge.") and state["seen"] > 2:
                return None
            return result

        monkeypatch.setattr(worktree_config, "effective_config_entry", fake_effective)
        with pytest.raises(
            WorktreeError, match="did not become the effective direct worktree value"
        ):
            install(str(repo.root))

    def test_driver_install_rollback_failure_is_aggregated(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original_entries = worktree_config.included_config_entries
        calls = {"n": 0}

        def fake_entries(root: str, config_path: str, key: str) -> list[dict[str, str]]:
            calls["n"] += 1
            if calls["n"] > 2:
                return [{"origin": f"file:{config_path}", "value": "unexpected"}]
            return original_entries(root, config_path, key)

        real_unset = worktree_config._unset_worktree_config

        def failing_unset(root: str, key: str) -> None:
            if key == "merge.hdsh-pairing.name":
                raise WorktreeError("unset exploded")
            real_unset(root, key)

        monkeypatch.setattr(worktree_config, "included_config_entries", fake_entries)
        monkeypatch.setattr(worktree_config, "_unset_worktree_config", failing_unset)
        with pytest.raises(
            WorktreeError,
            match=r"Pairing merge-driver configuration failed.*"
            r"rollback also failed.*unset exploded",
        ):
            install(str(repo.root))


class TestConfigEdges:
    def test_origin_is_file_rejects_non_file_origins(self) -> None:
        assert (
            worktree_config.origin_is_file("command:x", "/repo", "/repo/.git/config.worktree")
            is False
        )
        assert worktree_config.origin_is_file(
            "file:/repo/.git/config.worktree", "/repo", "/repo/.git/config.worktree"
        )

    def test_origin_is_file_resolves_relative_origins(self, tmp_path: Path) -> None:
        assert worktree_config.origin_is_file(
            "file:.git/config.worktree", str(tmp_path), str(tmp_path / ".git" / "config.worktree")
        )

    def test_normalized_path_is_lexical(self) -> None:
        assert worktree_config.normalized_path("/a/b/../c") == str(Path("/a/c").resolve())

    def test_run_prek_success_returns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(["prek"], 0, "", "")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        worktree_config.run_prek("/repo")
