# RFC: Give consumers ownership of their configuration files

Status: proposed

English | [中文](2026-10-01-consumer-configuration-ownership.zh.md)

## Problem

Three installed files mix upstream-rendered bytes with per-repository values while the adopt manifest byte-pins them: `.hdsh/pairing.manifest.json` — whose `excluded`, `generated`, and `public_blob_root` fields are the documented consumer mechanisms — plus `.hdsh/docs.manifest.json` and `.github/issue-management/config.json`. The first consumer that exercised a documented mechanism, excluding `.zcode/README.md` from the corpus, landed in a permanent deadlock: adopt verify reported drift forever, and a later re-apply was refused by the clobber check, whose guidance — revert the local change, or redirect it upstream — is impossible for a repository-specific exclusion. The root cause is ownership, not pinning: the seed entries inside these files (the English-only exclusion set, the standard wrap and links globs) are corpus constants wearing configuration clothing, and byte pinning protects the seeds by capturing the consumer's values with them. The same pinning makes a corrected project number or time zone a full re-apply of every generated file. The configuration surfaces being extended are owned by [the pairing-gate RFC](../../implemented/process/2026-09-07-bilingual-pairing-gate.md) and [the document-corpus-gates RFC](../../implemented/process/2026-09-07-document-corpus-gates.md); the binding behavior is owned by the [guided-adoption RFC](2026-10-01-guided-adoption-wizard.md).

## Proposal

- **Seeds become corpus constants.** The English-only exclusion set and the standard wrap and links globs move out of the manifests into the gates' scope predicates — protocol constants, not deployment-varying tunables — and the pairing manifest starts life as pure consumer configuration. The initial doc budgets for the templated standing documents remain one-time starting values in the file.
- **The three files join the editable class.** Created once, never digest-pinned, never clobber-checked, untouched by re-apply. adopt verify replaces byte pinning with structural checks: load-time validation, plus cross-checks of the adopt-owned fields — owner, repository, and account type against the derivation, statuses against the standard set, project number against the manifest anchor.
- **The pairing manifest gains `roots`.** Each entry extends the corpus as a subtree prefix under the trailing-slash boundary rule `excluded` already uses, which is the fix for a consumer repository whose own bilingual document tree sits outside the standard scope: its README's links to its own content stop diverging by byte comparison and normalize like corpus links.
- **A hand-authored `config.json` is a binding input.** A flag that contradicts an existing file value is a blocker — no precedence guessing — and consumer-owned fields are free edits validated at load.

## Alternatives considered

**Baseline plus overlay files.** Rejected: it archives the mixed-ownership problem instead of dissolving it. Once the seeds move, no upstream bytes remain in these files and the second layer has no reason to exist; it would be new machinery maintaining an absence.

**Keep byte pinning and document "redirect the change upstream".** This is the deadlock the first consumer actually hit; a repository-specific exclusion cannot be redirected anywhere, and the deadlock was discovered by following the documentation exactly.

**Editable with the seeds left in place.** Rejected: mixed ownership is the root cause. A consumer could silently delete a seed exclusion and learn about it only from a downstream pairing failure, one step removed from the act.

## Acceptance criteria

- Adding an exclusion, adding a `roots` entry, or correcting the project number or time zone never drifts adopt verify and never blocks a re-apply.
- Deleting a required field fails load-time validation with the field named.
- An adopt-owned field contradicting the derivation or the anchor is a named blocker.
- Corpus behavior for the standard set is unchanged by the seed migration: the same files stay in scope and the same gates cover them.

## Risks

- Losing digest pinning for these files weakens drift detection; the named structural checks are the replacement, and their coverage — load validation, derivation agreement, anchor agreement — is enumerated rather than implied.
- The seed migration changes manifest contents once, so upgrades carry a one-time migration step that must be documented in the release notes.
- A consumer-owned `roots` entry extends every pairing rule — including the structural-signature comparison — onto a tree hdsh has never seen; that is the mechanism working as intended, but it widens what a mis-declared root can affect.
