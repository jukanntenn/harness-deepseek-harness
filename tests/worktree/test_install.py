"""Worktree-local prek hook installation safety."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import pytest

from hdsh.worktree import install as worktree_install
from hdsh.worktree.git import WorktreeError
from hdsh.worktree.install import install
from tests.helpers import Repo, git, parse_command


@pytest.fixture(autouse=True)
def no_prek(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the probe and prek invocation; the installer's contract is under test."""
    monkeypatch.setattr(worktree_install, "run_prek", lambda root: None)
    monkeypatch.setattr(worktree_install, "probe_pairing_merge_driver", lambda root: None)


def hooks_path_of(repo: Repo) -> str:
    git_dir = git("rev-parse", "--absolute-git-dir", cwd=repo.root).stdout.strip()
    return f"{git_dir}/hdsh-hooks"


class TestFreshInstall:
    def test_installs_worktree_local_hooks(self, repo: Repo) -> None:
        install(str(repo.root))
        hooks = hooks_path_of(repo)
        assert (repo.root / ".git" / "hdsh-hooks" / ".hdsh-hooks-owned").is_file()
        marker = json.loads(
            (repo.root / ".git" / "hdsh-hooks" / ".hdsh-hooks-owned").read_text(encoding="utf-8")
        )
        assert marker["hooksPath"] == hooks
        assert git("config", "--worktree", "core.hooksPath", cwd=repo.root).stdout.strip() == hooks
        assert (
            git("config", "--worktree", "merge.hdsh-pairing.driver", cwd=repo.root)
            .stdout.strip()
            .startswith("scripts/pairing-merge-driver.sh")
        )
        assert git("config", "extensions.worktreeConfig", cwd=repo.root).stdout.strip() == "true"

    def test_reinstall_is_idempotent(self, repo: Repo) -> None:
        install(str(repo.root))
        install(str(repo.root))


