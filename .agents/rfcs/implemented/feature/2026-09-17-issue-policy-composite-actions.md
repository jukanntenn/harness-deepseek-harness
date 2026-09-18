# RFC: Distribute the issue policy workflows as composite actions

Status: implemented

English | [中文](2026-09-17-issue-policy-composite-actions.zh.md)

## Problem

The policy engine ships with the package: `hdsh policy pr` and `hdsh policy lifecycle` are plain CLI commands installable anywhere. The workflow glue was not distributable. Flavor resolution, credential validation, the trusted default-branch checkout, engine provisioning, and the pinned third-party action SHAs lived only in this repository's own `issue-policy.yml` (78 lines) and `issue-lifecycle.yml` (107 lines). A consuming repository that wanted the same Issue/PR governance had to copy those files wholesale; copies drift from upstream, and every upstream improvement required a manual re-diff per consumer. The adoption story stopped at the hook manifest: prek distributed the gates, nothing distributed the workflows.

## Decision

### Two composite actions own the glue

`issue-policy` and `issue-lifecycle` are composite actions under `.github/actions/<name>/action.yml`, the location GitHub's own tutorial recommends for repository actions. Each action carries everything the previous workflow files carried: flavor resolution from the consumer's checked-in policy config, per-flavor credential validation, GitHub App token minting through a nested `uses:` of `actions/create-github-app-token` at a pinned SHA, the trusted checkout, engine provisioning, and the CLI invocation. GitHub event triggers cannot subscribe across repositories, so a consumer workflow file always remains — but it shrinks to the trigger set, a minimal `permissions` block, and one `uses:` line with credential inputs. This supersedes the glue placement decided by the [github-workflow RFC](../process/2026-09-07-github-workflow.md), which was updated in the same change; its invariant survives — policy logic stays in the engine, workflow files only subscribe and invoke. The flavor logic lives in a `scripts/flavor.py` inside each action directory, byte-identical in both, so the CI rehearsal can execute it directly.

### Credentials enter as inputs; the action never touches secrets

The platform forbids the `secrets` context inside composite actions, so the caller maps secrets to role-named inputs: `github-token` (defaulting to `${{ github.token }}`, evaluated caller-side), `project-token`, `app-client-id`, `app-private-key`. The action validates input completeness against the config's `accountType` and fails loud per flavor — the same credential matrix the previous workflow shells enforced. App tokens are minted inside the action, so organization and user flavors both cost the caller a single step, matching the [identity model](../feature/2026-09-08-user-account-issue-policy.md). This repository's secret family aligns with the workflow flip that adopts the actions: `HDSH_PROJECT_PAT` becomes `HDSH_ISSUE_PROJECT_TOKEN`, joining `HDSH_ISSUE_APP_CLIENT_ID` and `HDSH_ISSUE_APP_PRIVATE_KEY` — one prefix, role-based names that state what the credential reaches rather than how it was minted.

### The policy configuration stays a checked-in file

`config.json` remains the single policy home; the action receives only a `config-path` input defaulting to `.github/issue-management/config.json`. Policy semantics do not move into action inputs or repository variables: the `pull_request` event runs the workflow file from the PR's merge ref, so input values embedded in that file are PR-controlled, and a pull request could relax the policy that validates it; repository variables mutate without review. Complex, review-governed configuration belongs in repository files — the release-please, semantic-release, and dependabot precedent. The engine cross-validates the config's `owner`, `repository`, and `accountType` against the event payload's repository context (`hdsh.policy.commands.validate_context`) and fails loud on mismatch, catching renamed repositories and copy-pasted configs before any API call.

### Trusted sources: default-branch config, pinned engine

The action checks the consumer's config out of the default branch, never the PR head, preserving the anti-self-modification property. The engine comes from a required `hdsh-ref` input — a git ref (tag or full SHA) — provisioned as `uv tool run --from "harness-deepseek-harness @ git+<clone-url>@<hdsh-ref>"`; the clone URL comes from the event payload, so the same action serves any fork or mirror. A governance engine never floats on `latest`. Switching the provisioner to a PyPI pin (`==<version>`) is a deferred follow-up for the release that publishes the package.

### This repository self-hosts by full reference, never relative

This repository's own workflows call its actions the same way; the flip lands as the immediately following change, because the default branch must carry the actions before any caller can pin them. A relative `./.github/actions/...` reference would load the action from the PR's merge ref, letting a pull request modify its own validator. The default-branch reference keeps the previous trust semantics exactly: glue and engine come from reviewed default-branch state, and glue changes land only through review. Immutably pinning self-references to release tags is a stricter discipline this record deliberately does not adopt: it would freeze the validator between releases and add a pin-bump step to every release without changing what an attacker can reach.

## Verification

`tests/policy/` pins every cross-validation mismatch: missing repository context, missing owner context, repository, owner, and account-type contradictions, plus the CLI diagnostic path. The CI `action-rehearsal` job executes both actions' `flavor.py` against user and organization fixtures (happy path plus both loud-failure paths), runs the engine's exact CLI invocation against a config that contradicts its event payload; from the workflow-flip change on it also asserts that both self-hosting workflow references are fully qualified with no relative `uses:` anywhere. A rehearsal against a live consumer repository with real API traffic remains future work until a release tag exists.

## Alternatives considered

**Reusable workflows.** Thinner callers and native `secrets: inherit`, but callers remain full workflow files coupled to event subscriptions, the lifecycle workflow's step-level skip tuning (green checks instead of gray skipped segments on benign review events) crosses awkwardly into called-workflow job semantics, and upgrades would stop mirroring the prek `rev:` pin model consumers already follow.

**Generated workflows with a drift gate.** A command writes the full workflow files into consumers and a gate compares them against upstream. Copy semantics survive — every improvement forks every consumer until regeneration — and the solution grows a second moving part where the composite action has one.

**Policy configuration as action inputs or repository variables.** Rejected on trust: workflow files are read from the PR merge ref on `pull_request`, so a PR could relax the policy that validates it, and repository variables mutate without review; the file also remains the only surface the CLI reads outside Actions.

## Consequences

- Consumers upgrade the workflows by moving one `uses:` ref, mirroring the prek pin model; the credential surface stays explicit and minimal at four role-named inputs plus two paths.
- Composite actions cannot read `secrets` directly — every credential must surface as an input, so an incorrect caller mapping fails loud in the flavor step rather than silently authenticating as nothing.
- Self-hosting at the default branch means this repository validates main with main's glue — identical to the previous semantics, but a glue regression affects validation immediately on merge instead of at the next release boundary.
- The organization/user credential matrix doubles the action's test surface; the rehearsal job carries the local half, and the lifecycle action preserves its green-not-gray step gating under the new structure.
- Engine provisioning through git refs works before PyPI exists but re-resolves the repository per run; the PyPI pin switch is queued behind the first release.
