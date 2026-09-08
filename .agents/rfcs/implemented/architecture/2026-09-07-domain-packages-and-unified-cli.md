# RFC: Domain packages and the unified hdsh CLI

Status: implemented

English | [中文](2026-09-07-domain-packages-and-unified-cli.zh.md)

## Problem

A gate package with six domains needs one name per concept across three layers: the directory, the CLI domain, and the prek hook-id prefix. Flat per-gate scripts and mixed naming styles leave the public surface unrecognizable, tests that do not mirror the source by domain bloat to close coverage rather than describe behavior, and every new gate multiplies that ambiguity.

## Decision

`src/hdsh/` is organized by domain, and one name identifies one concept across three layers: the directory, the CLI domain, and the prek hook-id prefix.

- The domain packages are `pairing/`, `docs/`, `rfc/`, `scope.py`, `policy/`, and `worktree/`; inside them modules split by concept — `pairing/{manifest,corpus,records,links,structure,git,verify,merge}`, `policy/{config,rules,client,commands}`, `worktree/{git,ownership,config,install}`, `docs/{config,corpus,markdown,wrap,links,budgets}`.
- Exactly one console script remains — `hdsh` (`hdsh.cli:main`, plus `python -m hdsh`); `cli.py` owns the two-level argparse subcommand tree `hdsh <domain> <command>` with progressive `--help` at every level, each domain package registers its own command-leaf parsers and keeps its semantic validation and messages (for example pairing's explicit-bulk-record rule), syntax errors surface as `ValueError` and handled help as a signal through `hdsh.cliargs`, handlers return integer exit codes, and `SystemExit` appears only at the process entry and the git-boundary helpers.
- Hook ids follow the same rule: `hdsh-pairing-verify`, `hdsh-rfc-verify`, `hdsh-scope` (manual stage), `hdsh-docs-wrap`, `hdsh-docs-links`, `hdsh-docs-budgets`; manifest entries invoke the subcommands (`entry: hdsh pairing verify`), keeping upstream pre-commit compatibility.
- Gate configuration files mirror the domains — `.hdsh/pairing.manifest.json` and `.hdsh/docs.manifest.json` — and the merge driver is `merge.hdsh-pairing` backed by `scripts/pairing-merge-driver.sh`; the worktree installer registers both.
- Tests mirror the source tree per domain with package markers and shared helpers in `tests/helpers.py`; `src/hdsh/py.typed` marks the wheel as typed (PEP 561).

## Alternatives considered

**A `gates/` umbrella directory.** Whether something is a prek hook is a property of the root manifest, not of source code; `policy` and `scope` are public but not automatic hooks, so the split leaked on its first real case and duplicated the package-level word "gates".

**A separate hooks mirror repository (the ruff-pre-commit pattern).** Its motivation is a compiled binary with an independent release cadence; these gates are pure Python shipped from the same package, so a mirror only adds a version-alignment surface.

**Per-gate console scripts.** Multiple entries give one concept several names, and each entry needs its own usage grammar; before external consumers exist, a single entry point with domain subcommands is strictly simpler.

**Declaring every domain's flags in one shared parser.** Domains carry deliberate usage grammars and diagnostics; a single shared flag surface would either duplicate validation or weaken it, so syntax lives in per-command leaf parsers that each domain registers itself.

**A hand-written name-table dispatcher with per-domain argv parsing.** Two parsing mechanisms would enforce one contract twice: abbreviated flags accepted by one command and rejected by the others, a flag missing its value reported as an unknown argument, and a hand-maintained usage table duplicating every command's flag grammar; one argparse tree gives each level progressive `--help` and the exit-code contract a single owner.

## Consequences

- Consumers write `entry: hdsh pairing verify`-style hooks against the same repository; hook ids, command names, configuration file names, and the merge-driver key share one domain vocabulary, with no compatibility shims.
- The exit-code contract is uniform — 0 green, 1 violation, 2 usage — and the merge driver, resolver, and installer share the `hdsh pairing …` / `hdsh worktree install` surfaces.
- Branch coverage stays at 100 percent through per-domain behavior tests; when a branch could only be reached by monkeypatching an internal, the branch is removed rather than the test kept.
