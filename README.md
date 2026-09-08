# harness-deepseek-harness

English | [中文](README.zh.md)

Reusable governance gates for the Python ecosystem, wired through [prek](https://github.com/j178/prek): GitHub issue/PR policy, bilingual documentation pairing, documentation gates, and pull-request workflow tooling. External projects adopt the gates by pointing prek at this repository; this repository uses the same hooks it ships.

## What is here

- **Issue policy** (`.github/issue-management/`, `.github/workflows/issue-policy.yml`, `issue-lifecycle.yml`): Issue templates, a pull-request template, and a Python engine that validates Issue bodies, titles, labels, native Types, Project statuses, PR label taxonomy (exactly one `kind/*`, at least one `area/*`), same-repository Issue references, and Priority synchronization, and projects event-directed lifecycle transitions (`review_requested` → In review, `changes_requested` → In progress) onto the resolving Issues' Project status.
- **Bilingual documentation pairing** (`hdsh.pairing`): every in-scope document is an English/Chinese pair with a recorded-blob-hash consistency sidecar (`foo.i18n.yaml`), enforced by `hdsh-pairing-verify` and composed across merges by a fail-closed Git merge driver; `hdsh pairing brief` renders the minimal-update working set for the extended translation workflow. The contract lives in [docs/i18n/README.md](docs/i18n/README.md).
- **Documentation gates** (`hdsh.docs`): `hdsh-docs-wrap` keeps one physical line per prose paragraph, `hdsh-docs-links` proves relative links and `#fragment` anchors resolve, and `hdsh-docs-budgets` holds standing docs under `wc -w` ceilings; each reads its corpus from `.hdsh/docs.manifest.json`.
- **Pull-request workflow tooling**: `hdsh-scope` reports the explicit committed and worktree scope of an outgoing change; `hdsh worktree install` installs worktree-local prek hooks and the merge driver with refuse-to-clobber safety; `.agents/skills/` carries the pre-push, stacked-PR merge, code-review, and CI-reliability workflows; `.agents/rfcs/` holds the RFCs that own the *why*.

## Toolchain

[uv](https://github.com/astral-sh/uv) manages the project and lockfile; [ruff](https://github.com/astral-sh/ruff) (strictest rule set) formats and lints; [basedpyright](https://github.com/DetachHead/basedpyright) type-checks in `all` mode with [ty](https://github.com/astral-sh/ty) as the secondary checker; pytest with branch coverage requires 100%. Relaxations go through an accepted RFC first.

## Using the gates in another repository

```yaml
# .pre-commit-config.yaml (or prek.toml) in the consuming project
repos:
  - repo: https://github.com/jukanntenn/harness-deepseek-harness
    rev: v0.1.0
    hooks:
      - id: hdsh-pairing-verify
      - id: hdsh-rfc-verify
      - id: hdsh-docs-wrap
      - id: hdsh-docs-links
      - id: hdsh-docs-budgets
```

The pairing gate reads its corpus scope from `.hdsh/pairing.manifest.json` and the documentation gates read theirs from `.hdsh/docs.manifest.json` in the consuming repository; see [docs/i18n/README.md](docs/i18n/README.md) for the pairing contract and the manifest rules.

## Development

```sh
uv sync                     # create the environment
uv run prek install         # local git hooks (or: uv run hdsh worktree install for worktree-local)
uv run pytest               # tests with the 100% coverage gate
uv run ruff check .         # lint and format
uv run basedpyright         # type check
uv run hdsh pairing list   # bilingual pairing state
```

Every non-trivial change ships an RFC in `.agents/rfcs/` and keeps documentation pairs consistent; see [AGENTS.md](AGENTS.md) for the standing rules.
