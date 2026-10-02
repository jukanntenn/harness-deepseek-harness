# RFC: Complete transplanted skill commands through guided placeholders

Status: proposed

English | [中文](2026-10-01-guided-placeholder-completion.zh.md)

## Problem

The transplanted skills assert hdsh's concrete toolchain facts as if they were the consumer's: the pytest invocation and the tests/ mirroring layout, basedpyright for typed source, ruff beyond staged files, the composition of the full local set, and one skill names hdsh's own test-file path outright. For a Rust or Node consumer these are dead commands, and the knowledge they stand in for — what to run for a behavior change, for a type surface, for style — is exactly the question each repository must answer for itself. No gate sees a wrong command, and nothing asks the consumer to replace one. The measured surface is ten command mentions concentrated in the pushing and archiving-rfcs skills, with reviewing suspect beyond those.

## Proposal

This is the per-repo-value row of [the transplantable-corpus taxonomy](../../implemented/architecture/2026-10-01-transplantable-corpus.md) realized for the skills.

- **Command-bearing skills become templates.** Each per-repo command fact becomes a guided `TODO(adopt):` placeholder whose text tells the filling agent what to state and shows hdsh's value as the worked example — the same marker the templated standing documents already use.
- **The placeholder check becomes an always-run prek hook.** adopt verify's existing placeholder check is wired where prek enforces it, so a commit that would carry an unfilled slot is blocked with the fill instruction in the diagnostic — the forcing function that already drives standing-document completion, moved onto the commit path.
- **Slots persist across re-apply.** Each placeholder site is a consumer-owned region inside an otherwise upstream-owned file: re-apply re-renders the surrounding prose and preserves filled slot values, reporting drift only when the upstream slot itself changed. The adopt-managed prek block is the in-tree precedent for marked regions with defined ownership.
- **Templates speak the consumer form.** hdsh commands appear bare in templates; the invocation mapping applies to mirrors, and templates — authored for consumers from the start — need no mapping.
- **An audit precedes implementation.** pushing and archiving-rfcs are known affected and reviewing is suspect; the audit enumerates every repository-specific fact in the skill set, and only the audited files become templates — the rest stay byte-equal mirrors.

## Alternatives considered

**Generalize the wording and link the repository's command inventory.** Rejected: the pointer is not the value, the inventory may be unfilled or absent when followed, and hdsh's own skills lose their concrete commands — the defect that established the taxonomy row this RFC implements.

**Rewrite the commands mechanically at adopt time.** Impossible rather than merely wrong: the consumer's commands are unknown at adoption, so there is nothing to rewrite into; only the consumer can state them.

**Make the whole skill editable once filled.** Rejected: it freezes the operational corpus at adoption time, and upstream skill revisions would never reach adopted repositories again.

## Acceptance criteria

- A fresh adoption cannot commit past the placeholder hook until every command slot is filled, and the diagnostic carries the fill instruction.
- Re-apply under a newer ref preserves filled slot values and updates the surrounding prose.
- An upstream change to a slot itself reports drift naming the re-fill action.
- The audit lists every templated skill with its slot count, and the unaudited skills remain byte-equal mirrors.

## Risks

- The affected skills live twice — hdsh's file beside its template — held together by a modulo-slot sync gate; this is the accepted tax of the per-repo-value class, confined to the audited files.
- The placeholder hook is commit friction by design; the mitigation is the diagnostic itself, which is the instruction.
- Slot persistence is new machinery; bounding it to marked regions and the managed-block precedent keeps its surface small.
