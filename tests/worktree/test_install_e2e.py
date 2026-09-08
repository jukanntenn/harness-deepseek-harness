"""End-to-end installer runs against real Git with a fake prek executable."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from hdsh.worktree.git import WorktreeError
from hdsh.worktree.install import install
from tests.helpers import git

FAKE_PREK = """#!/bin/sh
set -u
if [ "$#" -ne 2 ] || [ "$1" != "install" ] || [ "$2" != "--overwrite" ]; then
  echo "fake prek: unexpected arguments: $*" >&2
  exit 64
fi
if [ -n "${HDSH_TEST_FORBIDDEN_KEY:-}" ]; then
  if git config --get "$HDSH_TEST_FORBIDDEN_KEY" >/dev/null 2>&1; then
    exit 92
  fi
fi
hooks=$(git config --get core.hooksPath)
mkdir -p "$hooks"
running="$hooks/.fake-prek-running"
if ! (set -C; printf '%s' "$$" > "$running") 2>/dev/null; then
  exit 91
fi
if [ -n "${HDSH_TEST_GO_FILE:-}" ]; then
  while [ ! -f "$HDSH_TEST_GO_FILE" ]; do
    sleep 0.01
  done
fi
if [ -n "${HDSH_TEST_BREAK_WORKTREE_CONFIG:-}" ]; then
  printf '[invalid\\n' > "$(git rev-parse --git-path config.worktree)"
fi
if [ -n "${HDSH_TEST_FAIL:-}" ]; then
  rm -f "$running"
  exit 77
fi
root=$(git rev-parse --show-toplevel)
config=$(cat prek.toml 2>/dev/null || echo no-config)
for name in pre-commit pre-merge-commit pre-push; do
  printf '#!/bin/sh\\n# root=%s\\n# config=%s\\nexit 0\\n' "$root" "$config" > "$hooks/$name"
  chmod 755 "$hooks/$name"
done
rm -f "$running"
"""

FAKE_UV = """#!/bin/sh
if [ -n "${HDSH_TEST_UV_LOG:-}" ]; then
  printf '%s\\n' "$*" >> "$HDSH_TEST_UV_LOG"
fi
exit ${HDSH_TEST_UV_STATUS:-0}
"""

_INSTALLER_CODE = "import sys; from hdsh.worktree.install import install; install(sys.argv[1])"


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.email", "hooks@example.test", cwd=path)
    git("config", "user.name", "Hooks Test", cwd=path)
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    git("add", "README.md", cwd=path)
    git("commit", "-m", "fixture", cwd=path)
    return path


def git_dir_of(root: Path) -> str:
    return git("rev-parse", "--absolute-git-dir", cwd=root).stdout.strip()


def hooks_path_of(root: Path) -> str:
    return str(Path(git_dir_of(root), "hdsh-hooks"))


def common_dir_of(root: Path) -> Path:
    output = git("rev-parse", "--git-common-dir", cwd=root).stdout.strip()
    path = Path(output)
    return path if path.is_absolute() else root / path


@pytest.fixture
def worktrees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A main worktree plus a linked one, with fake prek and uv on PATH."""
    main = _init_repo(tmp_path / "main")
    linked = tmp_path / "linked"
    git("worktree", "add", "-b", "linked", str(linked), cwd=main)
    (main / "prek.toml").write_text("main-worktree-config\n", encoding="utf-8")
    (linked / "prek.toml").write_text("linked-worktree-config\n", encoding="utf-8")
    legacy = common_dir_of(main) / "hooks" / "pre-commit"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("#!/bin/sh\n# legacy hook\n", encoding="utf-8")
    legacy.chmod(0o755)
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    fake_prek = bin_directory / "prek"
    fake_prek.write_text(FAKE_PREK, encoding="utf-8")
    fake_prek.chmod(0o755)
    fake_uv = bin_directory / "uv"
    fake_uv.write_text(FAKE_UV, encoding="utf-8")
    fake_uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_directory}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("HDSH_TEST_UV_LOG", str(tmp_path / "uv.log"))
    return {
        "container": tmp_path,
        "main": main,
        "linked": linked,
        "bin": bin_directory,
        "legacy": legacy,
    }


