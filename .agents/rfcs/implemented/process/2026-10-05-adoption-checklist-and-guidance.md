# RFC: A machine-readable Phase 1 checklist and three guidance seams

Status: implemented

English | [中文](2026-10-05-adoption-checklist-and-guidance.zh.md)

## Problem

Three guidance seams the fourth adopter hit on the way in. First, Phase 1's enumeration — the label taxonomy, the seven board statuses, the `Priority` and start-date fields — existed only as source constants (`rules.py`, `corpus.py`); `hdsh adopt plan` requires `--project-number`, so before creating the board the operator had nothing to read but the source. Second, preflight reported "gh authenticated" while board creation actually needs the `project` scope, an operator-level fact [the wizard RFC](../feature/2026-10-01-guided-adoption-wizard.md) left to the manual; the operator discovers the gap at the board step. Third, [translation-rules](../../../../docs/i18n/translation-rules.md) said pure in-page fragments stay unchanged without telling the translator that GitHub keeps a CJK heading's characters in its slug — so an unchanged fragment resolves on the Chinese side only beside an explicit `<a id>` anchor, the pattern the corpus itself already uses (the RFC index, the i18n contract README) but the rulebook never stated; the pairing gate's exact-fragment comparison and the links gate's resolvability requirement otherwise read as contradictory, as [the corpus-gates RFC](../process/2026-09-07-document-corpus-gates.md) records. gh has since shipped native `gh project` commands, so the manual's "the consumer's agent runs these" can now mean literally that — except for the built-in Status field's options.

## Decision

- `hdsh adopt checklist` prints the Phase 1 enumeration as copy-pasteable commands derived from single sources: `LABEL_DESCRIPTIONS` in the policy rules — pinned by test to exactly the closed `kind/*`, `type/*`, and priority sets — the seven standard statuses, the `Priority` single-select options, and the `field-create` commands. gh cannot edit the built-in Status field's options, so the checklist prints the two GraphQL commands that set all seven in one call: the field-id query (`user(login:)` shown, `organization(login:)` named for organization accounts) and the `updateProjectV2Field` mutation with the standard option set, both as `gh api graphql` invocations runnable by the operator token that already carries the `project` scope — the fifth adopter proved the route by setting board #6's statuses with it. It also names the `gh auth refresh -s project` remedy.
- Preflight parses the `Token scopes:` lines a successful `gh auth status` discloses and emits an advisory — not a blocker — when none mentions `project`; undisclosed scopes (an unrecognized output format) stay silent rather than wrong. The advisory is separate from failures because organization deployments drive their workflows with App credentials the operator token never carries.
- The translation rule now states the pattern: the same `<a id>` on both sides beside the heading, the fragment linked verbatim — the reconciliation the two gates already accept, no gate weakened.
- The adoption manual points Phase 1 at the checklist, states the scope remedy and the Status-UI boundary, and documents the adoption-pull-request bootstrap behavior decided in [the bootstrap RFC](../bug-fix/2026-10-05-first-adoption-policy-bootstrap.md).

## Verification

Checklist output is pinned by test against the constants — every label command with its description, all seven statuses, both field-create forms, the field-id query and the Status-options mutation, and the scope remedy — and the taxonomy test proves `LABEL_DESCRIPTIONS` covers exactly the closed label sets. The scope advisory is pinned through the injected transport (scopeless, project-carrying, undisclosed) and against the parser directly. The translation-rules and adoption-manual pairs re-record green under the pairing gate, and the wrap, links, and budget gates pass over the edited corpus.

## Alternatives considered

**List the enumeration in the adoption manual only.** Rejected: a second hand-maintained copy of closed sets drifts from the constants the engine enforces; the command derives from the single source, and the manual points at it.

**Make the missing scope a preflight blocker.** Rejected: organization deployments never need the operator token to carry `project`; blocking preflight would fail correct setups to warn about a flavor-specific convenience.

**Relax the pairing gate to accept locale-sluggable fragments.** Rejected: the structural signature compares exact fragments because a diverged anchor is precisely the divergence it exists to catch; the explicit anchor reconciles both gates without weakening either.

**Wrap the Status-options mutation in an hdsh subcommand.** Rejected for this change: hdsh holds no Project credential at adoption time — the operator's gh token is the only credential in play, and `gh api graphql` rides it without a new hdsh surface; a first-class command can follow if adopters want idempotent convergence rather than a printed one-shot.

## Consequences

What the change bought: a Phase 1 operator — human or agent — runs one command instead of reading source, learns the scope requirement before the board step rather than at it, and a translator has the sanctioned fragment pattern with the corpus's own pairs as examples.

What it cost: the checklist is one more surface to keep aligned with the constants (held by test), the scope advisory reads gh's output format under a disclosed-only rule, and the Status options are set through printed GraphQL rather than a first-class hdsh command — the raw mutation replaces the option set wholesale, so a board whose options diverge converges only by rerunning it.
