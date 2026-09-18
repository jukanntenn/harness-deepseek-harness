# RFC: A CLI entry for the pairing merge driver

Status: implemented

English | [中文](2026-09-17-pairing-merge-driver-cli-entry.zh.md)

## Problem

`hdsh worktree install` registered the pairing merge driver as `scripts/pairing-merge-driver.sh %O %A %B %P` — a path relative to the repository root that resolves only inside this repository. Run in any other repository, the installer wrote a driver pointing at a file that does not exist, and the first merge touching an `.i18n.yaml` record failed with git's merge-driver error instead of resolving or degrading. The wrapper's single responsibility — fail closed to an ordinary text conflict when the runtime is unavailable — was a few lines of shell around an `exec` of the Python resolver that already lives in the CLI. External adoption of the pairing contract therefore blocked on a repository-relative script that cannot travel with the package.

## Decision

### The driver is a command leaf

`hdsh pairing merge-driver` takes the four `%O %A %B %P` arguments and carries the wrapper's semantics in Python: when the repository-aware resolver can run, it resolves exactly as the previous four-path form of `hdsh pairing merge` did; when it cannot, the command writes an ordinary text conflict through `git merge-file` with the record path as the conflict labels, prints the recovery pointer (`hdsh pairing merge --resolve` after the environment is restored, or `git merge --abort`), and exits non-zero so Git keeps the index stages unresolved. `scripts/pairing-merge-driver.sh` is deleted, `hdsh pairing merge` keeps only `--probe` and `--resolve`, and the [bilingual pairing gate RFC](../process/2026-09-07-bilingual-pairing-gate.md) plus the domain-map RFC were updated in the same change.

### The registered command and its precondition

The installer writes `uv run --no-sync hdsh pairing merge-driver %O %A %B %P`: Git invokes merge drivers with the repository root as the working directory — the same assumption the relative script path made — so the project environment resolves from that directory. The existing probe (`hdsh pairing merge --probe`) is unchanged. A clean precondition replaces the wrapper's degraded path: the driver works exactly when hdsh is installed and the environment is synced; when the precondition fails, the driver command itself fails and Git stops the merge with a driver error, and `--resolve` recovers once the environment is restored — the same recovery the shell wrapper's message pointed to.

### One-generation migration of the registered string

Worktrees registered with the previous script path keep working until they upgrade. The installer recognizes its own superseded driver string and rewrites it in place, while still refusing genuinely foreign `merge.hdsh-pairing.*` values as before; the registration changelist now records previous values, so a failed installation rolls a migration back to the legacy string rather than unsetting it. No consumer edits git config by hand to upgrade.

### The contract note that travels with the decision

Without a `.gitattributes` line declaring `merge=hdsh-pairing`, the driver never runs and records merge as plain text: non-adjacent per-line changes combine cleanly but without the structural verification, and same-entry changes conflict as ordinary text. The pairing gate remains the fail-loud backstop in every case — stale hashes and structurally divergent pairs go red at commit and in CI. The driver buys merge-time verification and earlier, more precise failures; record correctness never depended on it. [docs/i18n/README.md](../../../../docs/i18n/README.md) carries this paragraph.

## Verification

`tests/pairing/test_merge.py` drives the registered command under real `git merge`: composition and commit through a working runtime, link targets added by the merged branch, the degraded ordinary text conflict (markers and a clean-but-unverified record) when composition fails structurally, recovery through `--resolve`, the pre-merge-commit rejection path, and the mixed merge that resolves safe pairs while aggregating owner conflicts; the unit-level cases pin the fallback's conflict labels, the hard-failure diagnostics for unreadable paths and missing git, and the usage split between `merge` and `merge-driver`. `tests/worktree/` pins the fresh registration, the legacy-string migration, its rollback to the legacy value on a failed installation, and the continued refusal of foreign driver values.

## Alternatives considered

**A generated shim in the owned hooks directory.** Keeps a shell wrapper working without a project environment, at the cost of a second artifact to own, roll back, and upgrade — and the wrapper still execs the same Python resolver whenever it runs, so nothing is actually decoupled.

**A bare `hdsh` driver string.** Decouples merge-time behavior from the project environment but requires a PATH-installed hdsh (`uv tool install`), a second installation topology to document, probe, and keep in sync with the pairing workflow's documented home in the project environment.

**Package-data script referenced from site-packages.** Environment rebuilds and multiple coexisting environments make the absolute path unstable; a driver pointing into one virtualenv breaks exactly when environments are most in flux.

**Keep the script and document copying it.** Copy-distribution is the drift problem this change removes, and every consumer's installer would write a broken path until the copy exists.

## Consequences

- The registered driver string travels with the package: any repository running `hdsh worktree install` gets a working driver, and upgrades migrate the string mechanically.
- Merges in an unsynced environment stop with a driver error instead of pre-written conflict markers — accepted in exchange for the clean precondition; recovery through `--resolve` is unchanged, and the development guide keeps recommending `uv sync` first.
- `uv run --no-sync` as the driver command ties merge-time behavior to the project environment; a tool-installed hdsh without a synced environment takes the driver-error path.
- The migration window knows exactly one superseded string; older or hand-edited values refuse with guidance rather than guessing.
