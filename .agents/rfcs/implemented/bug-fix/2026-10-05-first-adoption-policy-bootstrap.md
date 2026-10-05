# RFC: Let the policy gates skip only the pull request that introduces the config

Status: implemented

English | [中文](2026-10-05-first-adoption-policy-bootstrap.zh.md)

## Problem

Both policy workflows check out the repository's default branch and read `.github/issue-management/config.json` there — the anti-tamper design that keeps a pull request from editing its own validator, recorded in [the GitHub workflow RFC](../process/2026-09-07-github-workflow.md). The first adoption pull request therefore ran its own validators against a default branch that carried no config: every run of both workflows failed with a missing-file error until the pull request merged, forcing the maintainer to merge red — the bootstrap paradox the fourth adopter reported. Nothing documented the expected red, so on arrival it read as a defect in the gates the pull request was adopting.

## Decision

- The flavor-resolution step treats a config absent from the default-branch checkout as exactly one of two cases. When the event's pull request adds or modifies the config path — checked against the REST pull-request files listing, following pagination — the run emits a `::notice` and a `skip=true` step output that gates the credential-minting and validation steps: there is no policy to validate against until that pull request merges, and the one pull request whose own copy is never read is the one run that cannot tamper with the validator by this route.
- Every other absence fails loud as drift: an issue event on a repository without a config, an unrelated pull request, a config deleted after adoption. The loud branch is also the de-adoption detector — a repository whose policy config disappeared stays red instead of quietly passing.
- The introduction check runs inside the composite actions' flavor scripts, so consumers upgrade by moving one `uses:` ref; the thin workflow templates consumers install needed no change, and this repository's own two inline workflows carry the same branch. An unreachable or unreadable files API fails loud rather than guessing the pull request's content.
- The adoption manual states the behavior: the adoption pull request is a known bootstrap moment, and no red-first merge is required.

## Verification

Hermetic script tests drive both flavor scripts against a local paginated files API: the introducing pull request skips with the notice and the `skip=true` output; an unrelated pull request, an event without pull-request context, a missing token mapping, and a failing API each remain loud failures; flavor resolution for an existing config is unchanged. actionlint passes over the changed workflows and actions.

## Alternatives considered

**Downgrade every missing config to a warning.** Rejected: after a pull request deletes the config merges, the workflows would skip forever — a silently de-adopted repository with green checks. Only the pull request that introduces the config may skip.

**Read the config from the pull request head.** Rejected: it reopens the self-validation hole the default-branch checkout exists to close.

**Document the red and merge red-first.** Rejected as the whole fix: it works once, but every future consumer's first experience of the gates is a false failure the maintainer must knowingly override, and the manual would have to teach that override forever.

## Consequences

What the change bought: the adoption pull request lands green with an explanatory notice instead of two guaranteed failures, and the precise skip condition keeps the anti-tamper property — the validator still reads only trusted default-branch state — while making silent de-adoption loud.

What it cost: the flavor step performs one authenticated API read on the bootstrap path only, and its failure is loud; consumers on older action refs keep the old behavior until they rerun `hdsh adopt apply` under a newer ref, which is the standing upgrade path.
