# Contributing to harness-deepseek-harness

English | [中文](CONTRIBUTING.zh.md)

Contributions are welcome — issues, code, documentation, and translations. This page is the entry: it carries the process skeleton and links the authoritative rules rather than restating them. By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

- Every change starts with an issue — including typo fixes. The pull request references it with `Fixes #NN` (resolves and auto-closes) or `Related to #NN` (links only); the Issue policy CI check enforces the reference and the label taxonomy once a pull request enters review.
- Non-trivial changes ship an RFC (decision record) in the same pull request; purely mechanical, local edits are exempt ([rules](../.agents/rfcs/README.md)).
- Bilingual pairs move together: editing either side of a pair updates the counterpart and re-records the pair in the same pull request ([contract](i18n/README.md)).

## Development environment

Python ≥ 3.12 and [uv](https://github.com/astral-sh/uv); `uv sync` creates the environment and `uv run hdsh worktree install` installs worktree-local hooks. The minimal command set:

```sh
uv run pytest               # tests with the 100% coverage gate
uv run ruff check .         # lint
uv run basedpyright         # type check
uv run hdsh pairing verify  # bilingual pairing gate
```

The full command inventory and the evidence-selection rules live in [AGENTS.md](../AGENTS.md): select the narrowest checks that cover your diff, and let CI own the exhaustive matrix.

## Pull requests

Open a draft early when useful and mark it ready once the checks pass. The body references the issue and carries the checklist from the pull-request template; the labels classify the change — exactly one `kind/*` and at least one `area/*`. Review requires one approval from a different account, merges are merge commits, and dependent chains land as native stacks ([merge skill](../.agents/skills/merging-stacked-prs/SKILL.md)). Commit titles follow Conventional Commits style — a convention here, not a gate.

## What we accept

Welcome without pre-discussion: gate improvements, documentation and translation updates, new checks with tests, and repository hygiene. Discuss first — in an issue or a [Discussion](https://github.com/jukanntenn/harness-deepseek-harness/discussions) — before changing the label taxonomy, relaxing any strict default, or reshaping a contract the gates enforce; relaxations require an accepted RFC first.

## AI-assisted contributions

You must be able to explain every line you submit, including code an AI assistant generated. Agents contributing to this repository follow [AGENTS.md](../AGENTS.md).

## Getting help

See [SUPPORT.md](SUPPORT.md) for where to ask, what makes a report actionable, and what is out of scope.