def _spawn_installer(root: Path, extra_env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", _INSTALLER_CODE, str(root)],
        env={**os.environ, **extra_env},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.01)


class TestIsolation:
    def test_isolates_worktrees_without_touching_legacy_hooks(
        self, worktrees: dict[str, Any]
    ) -> None:
        main, linked = worktrees["main"], worktrees["linked"]
        install(str(main))
        install(str(linked))

        main_hooks, linked_hooks = hooks_path_of(main), hooks_path_of(linked)
        assert main_hooks != linked_hooks
        assert git("config", "--worktree", "core.hooksPath", cwd=main).stdout.strip() == main_hooks
        assert (
            git("config", "--worktree", "core.hooksPath", cwd=linked).stdout.strip() == linked_hooks
        )
        assert (
            git("config", "--worktree", "merge.hdsh-pairing.driver", cwd=main)
            .stdout.strip()
            .startswith("scripts/pairing-merge-driver.sh")
        )
        assert (
            git("config", "--worktree", "merge.hdsh-pairing.driver", cwd=linked)
            .stdout.strip()
            .startswith("scripts/pairing-merge-driver.sh")
        )
        main_hook = (Path(main_hooks) / "pre-commit").read_text(encoding="utf-8")
        linked_hook = (Path(linked_hooks) / "pre-commit").read_text(encoding="utf-8")
        assert f"# root={main}" in main_hook
        assert "# config=main-worktree-config" in main_hook
        assert str(linked) not in main_hook
        assert f"# root={linked}" in linked_hook
        assert "# config=linked-worktree-config" in linked_hook
        assert str(main) not in linked_hook
        assert (Path(main_hooks) / "pre-merge-commit").is_file()
        assert worktrees["legacy"].read_text(encoding="utf-8") == "#!/bin/sh\n# legacy hook\n"

        common = common_dir_of(main) / "config"
        assert (
            git(
                "config", "--file", str(common), "core.repositoryFormatVersion", cwd=main
            ).stdout.strip()
            == "1"
        )
        assert (
            git(
                "config", "--file", str(common), "extensions.worktreeConfig", cwd=main
            ).stdout.strip()
            == "true"
        )
        assert (
            git("config", "--file", str(common), "core.bare", cwd=main, check=False).returncode == 1
        )

        main_hook_before = main_hook
        git("worktree", "remove", "--force", str(linked), cwd=main)
        assert (Path(main_hooks) / "pre-commit").read_text(encoding="utf-8") == main_hook_before
        assert worktrees["legacy"].read_text(encoding="utf-8") == "#!/bin/sh\n# legacy hook\n"

    def test_replaces_the_owned_hook_path_git_copies_into_new_worktrees(
        self, worktrees: dict[str, Any]
    ) -> None:
        main = worktrees["main"]
        install(str(main))
        main_hooks = hooks_path_of(main)
        main_hook_before = (Path(main_hooks) / "pre-commit").read_text(encoding="utf-8")

        late = worktrees["container"] / "late"
        git("worktree", "add", "-b", "late-linked", str(late), cwd=main)
        (late / "prek.toml").write_text("late-worktree-config\n", encoding="utf-8")
        assert git("config", "--worktree", "core.hooksPath", cwd=late).stdout.strip() == main_hooks

        install(str(late))

        late_hooks = hooks_path_of(late)
        assert late_hooks != main_hooks
        assert git("config", "--worktree", "core.hooksPath", cwd=late).stdout.strip() == late_hooks
        late_hook = (Path(late_hooks) / "pre-commit").read_text(encoding="utf-8")
        assert "# config=late-worktree-config" in late_hook
        assert (Path(main_hooks) / "pre-commit").read_text(encoding="utf-8") == main_hook_before

    def test_repairs_its_owned_absolute_hook_path_after_the_checkout_moves(
        self, worktrees: dict[str, Any]
    ) -> None:
        main = worktrees["main"]
        install(str(main))
        old_hooks = hooks_path_of(main)

        moved = worktrees["container"] / "moved-main"
        shutil.move(str(main), str(moved))
        install(str(moved))

        moved_hooks = hooks_path_of(moved)
        assert moved_hooks != old_hooks
        assert (
            git("config", "--worktree", "core.hooksPath", cwd=moved).stdout.strip() == moved_hooks
        )
        moved_hook = (Path(moved_hooks) / "pre-commit").read_text(encoding="utf-8")
        assert f"# root={moved}" in moved_hook
        moved_marker = json.loads(
            (Path(moved_hooks) / ".hdsh-hooks-owned").read_text(encoding="utf-8")
        )
        assert moved_marker["hooksPath"] == moved_hooks

    def test_restores_the_marker_backed_stale_path_when_relocation_reinstall_fails(
        self, worktrees: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        main = worktrees["main"]
        install(str(main))
        old_hooks = hooks_path_of(main)
        previous_marker = (Path(old_hooks) / ".hdsh-hooks-owned").read_text(encoding="utf-8")

        moved = worktrees["container"] / "moved-main"
        shutil.move(str(main), str(moved))
        monkeypatch.setenv("HDSH_TEST_FAIL", "1")
        with pytest.raises(WorktreeError, match="exit status 77"):
            install(str(moved))

        moved_hooks = hooks_path_of(moved)
        assert git("config", "--worktree", "core.hooksPath", cwd=moved).stdout.strip() == old_hooks
        assert (Path(moved_hooks) / ".hdsh-hooks-owned").read_text(encoding="utf-8") == (
            previous_marker
        )

    def test_preserves_trailing_spaces_in_worktree_paths(self, tmp_path: Path) -> None:
        main = _init_repo(tmp_path / "main ")
        bin_directory = tmp_path / "bin"
        bin_directory.mkdir()
        for name, content in (("prek", FAKE_PREK), ("uv", FAKE_UV)):
            shim = bin_directory / name
            shim.write_text(content, encoding="utf-8")
            shim.chmod(0o755)
        saved_path = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_directory}{os.pathsep}{saved_path}"
        try:
            install(str(main))
            assert git(
                "config", "--worktree", "core.hooksPath", cwd=main
            ).stdout.strip() == hooks_path_of(main)
        finally:
            os.environ["PATH"] = saved_path


