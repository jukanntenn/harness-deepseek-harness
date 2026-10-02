# RFC: Give consumers ownership of their configuration files

Status: implemented

English | [中文](2026-10-01-consumer-configuration-ownership.zh.md)

## Problem

Three installed files mix upstream-rendered bytes with per-repository values while the adopt manifest byte-pins them: `.hdsh/pairing.manifest.json` — whose `excluded`, `generated`, and `public_blob_root` fields are the documented consumer mechanisms — plus `.hdsh/docs.manifest.json` and `.github/issue-management/config.json`. The first consumer that exercised a documented mechanism, excluding `.zcode/README.md` from the corpus, landed in a permanent deadlock: adopt verify reported drift forever, and a later re-apply was refused by the clobber check, whose guidance — revert the local change, or redirect it upstream — is impossible for a repository-specific exclusion. The root cause is ownership, not pinning: the seed entries inside these files (the English-only exclusion set, the standard wrap and links globs) are corpus constants wearing configuration clothing, and byte pinning protects the seeds by capturing the consumer's values with them. The same pinning makes a corrected project number or time zone a full re-apply of every generated file. The configuration surfaces being extended are owned by [the pairing-gate RFC](../process/2026-09-07-bilingual-pairing-gate.md) and [the document-corpus-gates RFC](../process/2026-09-07-document-corpus-gates.md); the binding behavior is owned by the [guided-adoption RFC](2026-10-01-guided-adoption-wizard.md).

## Decision

- **Seeds are corpus constants.** The English-only exclusion set and the standard wrap and links globs moved out of the manifests into the gates: `is_scope_file` carries the English-only files, and the documentation gates carry `STANDARD_SCOPE` built in. The pairing manifest starts life as pure consumer configuration (`excluded` now optional alongside `generated`), and the docs manifest sections for wrap and links became optional consumer extensions unioned onto the standard corpus rather than required replacements for it. The initial doc budgets remain one-time starting values in the file.
- **The three files are consumer-owned.** Created once at adoption, never digest-pinned, never clobber-checked, untouched by re-apply; the adopt manifest lists them under `consumerConfig`, and adopt verify checks structure instead of bytes: each file must load under its owning parser; `config.json` must still name the origin-remote repository and the standard status set. The project-number-against-anchor cross-check waits for the guided-adoption program, which introduces the anchor.
- **The pairing manifest carries `roots` and `governed`.** `roots` entries are trailing-slash subtree prefixes extending the corpus — a consumer repository whose own bilingual document tree sits outside the standard scope declares it, and its README's links into that tree stop diverging by byte comparison and normalize like corpus links. `governed` entries name bilingual content the repository maintains under its own discipline: translations may exist, and the gate looks away entirely. One predicate — standard scope or roots, minus excluded and governed — now drives discovery, named-anchor validation, and link-source semantics alike.
- **A hand-authored `config.json` is a binding input.** Its values become the adoption parameters; every required flag that contradicts a file value is a blocker, because required flags are always explicit and adopt never guesses precedence. The `--allow-unassigned-owner` store-true flag cannot distinguish presence from absence, so the file wins for that boolean. A file whose statuses leave the standard set is a blocker at apply, not only at verify.

## Verification

Focused tests pin each behavior: a pre-existing consumer manifest survives apply byte-identical while its digest leaves the adopt manifest; a hand-authored `config.json` binds, a contradicting flag blocks with the field named, malformed files block, and a non-standard status set blocks at apply; verify reports invalid, missing, and repository-mismatched consumer configuration as drift; `roots` admits a consumer document tree whose links normalize across languages where the same tree stays red without the root; `governed` keeps translations with no completeness or switcher demands; and the docs gates cover the standard corpus with no manifest section and union consumer extensions onto it. The full corpus gates run green on this repository with its own manifests slimmed to the new shape.

## Alternatives considered

**Baseline plus overlay files.** Rejected: it archives the mixed-ownership problem instead of dissolving it. Once the seeds moved, no upstream bytes remain in these files and the second layer has no reason to exist; it would be new machinery maintaining an absence.

**Keep byte pinning and document "redirect the change upstream".** This is the deadlock the first consumer actually hit; a repository-specific exclusion cannot be redirected anywhere, and the deadlock was discovered by following the documentation exactly.

**Editable with the seeds left in place.** Rejected: mixed ownership is the root cause. A consumer could silently delete a seed exclusion and learn about it only from a downstream pairing failure, one step removed from the act.

## Consequences

What the change bought: adding an exclusion, a `roots` entry, or correcting the project number, time zone, or actor never drifts adopt verify and never blocks a re-apply; deleting a required field fails load-time validation with the field named; an adopt-owned field contradicting the derivation is a named blocker; and corpus behavior for the standard set is unchanged by the seed migration — the same files stay in scope under the same gates.

What the change cost: losing digest pinning for these files weakens drift detection, and the named structural checks — load validation, repository agreement, status-set agreement — are the enumerated replacement. The seed migration changes manifest contents once, so upgrades carry a one-time migration old files absorb gracefully (seed entries and standard globs become no-ops against the built-in constants). A consumer-owned `roots` entry extends every pairing rule — including the structural-signature comparison — onto a tree hdsh has never seen; that is the mechanism working as intended, but it widens what a mis-declared root can affect.
