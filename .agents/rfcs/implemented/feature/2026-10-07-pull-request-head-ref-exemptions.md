# RFC: Pull-request head-ref exemptions owned by the repository's config

Status: implemented

English | [中文](2026-10-07-pull-request-head-ref-exemptions.zh.md)

## Problem

The pull-request policy binds every non-draft human pull request to the reference, `kind/*`, and `area/*` rules. Whole classes of pull requests cannot satisfy the reference rule by construction: a release pull request rolls versions and changelogs with no same-repository Issue to resolve, so it fails `PR body must reference at least one same-repository Issue` on every run. The fifth adopter carries a local MRFC (2026-08-24) patching exactly this and reports that every release needs a maintainer override until upstream ships a mechanism. Hardcoding a `release/**` exemption upstream would be a deployment-varying choice baked into a gate — the tunable shape the repository's configuration conventions forbid.

## Decision

- `config.json` gains `pullRequestExemptHeadRefs`: a list of non-empty `fnmatch` globs over pull-request head ref names, validated at load — anything but a list of non-empty strings fails loud with the field named. Absent or empty means no exemption, which is the closed-set behavior every repository starts from; the field is consumer-owned configuration under the [configuration-ownership RFC](2026-10-01-consumer-configuration-ownership.md).
- The globs use `fnmatch` semantics compared case-sensitively, like ref names: `*` crosses `/`, so one `release/*` pattern covers nested release refs and `release/**` and `release/*` are equivalent.
- The pull-request snapshot carries the head ref, and `hdsh policy pr` checks the exemption before validation: a matching pull request prints one line naming the ref and exits green — the same shape as the existing not-yet-in-scope path for drafts and automation.
- The exemption is whole-policy: a matching pull request skips the reference, `kind/*`, and `area/*` rules together. Lifecycle flows are untouched — a release pull request without references transitions nothing anyway.

## Alternatives considered

**Hardcode a `release/**` exemption upstream.** Rejected: which heads are exempt is a per-repository choice; a gate constant would be exactly the hardcoded tunable the configuration rules exist to prevent.

**Exempt only the reference rule.** Rejected: it splits one applicability decision into two config surfaces, and release pull requests carry no `kind/*` or `area/*` either — no adopter has asked for the split.

**Exempt by a pull-request label.** Rejected: a label the pull-request author can add lets any author self-exempt; head refs are protectable by branch rules and carry the release identity already.

**Read the patterns from repository variables.** Rejected: `config.json` is the validated, event-cross-checked configuration home the workflows already read from trusted default-branch state; a second source would drift from it.

## Consequences

What the change bought: release-style pull requests land green with one explanatory line, the consuming repository owns its exemption list as reviewed configuration, and a repository without the field behaves exactly as before.

What it cost: one more validated config surface to carry, and a too-broad glob silently exempts every matching pull request — the exempt line in the run log is the visible trace, and the config file is reviewed like code.

## Verification

Unit tests pin the glob semantics (exact names, `/`-crossing stars, case sensitivity, empty patterns never matching), the load validation (absent defaults empty; a non-list, an empty-string entry, and a non-string entry each fail loud with the field named), and the client path (a matching head ref prints the exempt line and no `::error` annotations; the snapshot carries the head ref). The default configuration — no field — runs the unchanged policy, pinned by the existing pull-request suite.
