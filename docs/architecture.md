# harness-deepseek-harness architecture

English | [中文](architecture.zh.md)

Read this before changing anything under `src/hdsh/`. It is the ordered map of the package — domains, the unified CLI, and where new behavior goes; decision rationale lives in the linked RFCs.

## What this package is

hdsh ships governance gates for the Python ecosystem: GitHub Issue/PR policy, bilingual documentation pairing, documentation corpus gates, and pull-request workflow tooling. External projects consume the gates through prek by pointing at [`.pre-commit-hooks.yaml`](../.pre-commit-hooks.yaml); this repository uses the same hooks it ships. Everything below a domain boundary belongs to that domain; the root [AGENTS.md](../AGENTS.md) carries the standing conventions and the command inventory.

## Domain packages and the unified CLI

`src/hdsh/` is organized by domain, and one name identifies one concept across three layers: the directory, the CLI domain, and the prek hook-id prefix ([decision](../.agents/rfcs/implemented/architecture/2026-09-07-domain-packages-and-unified-cli.md)).

`hdsh.cli` owns the two-level argparse tree `hdsh <domain> <command>`: each domain package registers its own command-leaf parsers and keeps its semantic validation and messages, syntax errors surface as `ValueError` through `hdsh.cliargs`, handlers return integer exit codes, and the contract is uniform — 0 green, 1 violation, 2 usage. `scope` is the deliberate single-command exception: it registers its flags directly at the domain level because it has no subcommands.

Gate configuration mirrors the domains: pairing reads `.hdsh/pairing.manifest.json` (`excluded` array plus the optional `generated` array of English sources exempt from the English-side switcher), the documentation gates read `.hdsh/docs.manifest.json`, and both parsers fail loud on unsupported fields at load.

## Core packages

| Package | Owns | CLI surface |
|---|---|---|
| [`pairing/`](../src/hdsh/pairing/) | The bilingual pairing gate, records, merge driver, and briefing tool | `hdsh pairing verify/record/list/merge/brief` |
| [`docs/`](../src/hdsh/docs/) | Documentation corpus gates: wrap, links, budgets | `hdsh docs wrap/links/budgets` |
| [`rfc/`](../src/hdsh/rfc/) | RFC format gate and the frozen-archive gate | `hdsh rfc verify/archive/seal` |
| [`policy/`](../src/hdsh/policy/) | GitHub Issue/PR policy engine: rules, client, lifecycle commands | `hdsh policy` |
| [`worktree/`](../src/hdsh/worktree/) | Worktree-local prek hook and merge-driver installation | `hdsh worktree install` |
| [`scope.py`](../src/hdsh/scope.py) | Committed-plus-worktree scope report of an outgoing change | `hdsh scope` |

## Pairing

The pairing domain is the largest because it owns a durable contract, not just checks: `foo.md`, `foo.zh.md`, and the `foo.i18n.yaml` consistency record merge whole, and the record's blob hashes double as recovery pointers pinned under a content-addressed snapshot ref. The gate checks pair completeness, recorded hashes, language switchers (with the manifest-`generated` exemption), link locales, byte-identical generated regions, and the structural signature; `hdsh pairing merge` composes records fail-closed across Git merges; `hdsh pairing brief` renders the minimal-update working set for the extended translation workflow. The contract lives in [docs/i18n/README.md](i18n/README.md) and the decisions in its [RFC](../.agents/rfcs/implemented/process/2026-09-07-bilingual-pairing-gate.md) and the [briefed-updates RFC](../.agents/rfcs/implemented/process/2026-09-07-briefed-minimal-translation-updates.md).

## Documentation and RFC gates

The docs domain keeps the Markdown corpus mechanically tidy: one physical line per prose paragraph, relative links and `#fragment` anchors that resolve, and standing documents under `wc -w` ceilings — each configured through the docs manifest, with relocate-or-condense as the response to a red budget. The rfc domain owns the decision-record format: lifecycle folders, class folders, header block, and the body skeleton for each lifecycle, plus the sealed archive that frozen history lives in. Scope rules and manifests are owned by [docs/AGENTS.md](AGENTS.md), the pairing contract by [docs/i18n/README.md](i18n/README.md), and the RFC mechanism by [`.agents/rfcs/README.md`](../.agents/rfcs/README.md).

## Policy

The policy domain is the only one that talks to the GitHub API: `policy/rules.py` validates Issue bodies, titles, labels, native Types, and PR label taxonomy; `policy/client.py` separates repository reads from Project reads with distinct credentials; `policy/commands.py` drives the two workflow entry points (`pr`, `lifecycle`) from a validated config file and the event payload. The workflow glue lives in `.github/workflows/` and calls the CLI directly — no inline workflow Python ([decision](../.agents/rfcs/implemented/process/2026-09-07-github-workflow.md)).

## Worktree and scope

`worktree install` registers worktree-local prek hooks and the `hdsh-pairing` merge driver with refuse-to-clobber safety over paths it owns; `scope` reports the explicit committed and worktree scope of a change so pre-push check selection has a mechanical input. Both exist because contributors work in stacked worktrees, and per-worktree configuration is the only way hooks and drivers stay correct when several checkouts share one repository.

## Where new behavior goes

| Goal | Mechanism |
|---|---|
| Add a gate | new module in its domain package, a command leaf it registers, a hook-id entry in `.pre-commit-hooks.yaml`, and manifest keys when it needs configuration |
| Add a domain | new package, a `_COMMAND_DOMAINS` entry in `hdsh.cli`, and hook ids following the `hdsh-<domain>-<command>` prefix rule |
| Add gate configuration | a validated manifest field with load-time errors; never a `DEFAULT_*` constant or a test hook |
| Extend the pairing contract | update [docs/i18n/README.md](i18n/README.md) and the gate in the same change; the structural signature and its grammar stay in `pairing/structure.py` |
| Add a repository policy rule | extend `policy/rules.py` and pin it with tests over the closed label set; workflow files subscribe to events, they do not implement policy |
| Change an RFC rule | update `.agents/rfcs/README.md` and `rfc/format.py` together; the gate rejects other folders than the documented classes |
| Add reusable agent workflow | a skill under `.agents/skills/`; skills carry procedure, RFCs carry decisions |
| Record why something is the way it is | an RFC in `.agents/rfcs/` ([rules](../.agents/rfcs/README.md)); only mechanical, local edits are exempt |

The contributor entry points — setup, daily workflow, Git integrations, CI — are in [development.md](development.md).
