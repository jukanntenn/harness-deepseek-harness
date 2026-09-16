#!/bin/sh
# Resolve the deployment flavor from the checked-in policy config and prove
# that the matching credential inputs exist; the calling workflow has already
# mapped its secrets onto the environment variables below. Composite actions
# cannot read the secrets context, so credentials only ever arrive as inputs.
set -eu

title=${1:?usage: flavor.sh <title>}
flavor=$(jq -r .accountType "$CONFIG_PATH")
case "$flavor" in
  organization)
    if [ -z "$APP_CLIENT_ID" ] || [ -z "$APP_PRIVATE_KEY" ]; then
      echo "::error title=${title} credentials::organization flavor requires the app-client-id and app-private-key inputs (vars.HDSH_ISSUE_APP_CLIENT_ID and secrets.HDSH_ISSUE_APP_PRIVATE_KEY)" >&2
      exit 1
    fi
    ;;
  user)
    if [ -z "$PROJECT_TOKEN" ]; then
      echo "::error title=${title} credentials::user flavor requires the project-token input (secrets.HDSH_ISSUE_PROJECT_TOKEN, classic PAT, project scope)" >&2
      exit 1
    fi
    ;;
  *)
    echo "::error title=${title} config::unknown accountType '$flavor' in $CONFIG_PATH" >&2
    exit 1
    ;;
esac
echo "account-type=$flavor" >> "$GITHUB_OUTPUT"