class TestConcurrency:
    def test_serializes_concurrent_installs(
        self, worktrees: dict[str, Any], tmp_path: Path
    ) -> None:
        main, linked = worktrees["main"], worktrees["linked"]
        go_file = tmp_path / "go"
        main_running = Path(hooks_path_of(main)) / ".fake-prek-running"
        linked_running = Path(hooks_path_of(linked)) / ".fake-prek-running"

        first = _spawn_installer(main, {"HDSH_TEST_GO_FILE": str(go_file)})
        second = _spawn_installer(linked, {"HDSH_TEST_GO_FILE": str(go_file)})
        try:
            _wait_for(main_running)
        except AssertionError:
            first.wait(timeout=30)
            second.kill()
            pytest.skip("installer finished before the running marker could be observed")
        go_file.touch()
        assert first.wait(timeout=30) == 0
        assert second.wait(timeout=30) == 0

        assert not main_running.exists()
        assert not linked_running.exists()
        assert not (common_dir_of(main) / "hdsh-hooks-install.lock").exists()
        assert "# config=main-worktree-config" in (
            Path(hooks_path_of(main)) / "pre-commit"
        ).read_text(encoding="utf-8")
        assert "# config=linked-worktree-config" in (
            Path(hooks_path_of(linked)) / "pre-commit"
        ).read_text(encoding="utf-8")


