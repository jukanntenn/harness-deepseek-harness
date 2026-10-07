# RFC: adopt verify warns when a skills mirror lacks the installed skills

Status: implemented

English | [中文](2026-10-07-skills-mirror-detection.zh.md)

## Problem

The fifth adopter's repository mirrors `.claude/skills/` ↔ `.agents/skills/` with a direction-agnostic sync tool. hdsh writes only `.agents/skills/`, so the first mirror run read the empty far side as a deletion and removed all nine installed skills — twice, refilled by hand each time. The manifest's slot preservation cannot help once the files are deleted, and `hdsh adopt verify` stayed silent throughout: the mirror tree is not hdsh's, so nothing in the digest model covers it.

## Decision

- Verify recognizes the mirror layout the corpus actually saw: when `.claude/skills/` exists and installed skill paths — the manifest's `files`, `editable`, and `slotTemplates` entries under `.agents/skills/` — lack counterparts under `.claude/`, verify prints one advisory naming the counts, an example path, and the remedy: copy `.agents/skills/` to the mirror side before running the mirror tool.
- The advisory changes no exit code. The mirror tree is consumer-owned and a missing counterpart is not drift in hdsh's files; deleted `.agents`-side skills remain hard drift through the existing digest check, and the committed paths restore with git.
- The adoption manual's Phase 3 warning — landed with the fifth-adopter friction batch — names the same ordering rule; this advisory surfaces it at every verify while the risk is live.

## Alternatives considered

**Fail verify when the mirror is incomplete.** Rejected: hdsh does not own the mirror tree, repositories without any mirror must stay green, and a half-configured mirror is consumer state to manage — the hint keeps the risk visible without annexing ownership.

**Detect every known agent-mirror layout.** Rejected: `.claude/skills` is the one layout an adopter actually hit; a generic scan over sibling skills directories would fire on unrelated tooling. The recognized set stays closed and grows when a real adopter brings a second layout.

**Copy to the mirror side at apply time.** Rejected: apply would claim a tree another tool manages bidirectionally; the copy is the consumer's own first mirror run, made safe by the ordering warning instead of performed behind their back.

## Consequences

What the change bought: the layout that cost two rounds of refilling announces itself at every verify with the remedy in the message, while exit codes stay honest about hdsh-owned drift alone.

What it cost: one recognized layout name carried as a constant, and the advisory prints on every verify until the mirror is filled — intentional, because the deletion risk is live until then.

## Verification

Verify tests pin the three states: an empty mirror directory beside installed skills prints the advisory and exits green, a fully mirrored tree prints nothing, and no mirror directory prints nothing. Deleted `.agents`-side skills remain hard drift under the digest check, pinned by the existing missing-file test.
