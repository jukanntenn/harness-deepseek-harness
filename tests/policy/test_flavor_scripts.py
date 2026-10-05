"""The composite actions' flavor scripts: flavor resolution and the bootstrap skip."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, NamedTuple, override

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = (
    _REPOSITORY_ROOT / ".github" / "actions" / "issue-policy" / "scripts" / "flavor.py",
    _REPOSITORY_ROOT / ".github" / "actions" / "issue-lifecycle" / "scripts" / "flavor.py",
)
_CONFIG_PATH = ".github/issue-management/config.json"


class _PagesHandler(BaseHTTPRequestHandler):
    """Serves one pull-request file listing per query, with Link pagination."""

    pages: ClassVar[dict[str, list[dict[str, str]]]] = {}
    failures: ClassVar[dict[str, int]] = {}

    def do_GET(self) -> None:
        if self.path in self.failures:
            self.send_error(self.failures[self.path])
            return
        page = self.pages.get(self.path)
        if page is None:
            self.send_error(404)
            return
        body = json.dumps(page).encode("utf-8")
        paths = list(self.pages)
        index = paths.index(self.path)
        link = ""
        if index + 1 < len(paths):
            link = f'<http://{self.headers.get("Host")}{paths[index + 1]}>; rel="next"'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if link:
            self.send_header("Link", link)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @override
    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture
def files_api(tmp_path: Path) -> Any:
    """A local pull-request files API answering under its root URL."""
    created: list[ThreadingHTTPServer] = []

    def serve(
        pages: dict[str, list[dict[str, str]]], failures: dict[str, int] | None = None
    ) -> str:
        _PagesHandler.pages = pages
        _PagesHandler.failures = failures or {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _PagesHandler)
        created.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield serve
    for server in created:
        server.shutdown()


class FlavorResult(NamedTuple):
    """One flavor-script run: the process channels plus the GITHUB_OUTPUT file."""

    returncode: int
    stdout: str
    stderr: str
    output_text: str


def run_flavor(
    script: Path,
    tmp_path: Path,
    *,
    config: str | None,
    environment: dict[str, str],
) -> FlavorResult:
    """Run one flavor script with a scratch working directory and output file."""
    working = tmp_path / "work"
    working.mkdir()
    if config is not None:
        (working / _CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
        (working / _CONFIG_PATH).write_text(config, encoding="utf-8")
    output = tmp_path / "output"
    completed = subprocess.run(
        [sys.executable, str(script), "Issue policy"],
        cwd=working,
        capture_output=True,
        text=True,
        check=False,
        env={
            "CONFIG_PATH": _CONFIG_PATH,
            "GITHUB_OUTPUT": str(output),
            **environment,
        },
    )
    output_text = output.read_text(encoding="utf-8") if output.exists() else ""
    return FlavorResult(completed.returncode, completed.stdout, completed.stderr, output_text)


class TestFlavorResolution:
    @pytest.mark.parametrize("script", _SCRIPTS)
    def test_organization_with_credentials_passes(self, script: Path, tmp_path: Path) -> None:
        completed = run_flavor(
            script,
            tmp_path,
            config='{"accountType": "organization"}',
            environment={"APP_CLIENT_ID": "id", "APP_PRIVATE_KEY": "key"},
        )
        assert completed.returncode == 0
        assert "account-type=organization" in completed.output_text

    @pytest.mark.parametrize("script", _SCRIPTS)
    def test_missing_config_path_env_fails(self, script: Path, tmp_path: Path) -> None:
        working = tmp_path / "work"
        working.mkdir()
        completed = subprocess.run(
            [sys.executable, str(script), "Issue policy"],
            cwd=working,
            capture_output=True,
            text=True,
            check=False,
            env={"GITHUB_OUTPUT": str(tmp_path / "output")},
        )
        assert completed.returncode == 1
        assert "CONFIG_PATH is not set" in completed.stderr

    @pytest.mark.parametrize("script", _SCRIPTS)
    def test_usage_errors_fail(self, script: Path, tmp_path: Path) -> None:
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            env={},
        )
        assert completed.returncode == 1
        assert "usage:" in completed.stderr


class TestBootstrapSkip:
    @pytest.mark.parametrize("script", _SCRIPTS)
    def test_the_introducing_pull_request_skips_with_a_notice(
        self, script: Path, tmp_path: Path, files_api: Any
    ) -> None:
        root = files_api(
            {
                "/repos/o/r/pulls/7/files?per_page=100": [{"filename": "README.md"}],
                "/repos/o/r/pulls/7/files?page=2": [{"filename": _CONFIG_PATH}],
            }
        )
        completed = run_flavor(
            script,
            tmp_path,
            config=None,
            environment={
                "PR_NUMBER": "7",
                "GH_TOKEN": "token",
                "GITHUB_REPOSITORY": "o/r",
                "GITHUB_API_URL": root,
            },
        )
        assert completed.returncode == 0
        assert "bootstrap" in completed.stdout
        assert "skip=true" in completed.output_text
        assert "account-type" not in completed.output_text

    @pytest.mark.parametrize("script", _SCRIPTS)
    def test_an_unrelated_pull_request_stays_a_loud_failure(
        self, script: Path, tmp_path: Path, files_api: Any
    ) -> None:
        root = files_api({"/repos/o/r/pulls/8/files?per_page=100": [{"filename": "README.md"}]})
        completed = run_flavor(
            script,
            tmp_path,
            config=None,
            environment={
                "PR_NUMBER": "8",
                "GH_TOKEN": "token",
                "GITHUB_REPOSITORY": "o/r",
                "GITHUB_API_URL": root,
            },
        )
        assert completed.returncode == 1
        assert "absent from the default branch checkout" in completed.stderr
        assert completed.output_text == ""

    @pytest.mark.parametrize("script", _SCRIPTS)
    def test_an_event_without_a_pull_request_stays_a_loud_failure(
        self, script: Path, tmp_path: Path
    ) -> None:
        completed = run_flavor(script, tmp_path, config=None, environment={})
        assert completed.returncode == 1
        assert "absent from the default branch checkout" in completed.stderr

    @pytest.mark.parametrize("script", _SCRIPTS)
    def test_a_pull_request_without_the_token_mapping_fails_loud(
        self, script: Path, tmp_path: Path
    ) -> None:
        completed = run_flavor(
            script,
            tmp_path,
            config=None,
            environment={"PR_NUMBER": "9", "GITHUB_REPOSITORY": "o/r"},
        )
        assert completed.returncode == 1
        assert "cannot determine whether the pull request introduces" in completed.stderr

    @pytest.mark.parametrize("script", _SCRIPTS)
    def test_an_unreachable_files_api_fails_loud(
        self, script: Path, tmp_path: Path, files_api: Any
    ) -> None:
        root = files_api(
            {},
            failures={"/repos/o/r/pulls/10/files?per_page=100": 500},
        )
        completed = run_flavor(
            script,
            tmp_path,
            config=None,
            environment={
                "PR_NUMBER": "10",
                "GH_TOKEN": "token",
                "GITHUB_REPOSITORY": "o/r",
                "GITHUB_API_URL": root,
            },
        )
        assert completed.returncode == 1
        assert "cannot determine whether the pull request introduces" in completed.stderr
