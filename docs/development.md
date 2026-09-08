# Development guide

English | [中文](development.zh.md)

The setup tutorial takes a new contributor from prerequisites to a checked checkout. The contributor reference that follows covers daily workflow, Git integrations, and CI organization. Design rationale belongs in the linked RFCs; the package map belongs in [architecture.md](architecture.md).

## Setup tutorial

### Prerequisites

- Python 3.12 or newer; CI covers the supported minimum and current releases.
- [uv](https://github.com/astral-sh/uv) manages the project and lockfile.
- Git 2.26 or newer; worktree-local hooks use Git's worktree-specific configuration extension.

### First-time setup

Install dependencies from the repository root:

```sh
uv sync
```

The install also configures repository-level prek hooks:

```sh
uv run prek install
```

If you work in stacked Git worktrees, install the worktree-local hooks and the `hdsh-pairing` merge driver instead — each new worktree needs its own run:

```sh
uv run hdsh worktree install
```

Run the checks once after a fresh clone:

```sh
uv run pytest
uv run ruff check .
uv run basedpyright
```

Setup is complete when all three exit successfully.

## Contributor reference

### Project layout

One name identifies one concept across the directory, the CLI domain, and the hook-id prefix: `pairing/`, `docs/`, `rfc/`, `policy/`, `worktree/`, and `scope.py` under `src/hdsh/`, behind the single `hdsh` entry point. The full map — domains, exit-code contract, and where new behavior goes — is [architecture.md](architecture.md).

### Git integrations

The pairing merge driver derives a conflicted `.i18n.yaml` record from the confirmed ancestor, current, and other owner blobs when both language files use Git's default text strategy and merge cleanly. It fails closed on owner conflicts, non-text merge configuration, or invalid records; after an already-stopped merge, run `uv run hdsh pairing merge --resolve`, which stages every safe pairing record and exits unsuccessfully if other pairing conflicts still need manual work. See the [bilingual documentation contract](i18n/README.md#the-pairing-contract) for the exact files and states the driver accepts.

When the driver's runtime is unavailable, the shell launcher degrades to a plain text merge with exit 1, so Git keeps the index stages unresolved; restore the environment and run `hdsh pairing merge --resolve`, or run `git merge --abort`.

prek hooks are configured in [prek.toml](../prek.toml) as fast local checkpoints:

- `pre-commit` verifies staged pairing records against the staged owner bytes, and the other staged checks the configuration lists.
- The hooks intentionally do not run tests, type checks, or the corpus-wide pairing check. Contributors run the [checks relevant to the changed behavior](../AGENTS.md#run-relevant-checks-locally) once; CI owns the exhaustive matrix.

### CI gates

The keyless [CI workflow](../.github/workflows/ci.yml) runs the test suite with the coverage gate, lint, both type checkers, and every documentation gate over the whole tree. Issue and pull-request policy runs in its own workflows against the configured GitHub Projects. See the workflow files for the current job inventory.

### Daily commands

The root [contributor instructions](../AGENTS.md#commands) summarize common commands; `uv run hdsh --help` and `uv run hdsh <domain> --help` expose the full command tree with progressive help at every level. Select the smallest checks that cover the changed surface. Documentation changes re-record the edited pairs; package-public behavior changes also update the owning document.

### TODO markers

Use one of three comment tags to flag known issues in the code, ordered by urgency — `FIXME` blocks a release, `TODO` is due soon, `XXX` is someday-maybe.
