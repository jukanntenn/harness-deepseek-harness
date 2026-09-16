# Adopting the harness

English | [中文](ADOPT.zh.md)

This is the consumer-side operating manual: it leads a repository — usually through its AI agent — from zero to the full harness. The mechanical half is `hdsh adopt`; this page carries the judgment half: the parameters, the out-of-git state, and what done means. Adopting means adopting the tree conventions: every README, the root ADOPT document, `docs/**`, and `.agents/rfcs/**` join the [bilingual pairing corpus](docs/i18n/README.md).

## Phase 1 — install

Run `hdsh adopt plan` with the parameters below, review the printed plan, then `hdsh adopt apply`. Both commands refuse loudly — one diagnostic per blocker — instead of guessing. Bootstrap hdsh itself from a pinned ref:

```sh
uvx --from "harness-deepseek-harness @ git+https://github.com/jukanntenn/harness-deepseek-harness@<ref>" \
  hdsh adopt plan <parameters>
```

The parameters are `--hdsh-ref` (tag or full SHA; it pins every reference), `--account-type user|organization`, `--project-number`, `--project-title`, `--lifecycle-actor`, and `--time-zone`; the Project field names carry defaults. Apply writes the prek gate entry with the `.gitattributes` driver line, the two thin policy workflows, the policy `config.json`, the issue and pull-request templates, the RFC mechanism, all ten skills, the documentation standard and the i18n contract, templated `architecture.md` and `development.md` pairs, and — when no root `AGENTS.md` exists — a templated standing-orders file. It records every installed bilingual pair and writes `.hdsh/adopt.manifest.json`.

## Phase 2 — the out-of-git checklist

Apply cannot see repository state on GitHub; the consumer's agent runs these and a human confirms the result:

- Create the label taxonomy: the `kind/*` set, the initial `area/*` labels, and `type/*` labels on user accounts (`gh label create <name> --description <...>`).
- Create the Project board with the configured statuses plus the `Priority` and start-date fields; its number is `--project-number`.
- Organization flavor: set `vars.HDSH_ISSUE_APP_CLIENT_ID` and `secrets.HDSH_ISSUE_APP_PRIVATE_KEY` for a GitHub App with Issues and organization Projects access. User flavor: set `secrets.HDSH_ISSUE_PROJECT_TOKEN` (classic PAT, `project` scope) held by the lifecycle account.
- Require one approval before merge.

## Phase 3 — complete the judgment half

Pair the repository's own README (translate the counterpart, then `hdsh pairing record README.md`), fill every `TODO(adopt):` placeholder, and merge the harness pointers into a pre-existing root `AGENTS.md` when one was skipped. `hdsh adopt verify` reports the remaining placeholders and any drift against the adopt manifest; done means verify green and every documentation gate green.

## Phase 4 — the local workflow layer

Add hdsh to the project (`uv add "harness-deepseek-harness @ git+https://github.com/jukanntenn/harness-deepseek-harness@<ref>"` until PyPI publishes), then run `uv run hdsh worktree install` in each worktree for the prek hooks and the pairing merge driver. Upgrades rerun `hdsh adopt apply` under the newer ref. Generated files are upstream-owned: redirect local changes upstream instead of forking them.
