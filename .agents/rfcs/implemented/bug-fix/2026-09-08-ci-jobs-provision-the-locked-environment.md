# RFC: CI gate jobs provision the locked environment before running tools

Status: implemented

English | [中文](2026-09-08-ci-jobs-provision-the-locked-environment.zh.md)

## Problem

Every `uv`-based CI job invoked its gates through `uv run --no-sync <tool>` on a fresh runner, where nothing had ever created the project environment. uv materialized an empty `.venv`, the spawn of `ruff`, `basedpyright`, `ty`, or `hdsh` failed with `Failed to spawn: ... No such file or directory`, and three of the five jobs failed on the repository's first push to `main` (run 34213766320). The coverage job passed only because `uv run pytest` auto-syncs implicitly, and the hook-manifest job passed because it never touches uv. The `--no-sync` pattern was borrowed from the local prek hooks, where the worktree's uv-managed environment is a standing precondition of development; a CI runner has no such precondition, so the flag silently assumed an environment nobody had built.

## Decision

Each `uv`-based CI job now runs an explicit `uv sync` step — locked, because `UV_LOCKED=1` is the workflow-wide environment — before its gate steps, and every tool invocation keeps `--no-sync`, including the coverage job's pytest, which previously relied on uv's implicit auto-sync. The four jobs share one shape: checkout, install uv, sync the locked environment, run gates.

## Verification

The first CI run on `main` is the failure evidence: lint, typecheck, and documentation-gate jobs died at `Failed to spawn` while the coverage job's implicit sync proved the locked environment installs cleanly on the runner. The push carrying this change runs all five jobs on `main`, and their green result is the acceptance evidence.

## Alternatives considered

**Dropping `--no-sync` and relying on `uv run` auto-sync.** The implicit default is exactly what the explicit-over-implicit boundary rule forbids: provisioning would hide inside every run invocation instead of appearing once as the job's resolution step. The uniform sync step also acts as a loud lock check — a `pyproject.toml`/`uv.lock` mismatch fails there, at the top of the job.

**A composite action wrapping checkout, uv, and sync.** Four jobs would hide four visible lines behind indirection for no behavior change; the repeated step keeps every job legible and parallel.

**Caching `.venv` keyed on the lockfile.** Provisioning would depend on cache-restore correctness, and stale-key staleness risks checking against an environment that no longer matches the lock. The uv download cache already makes a fresh sync fast; the coverage job's whole run, sync included, took 37 seconds.

## Consequences

- CI executes gate command strings copy-identical to the local prek hooks, in an environment provisioned exactly from `uv.lock`; environment drift between local and CI can no longer hide behind an implicit sync.
- A `pyproject.toml`/`uv.lock` mismatch fails the sync step at the top of every affected job, instead of surfacing as a confusing missing-executable error deep in a gate.
- Each job pays one provisioning step; the uv download cache keeps its cost to seconds, as the coverage job already demonstrated.
