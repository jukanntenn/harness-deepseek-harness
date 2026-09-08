# RFC: Adopt the documentation standard

Status: implemented

English | [中文](2026-09-07-adopt-documentation-standard.zh.md)

## Problem

The repository shipped gates for pairing, wrapping, links, budgets, and RFC format, but no documentation standard above them: no tier taxonomy, no tutorial/reference discipline, no slop checklist, no ordered map of the package, and no contributor entry point beyond the root command list. The open question was scope: the standard had to state what belongs and what stays out.

## Decision

The standard is scoped to this corpus:

- [docs/architecture.md](../../../../docs/architecture.md) joins the corpus as the ordered map: domains, the unified CLI, per-domain sections, and a where-new-behavior-goes table, with rationale linked to RFCs rather than restated.
- [docs/development.md](../../../../docs/development.md) joins as the contributor setup tutorial and reference: prerequisites, first-time setup, Git integrations (including the merge-driver failure contract, linked to the pairing contract's `#the-pairing-contract` anchor), prek hook boundaries, and a CI summary.
- [docs/AGENTS.md](../../../../docs/AGENTS.md) grows the tier taxonomy with one-home-per-fact rows and "does NOT belong there" columns, the tutorial/reference classification with reader-knowledge ordering and the authoring order, the slop checklist, the three-step budget policy (relocate, condense, raise) with 5% headroom, and the write-directly rule; its word ceiling is held in the docs manifest.
- `.agents/skills/documenting` carries the placement-and-audit workflow: the run-sequence, the executed-operation fact-check procedure, voice rules, quality criteria, corpus audit, and budget policy.
- `.agents/skills/editing-prose` carries the editorial standard: complete-proposition preservation, required coverage by prose location, and the borderline-decision protocol.

Out of scope: new documentation tiers, generated catalogs, and a site projection; none of them gets a gate.

## Alternatives considered

**Adopt a maximalist standard.** Cross-references into machinery this repository does not ship would dangle, and dead links fail the docs-links gate on the first run.

**Stay at the minimal per-gate rules.** The corpus already needs placement decisions (architecture versus development versus cookbook) and the slop failure modes; without a stated standard those decisions are re-litigated per PR and nothing audits them.

**Adopt only the taxonomy, not the skills.** The taxonomy states the rules but not the procedure for applying them; the audit and fact-check workflows are the part agents actually load, and they are pure guidance.

## Consequences

- New standing documents join the pairing corpus and the budget manifest; `docs/AGENTS.md`'s taxonomy is the placement authority, and documenting audits against it.
- The i18n README's `#the-pairing-contract` anchor is the merge-driver contract's inbound link target, and development.md cites the exact accepted files and states.
- The two skills are English-only instruction files — exempt from pairing, inside the wrap/links corpora — and reference only mechanisms this repository ships.
- Extending the standard means updating this RFC's scope list in the same change, not re-deriving what belongs.