class TestRefusals:
    def test_refuses_a_sibling_dormant_worktree_config(self, worktrees: dict[str, Any]) -> None:
        main, linked = worktrees["main"], worktrees["linked"]
        linked_hooks = worktrees["container"] / "custom-hooks"
        sibling_config = Path(git_dir_of(linked)) / "config.worktree"
        git("config", "--file", str(sibling_config), "core.hooksPath", str(linked_hooks), cwd=main)
        assert git("config", "core.hooksPath", cwd=linked, check=False).returncode == 1

        with pytest.raises(WorktreeError, match="sibling dormant worktree config"):
            install(str(main))

        assert git("config", "extensions.worktreeConfig", cwd=main, check=False).returncode == 1
        assert git("config", "core.hooksPath", cwd=linked, check=False).returncode == 1
        assert git(
            "config", "--file", str(sibling_config), "core.hooksPath", cwd=main
        ).stdout.strip() == str(linked_hooks)
        assert not Path(hooks_path_of(main)).exists()

    def test_refuses_an_active_symlinked_worktree_config(
        self, worktrees: dict[str, Any], tmp_path: Path
    ) -> None:
        main = worktrees["main"]
        common = common_dir_of(main) / "config"
        git("config", "--file", str(common), "core.repositoryFormatVersion", "1", cwd=main)
        git("config", "--file", str(common), "extensions.worktreeConfig", "true", cwd=main)
        external = tmp_path / "external.gitconfig"
        external.write_text("[user]\n\tname = External owner\n", encoding="utf-8")
        worktree_config = Path(git_dir_of(main)) / "config.worktree"
        worktree_config.symlink_to(external)

        with pytest.raises(WorktreeError, match=r"active worktree config .* not a regular file"):
            install(str(main))
        assert external.read_text(encoding="utf-8") == "[user]\n\tname = External owner\n"
        assert not Path(hooks_path_of(main)).exists()

    def test_refuses_a_symlinked_common_repository_config(
        self, worktrees: dict[str, Any], tmp_path: Path
    ) -> None:
        main = worktrees["main"]
        common = common_dir_of(main) / "config"
        external = tmp_path / "external-common.gitconfig"
        shutil.move(str(common), str(external))
        common.symlink_to(external)

        with pytest.raises(WorktreeError, match="not a regular file"):
            install(str(main))
        assert common.is_symlink()
        assert not Path(hooks_path_of(main)).exists()
        assert git("config", "extensions.worktreeConfig", cwd=main, check=False).returncode == 1

    def test_never_trusts_an_ownership_marker_outside_registered_hook_paths(
        self, worktrees: dict[str, Any]
    ) -> None:
        main, linked = worktrees["main"], worktrees["linked"]
        install(str(main))
        external_hooks = worktrees["container"] / "external-owned-hooks"
        external_hooks.mkdir()
        (external_hooks / ".hdsh-hooks-owned").write_text(
            '{"version": 1, "owner": "harness-deepseek-harness worktree-local prek hooks",'
            f' "hooksPath": "{external_hooks}"}}\n',
            encoding="utf-8",
        )
        git("config", "--worktree", "core.hooksPath", str(external_hooks), cwd=linked)

        with pytest.raises(WorktreeError, match="worktree-scoped core.hooksPath"):
            install(str(linked))
        assert git("config", "--worktree", "core.hooksPath", cwd=linked).stdout.strip() == str(
            external_hooks
        )
        assert not Path(hooks_path_of(linked)).exists()

    def test_never_overrides_a_hook_path_included_by_worktree_config(
        self, worktrees: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        main = worktrees["main"]
        included_hooks = worktrees["container"] / "included-hooks"
        included_hooks.mkdir()
        sentinel = included_hooks / "pre-commit"
        sentinel.write_text("#!/bin/sh\n# sentinel\n", encoding="utf-8")
        included_config = worktrees["container"] / "included.gitconfig"
        git(
            "config",
            "--file",
            str(included_config),
            "core.hooksPath",
            str(included_hooks),
            cwd=main,
        )
        common = common_dir_of(main) / "config"
        git("config", "--file", str(common), "core.repositoryFormatVersion", "1", cwd=main)
        git("config", "--file", str(common), "extensions.worktreeConfig", "true", cwd=main)
        git(
            "config",
            "--file",
            str(Path(git_dir_of(main)) / "config.worktree"),
            "include.path",
            str(included_config),
            cwd=main,
        )
        monkeypatch.setenv("HDSH_PREK_ALLOW_HOOKS_PATH_OVERRIDE", "1")

        with pytest.raises(WorktreeError, match="worktree-scoped core.hooksPath"):
            install(str(main))
        assert sentinel.read_text(encoding="utf-8") == "#!/bin/sh\n# sentinel\n"
        assert not Path(hooks_path_of(main)).exists()

    def test_never_overrides_a_command_scoped_hook_path(
        self, worktrees: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        main = worktrees["main"]
        command_hooks = worktrees["container"] / "command-hooks"
        command_hooks.mkdir()
        sentinel = command_hooks / "pre-commit"
        sentinel.write_text("#!/bin/sh\n# sentinel\n", encoding="utf-8")
        monkeypatch.setenv("HDSH_PREK_ALLOW_HOOKS_PATH_OVERRIDE", "1")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(command_hooks))

        with pytest.raises(WorktreeError, match="command-scoped core.hooksPath"):
            install(str(main))
        monkeypatch.delenv("GIT_CONFIG_COUNT")
        monkeypatch.delenv("GIT_CONFIG_KEY_0")
        monkeypatch.delenv("GIT_CONFIG_VALUE_0")
        assert sentinel.read_text(encoding="utf-8") == "#!/bin/sh\n# sentinel\n"
        assert git("config", "core.hooksPath", cwd=main, check=False).returncode == 1
        assert git("config", "merge.hdsh-pairing.driver", cwd=main, check=False).returncode == 1
        assert not Path(hooks_path_of(main)).exists()

    def test_old_git_is_refused_before_any_mutation(
        self, worktrees: dict[str, Any], tmp_path: Path
    ) -> None:
        main = worktrees["main"]
        real_git = shutil.which("git")
        assert real_git is not None
        fake_bin = tmp_path / "fake-bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        fake_git.write_text(
            "#!/bin/sh\n"
            'for arg in "$@"; do\n'
            '  if [ "$arg" = "--version" ]; then echo "git version 2.25.0"; exit 0; fi\n'
            "done\n"
            f'exec "{real_git}" "$@"\n',
            encoding="utf-8",
        )
        fake_git.chmod(0o755)
        saved_path = os.environ["PATH"]
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{saved_path}"
        try:
            with pytest.raises(WorktreeError, match="Git 2.26 or newer is required"):
                install(str(main))
        finally:
            os.environ["PATH"] = saved_path
        assert git("config", "extensions.worktreeConfig", cwd=main, check=False).returncode == 1
        assert not Path(hooks_path_of(main)).exists()

    def test_missing_prek_fails_loud_and_rolls_back(
        self, worktrees: dict[str, Any], tmp_path: Path
    ) -> None:
        main = worktrees["main"]
        bin_without_prek = tmp_path / "bin-no-prek"
        bin_without_prek.mkdir()
        real_git = shutil.which("git")
        assert real_git is not None
        (bin_without_prek / "git").symlink_to(real_git)
        (bin_without_prek / "uv").symlink_to(worktrees["bin"] / "uv")
        saved_path = os.environ["PATH"]
        # The replacement PATH carries Git and uv but no prek at all.
        os.environ["PATH"] = str(bin_without_prek)
        try:
            with pytest.raises(WorktreeError, match="prek install --overwrite failed"):
                install(str(main))
        finally:
            os.environ["PATH"] = saved_path
        assert git("config", "--worktree", "core.hooksPath", cwd=main, check=False).returncode == 1
        assert (
            git(
                "config", "--worktree", "merge.hdsh-pairing.driver", cwd=main, check=False
            ).returncode
            == 1
        )


