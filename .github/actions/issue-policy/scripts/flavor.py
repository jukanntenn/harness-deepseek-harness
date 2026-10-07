"""Resolve the deployment flavor and prove its credential inputs exist.

The flavor is read from the checked-in policy config; the calling workflow has
already mapped its secrets onto the environment variables below. Composite
actions cannot read the secrets context, so credentials only ever arrive as
inputs.

A default branch without a usable policy config — the config absent,
unparseable as JSON, or carrying no valid ``accountType`` — is the
first-adoption bootstrap moment: the pull request that introduces or
replaces the config cannot be validated against a policy that does not
exist yet, so exactly that pull request skips with a notice — every other
unusable config stays a loud failure.
"""

# ruff: noqa: S310 - every URL derives from the scheme-validated API root below

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

_EXPECTED_ARGUMENTS = 2
_ORGANIZATION_CREDENTIALS_MESSAGE = (
    "organization flavor requires the app-client-id and app-private-key inputs "
    "(vars.HDSH_ISSUE_APP_CLIENT_ID and secrets.HDSH_ISSUE_APP_PRIVATE_KEY)"
)
_USER_CREDENTIALS_MESSAGE = (
    "user flavor requires the project-token input "
    "(secrets.HDSH_ISSUE_PROJECT_TOKEN, classic PAT, project scope)"
)


def fail(title: str, scope: str, detail: str) -> None:
    """Emit one ``::error`` workflow annotation on stderr."""
    print(f"::error title={title} {scope}::{detail}", file=sys.stderr)


def _write_output(name: str, value: str) -> bool:
    """Append one ``name=value`` line to ``GITHUB_OUTPUT``.

    Returns:
        Whether the output file was mapped onto the step environment.
    """
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return False
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"{name}={value}\n")
    return True


def _next_page(link_header: str) -> str | None:
    """The ``rel="next"`` target of one Link header, or ``None`` at the end."""
    for part in link_header.split(","):
        fields = part.split(";")
        if len(fields) > 1 and fields[1].strip() == 'rel="next"':
            return fields[0].strip().strip("<>")
    return None


def _pull_request_filenames(repository: str, number: str, token: str) -> set[str]:
    """Every filename the pull request touches, following pagination."""
    api_root = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not api_root.startswith(("http://", "https://")):
        message = f"GITHUB_API_URL must be an http(s) root, got {api_root!r}"
        raise RuntimeError(message)
    url = f"{api_root}/repos/{repository}/pulls/{number}/files?per_page=100"
    names: set[str] = set()
    while url is not None:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.load(response)
            link_header = response.headers.get("Link", "")
        if not isinstance(page, list):
            message = f"expected a file array, got {type(page).__name__}"
            raise TypeError(message)
        names.update(entry.get("filename", "") for entry in page if isinstance(entry, dict))
        url = _next_page(link_header)
    return names


def _pull_request_introduces(config_path: str) -> bool:
    """Whether the event's pull request adds or modifies the config path.

    Returns:
        ``False`` whenever no pull request context exists — an issue event on a
        repository without a policy config is drift, not bootstrap.
    """
    number = os.environ.get("PR_NUMBER", "")
    if not number:
        return False
    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repository:
        message = "PR_NUMBER is set but GH_TOKEN or GITHUB_REPOSITORY is not mapped"
        raise RuntimeError(message)
    return config_path in _pull_request_filenames(repository, number, token)


def _bootstrap_or_drift(title: str, config_path: str, *, absent: bool, detail: str = "") -> int:
    """Bootstrap skip or loud drift for a default branch without a usable config.

    The default branch carries no policy to validate against when its config
    is absent or not an hdsh policy config; exactly the pull request that
    adds or modifies the config path bootstraps with a notice, and every
    other run fails loud naming the unusable state.

    Args:
        title: The workflow title prefix for annotations.
        config_path: The checked-out policy config path.
        absent: Whether the config is missing from the checkout entirely.
        detail: The foreign-schema reason, for the non-absent states.

    Returns:
        The process exit code.
    """
    try:
        introduces = _pull_request_introduces(config_path)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        fail(
            title,
            "config",
            f"cannot determine whether the pull request introduces {config_path}: {error}",
        )
        return 1
    if introduces:
        state = (
            "no policy config on the default branch yet; this pull request introduces it"
            if absent
            else f"the default-branch config is not an hdsh policy ({detail}); "
            "this pull request replaces it"
        )
        print(f"::notice title={title} bootstrap::{state}, so validation starts after merge")
        _write_output("skip", "true")
        return 0
    message = (
        f"{config_path} is absent from the default branch checkout"
        if absent
        else f"{config_path} on the default branch is not an hdsh policy config ({detail})"
    )
    fail(title, "config", message)
    return 1


def main() -> int:
    """Run the flavor-resolution gate; every failure path exits non-zero."""
    if len(sys.argv) != _EXPECTED_ARGUMENTS or not sys.argv[1]:
        print("usage: flavor.py <title>", file=sys.stderr)
        return 1
    title = sys.argv[1]
    config_path = os.environ.get("CONFIG_PATH")
    if not config_path:
        fail(title, "config", "CONFIG_PATH is not set; map the config-path input onto it")
        return 1
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _bootstrap_or_drift(title, config_path, absent=True)
    except ValueError as error:
        return _bootstrap_or_drift(
            title, config_path, absent=False, detail=f"unparseable as JSON: {error}"
        )
    except OSError as error:
        fail(title, "config", f"cannot read the policy config {config_path}: {error}")
        return 1
    flavor = config.get("accountType") if isinstance(config, dict) else None
    match flavor:
        case "organization":
            if not os.environ.get("APP_CLIENT_ID") or not os.environ.get("APP_PRIVATE_KEY"):
                fail(title, "credentials", _ORGANIZATION_CREDENTIALS_MESSAGE)
                return 1
        case "user":
            if not os.environ.get("PROJECT_TOKEN"):
                fail(title, "credentials", _USER_CREDENTIALS_MESSAGE)
                return 1
        case _:
            return _bootstrap_or_drift(
                title, config_path, absent=False, detail=f"unknown accountType '{flavor}'"
            )
    if not _write_output("account-type", flavor):
        fail(title, "config", "GITHUB_OUTPUT is not set; run inside a workflow step")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
