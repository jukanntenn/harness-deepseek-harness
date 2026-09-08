# AGENTS.md

HDSH packages governance gates for the Python ecosystem: GitHub issue/PR policy, bilingual documentation pairing, and pull-request workflow tooling. External projects consume the gates through prek by pointing at [.pre-commit-hooks.yaml](.pre-commit-hooks.yaml); this repository uses the same hooks it ships. Runtime code lives in `src/hdsh/` with tests mirroring it in `tests/`; [README.md](README.md) introduces the product surface. Read [docs/architecture.md](docs/architecture.md) before changing `src/hdsh/`; follow [docs/AGENTS.md](docs/AGENTS.md) for documentation.

## Commands

```sh
uv sync                                          # create the environment from uv.lock
uv run pytest                                    # tests; 100% branch coverage enforced
uv run ruff check .                              # lint (ALL rules minus documented conflicts)
uv run ruff format .                             # format
uv run basedpyright                              # primary type check (typeCheckingMode all)
uv run ty check                                  # secondary type check
uv run hdsh pairing verify            # bilingual pairing gate over the corpus
uv run hdsh pairing list              # pairing state per document; never fails
uv run hdsh pairing record <pair>     # re-record one confirmed pair
uv run hdsh pairing brief            # minimal-update briefing for out-of-sync pairs
uv run hdsh rfc verify                # RFC format gate
uv run hdsh rfc archive               # frozen RFC archive gate
uv run hdsh rfc seal                  # append seals for newly archived triplets
uv run hdsh docs wrap                 # one physical line per prose paragraph
uv run hdsh docs links                # relative links and #fragment anchors resolve
uv run hdsh docs budgets              # standing-doc word ceilings (--list reports usage)
uv run hdsh scope --base <ref>        # committed + worktree scope of a change
uv run hdsh worktree install          # worktree-local prek hooks and merge driver
uv run prek run --all-files                      # every hook over the whole tree
```

### Host sandbox failures

If a required `git`, `uv`, build, test, or gate command fails because the sandbox blocks credentials, network, IPC, watching, or nested sandboxing, retry unchanged with the narrowest host escalation. Require sandbox evidence; never bypass test failures or the gates themselves.

### Run relevant checks locally

Run checks before pushes via [pushing](.agents/skills/pushing/SKILL.md); report only commands run. After `gh stack sync`, validate immediately; do not merge before checks pass.

- Match evidence to the surface: focused pytest tests for behavior, the pairing gate for documentation pairs, the RFC format gate for RFCs, basedpyright for type surfaces.
- Never default to the full suite or repeat a passing check for commit or push. CI owns exhaustive coverage and the platform matrix; rehearse all locally only by explicit request, for CI diagnosis, or for an irreducibly repository-wide change.
- The coverage gate is pytest itself: `fail_under=100` sits in `pyproject.toml`, so every `uv run pytest` run enforces it.

## Secrets

Tests never need real credentials; no live API is reachable from this repository. Never commit credentials or environment files.

## Conventions

- Python >= 3.12, src layout: runtime code in `src/hdsh/`, tests in `tests/` mirroring it.
- English is the working language for code, commits, and reviews; in-scope documents are English + Simplified Chinese pairs under the [pairing contract](docs/i18n/README.md).
- **Prefer maintained dependencies over hand-rolling** when they genuinely delete owned code and tests.
- **Explicit > implicit at boundaries**: defaulting is an explicit resolution step in the owning implementation, never a hidden `or default` inside `run()`.
- **No hardcoded tunables in gates**: deployment-varying choices are validated config fields changeable by the consuming repository; a `DEFAULT_*` constant or test hook is not configurability. Protocol constants, external specs, and security invariants stay fixed.
- **Misconfiguration fails loud** at load when self-contained, otherwise at the earliest resolvable point; never silently skip a missing referent.
- **Opaque cross-boundary ids are typed** (`NewType`), never bare `str`.
- **Trust types at same-process boundaries.** Do not add runtime validation, fallback behavior, or hostile-input tests solely for values the static interface requires; validate at config, parser, subprocess, file, and wire boundaries.
- **An empty `except` names what it swallows** and why nothing else can reach it; keep the `try` to one statement.
- **Keep comments local.** Do not restate code, explain distant behavior unless locally required, or expand unrelated comments.
- **Prefer symmetry for parallel values**; unexplained asymmetry usually signals a missed extraction.
- **Tests describe behavior, not correctness.** Change obsolete behavior with its tests; explain why in the PR.
- **Non-trivial changes MUST include an RFC** in `.agents/rfcs/` in the same PR ([rules](.agents/rfcs/README.md)); only mechanical, local edits are exempt.
- **Labels:** one PR `kind/*`, all material `area/*`, a classified Issue — native Type on organization accounts, `type/*` label on user accounts; `source/*` is Issue-only ([policy](src/hdsh/policy/)).
- **Choose PR history deliberately.** Split independent changes and fix the introducing PR before propagation; follow the workflows in [.agents/skills/](.agents/skills/) for stacked branches, `--force-with-lease` pushes, and checkpoint handling.
- **Wire mechanically checkable invariants into an executed top-level gate** and prove each changed acceptance path rejects an invalid case.
- TODO markers: `FIXME`/`TODO`/`XXX` by urgency ([semantics](docs/development.md)).
- Files end with exactly one trailing newline.
- **Strictest tool defaults** — ruff `ALL`, basedpyright `all`, coverage 100; every relaxation requires an accepted RFC in `.agents/rfcs/` first.