class TestIncludes:
    @pytest.mark.parametrize("include_key", ["include.path", "includeIf.onbranch:main.path"])
    @pytest.mark.parametrize("key", ["core.worktree", "core.bare", "extensions.dshunknown"])
    def test_ignores_included_common_settings(
        self, worktrees: dict[str, Any], include_key: str, key: str
    ) -> None:
        main, linked = worktrees["main"], worktrees["linked"]
        included_config = worktrees["container"] / f"included-{key}.gitconfig"
        value = str(main) if key == "core.worktree" else "true"
        git("config", "--file", str(included_config), key, value, cwd=main)
        git(
            "config",
            "--file",
            str(common_dir_of(main) / "config"),
            include_key,
            str(included_config),
            cwd=main,
        )

        install(str(linked))

        assert git(
            "config", "--worktree", "core.hooksPath", cwd=linked
        ).stdout.strip() == hooks_path_of(linked)
        assert (Path(hooks_path_of(linked)) / "pre-commit").is_file()

    def test_ignores_an_inactive_global_includeif_hooks_path(
        self, worktrees: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        main, linked = worktrees["main"], worktrees["linked"]
        global_config = worktrees["container"] / "global.gitconfig"
        included_config = worktrees["container"] / "other-repository.gitconfig"
        included_hooks = worktrees["container"] / "other-repository-hooks"
        git(
            "config",
            "--file",
            str(included_config),
            "core.hooksPath",
            str(included_hooks),
            cwd=main,
        )
        git(
            "config",
            "--file",
            str(global_config),
            f"includeIf.gitdir:{worktrees['container'] / 'other'}/.path",
            str(included_config),
            cwd=main,
        )
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))

        install(str(linked))

        assert git("config", "--get", "core.hooksPath", cwd=linked).stdout.strip() == hooks_path_of(
            linked
        )


