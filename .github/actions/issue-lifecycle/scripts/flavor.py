"""Resolve the deployment flavor and prove its credential inputs exist.

The flavor is read from the checked-in policy config; the calling workflow has
already mapped its secrets onto the environment variables below. Composite
actions cannot read the secrets context, so credentials only ever arrive as
inputs.
"""

from __future__ import annotations

import json
import os
import sys
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
    except (OSError, ValueError) as error:
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
            fail(title, "config", f"unknown accountType '{flavor}' in {config_path}")
            return 1
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        fail(title, "config", "GITHUB_OUTPUT is not set; run inside a workflow step")
        return 1
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"account-type={flavor}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
