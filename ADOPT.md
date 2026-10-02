# Adopting the harness

English | [中文](ADOPT.zh.md)

This is the consumer-side operating manual: it leads a repository — usually through its AI agent — from zero to the full harness. The mechanical half is `hdsh adopt`; this page carries the judgment half: the parameters, the out-of-git state, and what done means. Adopting means adopting the tree conventions: every README, the root ADOPT document, `docs/**`, and `.agents/rfcs/**` join the [bilingual pairing corpus](docs/i18n/README.md).

## Phase 1 — install

Host-install hdsh (until PyPI publishes: `uv tool install "harness-deepseek-harness @ git+<url>@<ref>"`), confirm the toolchain with `hdsh adopt preflight`, then review `hdsh adopt plan` before `hdsh adopt apply`. Both refuse loudly — one diagnostic per blocker:

Only the project number and title are hand-typed; the rest derive when absent (ref from the latest upstream tag, account type from the remote, actor from the gh identity, zone from the system), each derivation echoed, each flag an override, and a fully flagged run stays offline. Apply writes the prek gate entry with the `.gitattributes` driver line, the two thin policy workflows, the policy `config.json`, the issue and pull-request templates, the RFC mechanism, all ten skills, the documentation standard and the i18n contract, templated `architecture.md` and `development.md` pairs, and — when no root `AGENTS.md` exists — a templated standing-orders file. It records every installed bilingual pair and writes `.hdsh/adopt.manifest.json`.

## Phase 2 — the out-of-git checklist

Apply cannot see repository state on GitHub; the consumer's agent runs these and a human confirms the result:

- Create the label taxonomy: the `kind/*` set, the initial `area/*` labels, and `type/*` labels on user accounts (`gh label create <name> --description <...>`).
- Create the Project board with the configured statuses plus the `Priority` and start-date fields; its number is `--project-number`.
- Organization flavor: set `vars.HDSH_ISSUE_APP_CLIENT_ID` and `secrets.HDSH_ISSUE_APP_PRIVATE_KEY` for a GitHub App with Issues and organization Projects access. User flavor: set `secrets.HDSH_ISSUE_PROJECT_TOKEN` (classic PAT, `project` scope) held by the lifecycle account.
- Require one approval before merge.

## Phase 3 — complete the judgment half

Pair the repository's own README (translate the counterpart, then `hdsh pairing record README.md`), fill every `TODO(adopt):` placeholder, and merge the harness pointers into a pre-existing root `AGENTS.md` when one was skipped. `hdsh adopt verify` reports the remaining placeholders and any drift against the adopt manifest; done means verify green and every documentation gate green.

## Phase 4 — the local workflow layer

hdsh is host-installed (Phase 1); run `hdsh worktree install` per worktree for the hooks and the merge driver, which resolve it from PATH. The managed hooks carry the `hdsh` group; a `--group`-filtered CI must include it or every gate silently drops out. Older actionlint misreports the `field_added`/`field_removed` triggers; bridge with `paths.ignore` until known. Upgrades rerun `hdsh adopt apply` under the newer ref. Generated files are upstream-owned: redirect local changes upstream instead of forking them.
