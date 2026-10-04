# Adopting the harness

English | [中文](ADOPT.zh.md)

This is the consumer-side operating manual: it leads a repository — usually through its AI agent — from zero to the full harness. The mechanical half is `hdsh adopt`; this page carries the judgment half: the parameters, the out-of-git state, and what done means. Adopting means adopting the tree conventions: every README, the root ADOPT document, `docs/**`, and `.agents/rfcs/**` join the [bilingual pairing corpus](docs/i18n/README.md).

## Phase 1 — the out-of-git checklist

Adoption starts on GitHub, before anything lands in the tree: `hdsh adopt plan` and `apply` both require `--project-number`, and the board behind it is created here. Apply cannot see repository state on GitHub; the consumer's agent runs these and a human confirms the result:

- Create the label taxonomy: the `kind/*` set, the initial `area/*` labels, and `type/*` labels on user accounts (`gh label create <name> --description <...>`).
- Create the Project board with the configured statuses plus the `Priority` and start-date fields; its number is `--project-number`.
- Organization flavor: set `vars.HDSH_ISSUE_APP_CLIENT_ID` and `secrets.HDSH_ISSUE_APP_PRIVATE_KEY` for a GitHub App with Issues and organization Projects access. User flavor: set `secrets.HDSH_ISSUE_PROJECT_TOKEN` (classic PAT, `project` scope) held by the lifecycle account.
- Require one approval before merge.

## Phase 2 — install

Host-install hdsh (until PyPI publishes: `uv tool install "harness-deepseek-harness @ git+<url>@<ref>"`), confirm the toolchain with `hdsh adopt preflight` (git, authenticated gh, bare `hdsh --version`, and `rg --version` — the skills assume ripgrep), then review `hdsh adopt plan` before `hdsh adopt apply`, both carrying the Phase 1 number. Both refuse loudly — one diagnostic per blocker:

Only the project number and title are hand-typed; the rest derive when absent (ref from the latest upstream tag, account type from the remote, actor from the gh identity, zone from the system — the zone also dates the adoption RFC), each derivation echoed, each flag an override, and a fully flagged run stays offline. Apply writes the prek gate entry with the `.gitattributes` driver line, the two thin policy workflows, the policy `config.json`, the issue and pull-request templates, the RFC mechanism, all nine skills (five mirrored, four slot-guided), the documentation standard and the i18n contract, the actionlint bridge file, templated `architecture.md` and `development.md` pairs, and — when no root `AGENTS.md` exists — a templated standing-orders file. It records every bilingual pair it installed — a pre-existing `architecture.md` or `development.md` is left untouched with no counterpart template and no record — prints the discovered pairing-corpus size plus the wrap-reflow cost of the pre-existing corpus, and writes `.hdsh/adopt.manifest.json`.

## Phase 3 — complete the judgment half

Pair the whole corpus, not one README: every README pair at any depth is auto-discovered, `docs/**` and `.agents/rfcs/**` join by prefix, and manifest `roots` pull further subtrees in — `hdsh pairing list` enumerates every pair; translate each counterpart, then `hdsh pairing record <anchor>`. A Chinese-first document flips first: `git mv docs/foo.md docs/foo.zh.md` makes the existing bytes the Chinese side, then translate the English `docs/foo.md`. Fill every `TODO(adopt):` placeholder; inside `<!-- hdsh:slot ... -->` markers the value is consumer-owned — fill it but keep the marker lines; the next apply uses them to preserve filled values. Merge the harness pointers into a pre-existing root `AGENTS.md` when one was skipped. `hdsh adopt verify` reports remaining placeholders and drift — including a CI that runs no hdsh gate, `prek run --group` filters missing the `hdsh` group, and transplanted files still carrying `uv run hdsh`; done means verify green and every documentation gate green.

## Phase 4 — the local workflow layer

hdsh is host-installed (Phase 2); run `hdsh worktree install` per worktree for the hooks and the merge driver, which resolve it from PATH. The managed hooks carry the `hdsh` group; every `--group`-filtered `prek run` in CI must include `--group hdsh` or the gates silently drop out — verify rejects the omission. A CI that runs no prek wires the gates itself — `prek run --all-files`, or a pinned hdsh install plus the managed gate commands — and verify rejects a gate-less CI just the same. Apply writes the `.github/actionlint.yaml` bridge (per-file, per-message-regex schema) for the `field_added`/`field_removed` triggers older actionlint misreports; the file links the documented activity types and carries its removal condition. Upgrades rerun `hdsh adopt apply` under the newer ref. Generated files are upstream-owned: redirect local changes upstream instead of forking them.

## Retiring a pre-existing documentation standard

hdsh is opinionated: adopt does not run a dual standard beside a repository's own gates. Retire pre-existing wrap checks, word budgets, pairing corpora, and decision-record trees in the same adoption: move decision records into `.agents/rfcs/` as complete triplets, fold word ceilings into [.hdsh/docs.manifest.json](.hdsh/docs.manifest.json) and corpus subtrees into [.hdsh/pairing.manifest.json](.hdsh/pairing.manifest.json) roots, delete the local gate scripts, and record the retirement in one implemented RFC. A legacy `.pre-commit-config.yaml` blocks apply until migrated to `prek.toml`; a local wrap gate that parses the slot-marker comments as prose will fight the transplanted skills — retire it rather than patch it. The wrap rule then covers the whole adopted corpus, not just the files hdsh installs: a pre-existing library that hard-wraps prose reflows once to one physical line per paragraph — `hdsh adopt plan` counts those paragraphs up front, so the reflow lands as one budgeted mechanical commit instead of a wall of red after apply.
