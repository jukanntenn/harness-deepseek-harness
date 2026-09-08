#!/bin/sh
# Fail-closed entry for git's *.i18n.yaml merge driver. When the runtime is
# unavailable the driver leaves an ordinary text conflict and exits non-zero
# so Git keeps the index stages unresolved until the repository-aware
# resolver runs.

if [ "$#" -ne 4 ]; then
  echo 'hdsh pairing merge: expected <ancestor> <current> <other> <repository-path>' >&2
  exit 129
fi

ancestor_path=$1
current_path=$2
other_path=$3
meta_path=$4
driver_directory=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 129

if command -v uv >/dev/null 2>&1 \
  && uv run --no-sync hdsh pairing merge --probe >/dev/null 2>&1; then
  exec uv run --no-sync hdsh pairing merge \
    "$ancestor_path" "$current_path" "$other_path" "$meta_path"
fi

echo "hdsh pairing merge: runtime is unavailable; leaving an ordinary text conflict in $meta_path" >&2
git merge-file \
  -L "$meta_path:current" \
  -L "$meta_path:ancestor" \
  -L "$meta_path:other" \
  -- "$current_path" "$ancestor_path" "$other_path"
fallback_status=$?
echo 'hdsh pairing merge: restore the project environment (uv sync), then rerun the merge or `hdsh pairing merge --resolve`; use `git merge --abort` to cancel' >&2

# A clean text merge is still unverified pairing metadata, so the driver must
# leave Git's index stages unresolved until the repository-aware resolver runs.
if [ "$fallback_status" -gt 127 ]; then
  exit "$fallback_status"
fi
exit 1