class TestProbeAndPrekBoundary:
    def test_publishes_nothing_when_the_pairing_probe_fails(
        self, worktrees: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        main = worktrees["main"]
        monkeypatch.setenv("HDSH_TEST_UV_STATUS", "1")

        with pytest.raises(WorktreeError, match="pairing merge --probe failed"):
            install(str(main))
        assert git("config", "--worktree", "core.hooksPath", cwd=main, check=False).returncode == 1
        assert git("config", "merge.hdsh-pairing.driver", cwd=main, check=False).returncode == 1
        assert Path(hooks_path_of(main)).is_dir()

    def test_does_not_pass_command_git_config_to_prek(
        self, worktrees: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        main = worktrees["main"]
        monkeypatch.setenv("HDSH_TEST_FORBIDDEN_KEY", "hdsh.testSentinel")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "hdsh.testSentinel")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "must-not-reach-prek")

        install(str(main))
        assert (Path(hooks_path_of(main)) / "pre-commit").is_file()

    def test_reports_installation_and_rollback_failures_together(
        self, worktrees: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        main = worktrees["main"]
        monkeypatch.setenv("HDSH_TEST_BREAK_WORKTREE_CONFIG", "1")
        monkeypatch.setenv("HDSH_TEST_FAIL", "1")

        with pytest.raises(
            WorktreeError,
            match=r"prek hook installation failed: .*exit status 77.*"
            r"rollback also failed.*unset-all core\.hooksPath failed",
        ):
            install(str(main))

    def test_refuses_multiply_linked_generated_hooks(
        self, worktrees: dict[str, Any], tmp_path: Path
    ) -> None:
        main = worktrees["main"]
        install(str(main))
        hook = Path(hooks_path_of(main)) / "pre-commit"
        external = tmp_path / "external-hook"
        os.link(hook, external)

        with pytest.raises(WorktreeError, match="non-regular or multiply linked hook entry"):
            install(str(main))
        assert external.read_text(encoding="utf-8").startswith("#!/bin/sh")

    def test_refuses_a_multiply_linked_ownership_marker(
        self, worktrees: dict[str, Any], tmp_path: Path
    ) -> None:
        main = worktrees["main"]
        install(str(main))
        marker = Path(hooks_path_of(main)) / ".hdsh-hooks-owned"
        external = tmp_path / "external-marker"
        os.link(marker, external)
        external_content = external.read_text(encoding="utf-8")

        with pytest.raises(WorktreeError, match="invalid ownership marker"):
            install(str(main))
        assert external.read_text(encoding="utf-8") == external_content