class TestRefusals:
    def test_refuses_inherited_hooks_path(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HDSH_PREK_ALLOW_HOOKS_PATH_OVERRIDE", raising=False)
        git("config", "core.hooksPath", "/user/owned/hooks", cwd=repo.root)
        with pytest.raises(
            WorktreeError,
            match=r"user-owned core\.hooksPath.*may remain active only in other worktrees",
        ):
            install(str(repo.root))
        assert (
            git("config", "extensions.worktreeConfig", cwd=repo.root, check=False).returncode == 1
        )
        assert git("config", "core.hooksPath", cwd=repo.root).stdout.strip() == "/user/owned/hooks"

    def test_override_env_permits_replacement(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        git("config", "core.hooksPath", "/user/owned/hooks", cwd=repo.root)
        monkeypatch.setenv("HDSH_PREK_ALLOW_HOOKS_PATH_OVERRIDE", "1")
        install(str(repo.root))
        assert git("config", "--worktree", "core.hooksPath", cwd=repo.root).stdout.strip() == (
            hooks_path_of(repo)
        )

    def test_refuses_foreign_merge_driver_value(self, repo: Repo) -> None:
        install(str(repo.root))
        git("config", "--worktree", "--unset-all", "merge.hdsh-pairing.driver", cwd=repo.root)
        git(
            "config",
            "merge.hdsh-pairing.driver",
            "custom-driver %O %A %B %P",
            cwd=repo.root,
        )
        git("config", "--worktree", "--unset-all", "core.hooksPath", cwd=repo.root)
        with pytest.raises(WorktreeError, match="refusing to mask inherited"):
            install(str(repo.root))

    def test_refuses_unowned_hooks_directory(self, repo: Repo) -> None:
        hooks = repo.root / ".git" / "hdsh-hooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
        with pytest.raises(WorktreeError, match="unowned hooks directory"):
            install(str(repo.root))
        assert (hooks / "pre-commit").read_text(encoding="utf-8") == "#!/bin/sh\n"

    def test_refuses_worktree_scoped_foreign_hooks_path(self, repo: Repo) -> None:
        install(str(repo.root))
        git("config", "--worktree", "core.hooksPath", "/somewhere/else", cwd=repo.root)
        with pytest.raises(WorktreeError, match="worktree-scoped core.hooksPath"):
            install(str(repo.root))
        assert (
            git("config", "--worktree", "core.hooksPath", cwd=repo.root).stdout.strip()
            == "/somewhere/else"
        )

    def test_refuses_foreign_value_without_an_owned_hooks_directory(self, repo: Repo) -> None:
        install(str(repo.root))
        git("config", "--worktree", "core.hooksPath", "/somewhere/else", cwd=repo.root)
        shutil.rmtree(repo.root / ".git" / "hdsh-hooks")
        with pytest.raises(WorktreeError, match="worktree-scoped core.hooksPath"):
            install(str(repo.root))
        assert (
            git("config", "--worktree", "core.hooksPath", cwd=repo.root).stdout.strip()
            == "/somewhere/else"
        )

    def test_refuses_bare_common_config(self, repo: Repo) -> None:
        git("config", "core.bare", "true", cwd=repo.root)
        with pytest.raises(WorktreeError, match="core.bare=true"):
            install(str(repo.root))

    def test_refuses_core_worktree_in_common_config(self, repo: Repo) -> None:
        git_config = repo.root / ".git" / "config"
        text = git_config.read_text(encoding="utf-8")
        git_config.write_text(
            text.replace("[core]", "[core]\n\tworktree = /elsewhere"), encoding="utf-8"
        )
        with pytest.raises(WorktreeError, match="core.worktree"):
            install(str(repo.root))


class TestCommandScopedAndUnknownScopes:
    def test_command_scoped_effective_hooks_path_refused(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = worktree_install.effective_config_entry

        def command_scoped(root: str, key: str) -> dict[str, str] | None:
            if key == "core.hooksPath":
                return {"scope": "command", "origin": "cmd", "value": "x"}
            return original(root, key)

        monkeypatch.setattr(worktree_install, "effective_config_entry", command_scoped)
        monkeypatch.delenv("HDSH_PREK_ALLOW_HOOKS_PATH_OVERRIDE", raising=False)
        with pytest.raises(
            WorktreeError, match="command-scoped core.hooksPath.*cannot override transient"
        ):
            install(str(repo.root))

    def test_command_scope_refused_even_with_override(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = worktree_install.effective_config_entry

        def command_scoped(root: str, key: str) -> dict[str, str] | None:
            if key == "core.hooksPath":
                return {"scope": "command", "origin": "cmd", "value": "x"}
            return original(root, key)

        monkeypatch.setattr(worktree_install, "effective_config_entry", command_scoped)
        monkeypatch.setenv("HDSH_PREK_ALLOW_HOOKS_PATH_OVERRIDE", "1")
        with pytest.raises(WorktreeError, match="command-scoped core.hooksPath"):
            install(str(repo.root))

    def test_unknown_scope_is_refused(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        original = worktree_install.effective_config_entry

        def unknown_scope(root: str, key: str) -> dict[str, str] | None:
            if key == "core.hooksPath":
                return {"scope": "bogus", "origin": "file:/x", "value": "y"}
            return original(root, key)

        monkeypatch.setattr(worktree_install, "effective_config_entry", unknown_scope)
        with pytest.raises(WorktreeError, match="unsupported bogus scope"):
            install(str(repo.root))


class TestRollback:
    def test_prek_failure_rolls_back_owned_config(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_prek(root: str) -> None:
            raise WorktreeError("prek exploded")

        monkeypatch.setattr(worktree_install, "run_prek", failing_prek)
        with pytest.raises(WorktreeError, match="prek exploded"):
            install(str(repo.root))
        assert (
            git("config", "--worktree", "core.hooksPath", cwd=repo.root, check=False).returncode
            == 1
        )
        assert (
            git(
                "config",
                "--worktree",
                "merge.hdsh-pairing.driver",
                cwd=repo.root,
                check=False,
            ).returncode
            == 1
        )

    def test_hook_path_rollback_failure_is_aggregated(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_run_git = worktree_install.run_git

        def selective(
            root: str, args: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            if "--unset-all" in args and "core.hooksPath" in args:
                raise WorktreeError("unset exploded")
            return real_run_git(root, args, **kwargs)

        def failing_prek(root: str) -> None:
            raise WorktreeError("prek exploded")

        monkeypatch.setattr(worktree_install, "run_git", selective)
        monkeypatch.setattr(worktree_install, "run_prek", failing_prek)
        with pytest.raises(
            WorktreeError,
            match=r"prek hook installation failed: prek exploded.*"
            r"rollback also failed.*unset exploded",
        ):
            install(str(repo.root))

    def test_rollback_restores_previous_worktree_value(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(str(repo.root))
        hooks_value = git("config", "--worktree", "core.hooksPath", cwd=repo.root).stdout.strip()

        def failing_prek(root: str) -> None:
            raise WorktreeError("boom")

        monkeypatch.setattr(worktree_install, "run_prek", failing_prek)
        with pytest.raises(WorktreeError, match="boom"):
            install(str(repo.root))
        assert (
            git("config", "--worktree", "core.hooksPath", cwd=repo.root).stdout.strip()
            == hooks_value
        )


class TestInstallLock:
    def test_stale_lock_fails_loud(self, repo: Repo) -> None:
        common = git("rev-parse", "--git-common-dir", cwd=repo.root).stdout.strip()
        (repo.root / common / "hdsh-hooks-install.lock").write_text(
            "999999 12345678-1234-1234-1234-123456789012\n", encoding="utf-8"
        )
        with pytest.raises(WorktreeError, match="stale installer lock"):
            install(str(repo.root))

    def test_invalid_lock_fails_loud(self, repo: Repo) -> None:
        common = git("rev-parse", "--git-common-dir", cwd=repo.root).stdout.strip()
        (repo.root / common / "hdsh-hooks-install.lock").write_text("garbage\n", encoding="utf-8")
        with pytest.raises(WorktreeError, match="invalid installer lock"):
            install(str(repo.root))

    def test_lock_released_after_success(self, repo: Repo) -> None:
        install(str(repo.root))
        common = git("rev-parse", "--git-common-dir", cwd=repo.root).stdout.strip()
        assert not (repo.root / common / "hdsh-hooks-install.lock").exists()

    def test_release_failure_alone_surfaces(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_release(lock_path: object, record: str, owned_stat: object) -> None:
            raise WorktreeError("lock release exploded")

        monkeypatch.setattr(worktree_install, "release_install_lock", failing_release)
        with pytest.raises(WorktreeError, match="lock release exploded"):
            install(str(repo.root))

    def test_relocation_guard_fires_when_the_directory_vanishes(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        install(str(repo.root))
        foreign = "/foreign/relocated/hdsh-hooks"
        git("config", "--worktree", "core.hooksPath", foreign, cwd=repo.root)
        marker = repo.root / ".git" / "hdsh-hooks" / ".hdsh-hooks-owned"
        marker.write_text(
            json.dumps(
                {
                    "version": 1,
                    "owner": "harness-deepseek-harness worktree-local prek hooks",
                    "hooksPath": foreign,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        real_ensure = worktree_install.ensure_owned_hooks_directory

        def vanishing_ensure(hooks_path: str) -> str:
            shutil.rmtree(hooks_path)
            return real_ensure(hooks_path)

        monkeypatch.setattr(worktree_install, "ensure_owned_hooks_directory", vanishing_ensure)
        with pytest.raises(WorktreeError, match="ownership changed while relocating"):
            install(str(repo.root))


class TestGitVersion:
    def test_old_git_is_refused(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            worktree_install,
            "run_git",
            lambda root, args, **kwargs: _fake_git_version("git version 2.25.0"),
        )
        with pytest.raises(WorktreeError, match="Git 2.26"):
            install(str(repo.root))

    def test_unparsable_git_is_refused(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            worktree_install,
            "run_git",
            lambda root, args, **kwargs: _fake_git_version("not a version string"),
        )
        with pytest.raises(WorktreeError, match="cannot determine Git version"):
            install(str(repo.root))


class TestMain:
    def install_cli(self) -> int:
        return worktree_install.main(parse_command(worktree_install.register, ["install"]))

    def test_ci_environments_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        assert self.install_cli() == 0  # returns without touching git

    def test_github_actions_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert self.install_cli() == 0

    def test_outside_repository_returns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        completed = subprocess.CompletedProcess(["git"], 128, "", "fatal")
        monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: completed)
        assert self.install_cli() == 0

    def test_rev_parse_oserror_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

        def raising_run(*args: Any, **kwargs: Any) -> None:
            raise OSError("no git")

        monkeypatch.setattr(subprocess, "run", raising_run)
        assert self.install_cli() == 1

    def test_install_error_fails(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, **kwargs: subprocess.CompletedProcess(args, 0, f"{repo.root}\n", ""),
        )
        monkeypatch.setattr(
            worktree_install, "install", lambda root: (_ for _ in ()).throw(WorktreeError("boom"))
        )
        assert self.install_cli() == 1

    def test_main_preserves_trailing_space_in_root(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        seen: list[str] = []

        def recording_install(root: str) -> None:
            seen.append(root)

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, **kwargs: subprocess.CompletedProcess(args, 0, f"{repo.root} \n", ""),
        )
        monkeypatch.setattr(worktree_install, "install", recording_install)
        assert self.install_cli() == 0
        assert seen == [f"{repo.root} "]

    def test_extra_arguments_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unrecognized arguments"):
            parse_command(worktree_install.register, ["install", "--nope"])


def _fake_git_version(version: str) -> object:
    class Result:
        returncode = 0
        stdout = version

    return Result()


class TestInstallEdges:
    def test_effective_hooks_path_verification_fails(
        self, repo: Repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = worktree_install.effective_config_entry
        state = {"n": 0}

        def skewed(root: str, key: str) -> dict[str, str] | None:
            result = original(root, key)
            if key == "core.hooksPath":
                state["n"] += 1
                if state["n"] == 1:
                    return None
                if state["n"] == 2:
                    return {"scope": "local", "origin": "file:/x", "value": "y"}
            return result

        monkeypatch.setattr(worktree_install, "effective_config_entry", skewed)
        with pytest.raises(WorktreeError, match="did not become the effective"):
            install(str(repo.root))

    def test_marker_update_after_prek(self, repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
        install(str(repo.root))
        marker = repo.root / ".git" / "hdsh-hooks" / ".hdsh-hooks-owned"
        stale = json.dumps({"version": 1, "owner": marker_owner(), "hooksPath": "/gone"})
        marker.write_text(stale + "\n", encoding="utf-8")

        # A second install must refresh the marker to the live hooks path.
        install(str(repo.root))
        refreshed = json.loads(marker.read_text(encoding="utf-8"))
        assert refreshed["hooksPath"] == hooks_path_of(repo)


def marker_owner() -> str:
    from hdsh.worktree.ownership import OWNERSHIP_MARKER_OWNER

    return OWNERSHIP_MARKER_OWNER


def test_main_returns_zero_after_successful_install(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(worktree_install, "run_prek", lambda root: None)
    monkeypatch.chdir(repo.root)
    parsed = parse_command(worktree_install.register, ["install"])
    assert worktree_install.main(parsed) == 0
    assert capsys.readouterr().err == ""
