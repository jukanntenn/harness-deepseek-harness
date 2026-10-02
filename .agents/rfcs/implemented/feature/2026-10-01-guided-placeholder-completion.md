# RFC: Complete transplanted skill commands through guided placeholders

Status: implemented

English | [中文](2026-10-01-guided-placeholder-completion.zh.md)

## Problem

The transplanted skills asserted hdsh's concrete toolchain facts as if they were the consumer's: the pytest invocation and the tests/ mirroring layout, basedpyright for typed source, ruff beyond staged files, the hook inventory, the packaging smoke, the coverage workflow, the composition of the full local set, hdsh's own archive-test path, and its console-entry-point test convention. For a Rust or Node consumer these are dead commands, and the knowledge they stand in for — what to run for a behavior change, for a type surface, for style, for packaging — is exactly the question each repository must answer for itself. No gate saw a wrong command, and nothing asked the consumer to replace one. The measured surface was ten non-hdsh `uv run` commands across the pushing and archiving-rfcs skills, plus the hook and entry-path facts.

## Decision

This is the per-repo-value row of [the transplantable-corpus taxonomy](../architecture/2026-10-01-transplantable-corpus.md) realized for the skills.

- **Command-bearing skills are slot templates.** The audit named pushing (seven slots: hooks, focused-tests, type-check, packaging-smoke, style-check, coverage, full-suite), archiving-rfcs (archive-tests), and reviewing (entry-path). Each slot is a marked region — `<!-- hdsh:slot <name> -->` to `<!-- /hdsh:slot -->` — whose body ships as guided `TODO(adopt):` text stating what to declare and showing hdsh's own form as the worked example. The prose around the slots is genericized: the repository name leaves the title and description, and hdsh commands appear in the consumer form the invocation mapping produces.
- **The placeholder check is an always-run prek hook.** `hdsh-adopt-verify` runs `hdsh adopt verify --hook`, which counts the unfilled slots alongside every other `TODO(adopt):` marker; a repository without an adoption manifest is a no-op success, so the hook never fails where nothing was adopted. The hook carries the `hdsh` group like every managed hook, and hdsh's own prek configuration runs it too.
- **Slots persist across re-apply.** Apply re-renders the surrounding prose and, for each slot, keeps the consumer's value when the guidance is unchanged; the adopt manifest records the digest of every installed guidance as the baseline. When a slot's upstream guidance changed and the consumer had filled it, apply resets that slot to the new guidance, reports the reset by name, and the placeholder hook asks for the re-fill. Consumer edits outside the slots are upstream-owned territory: re-apply replaces them, exactly as for every generated file.
- **Templates speak the consumer form.** hdsh commands appear bare in slot templates; the invocation mapping applies to mirrors only. The non-hdsh `uv run` authoring rejection — staged by the corpus program until this one made the corpus satisfiable — is now enforced: the self-containment gate rejects any non-hdsh `uv run` command in the mirrored corpus.

## Verification

Focused tests pin the grammar and the flows: slot parsing reads multi-line regions and rejects nesting, unmatched markers, duplicates, and empty bodies; splicing replaces contents and requires every value; a fresh apply installs the guidance and the manifest records per-slot digests while verify demands the fills; a re-apply preserves a filled value and says so, resets a filled slot whose recorded guidance went stale and names it, blocks on malformed installed markers, replaces out-of-slot consumer edits instead of refusing, and reports a missing slot template as drift; hook mode no-ops without a manifest; and the self-containment gate now proves the mirrored corpus carries no development commands.

## Alternatives considered

**Generalize the wording and link the repository's command inventory.** Rejected: the pointer is not the value, the inventory may be unfilled or absent when followed, and hdsh's own skills lose their concrete commands — the defect that established the taxonomy row this RFC implements.

**Rewrite the commands mechanically at adopt time.** Impossible rather than merely wrong: the consumer's commands are unknown at adoption, so there is nothing to rewrite into; only the consumer can state them.

**Make the whole skill editable once filled.** Rejected: it freezes the operational corpus at adoption time, and upstream skill revisions would never reach adopted repositories again.

## Consequences

What the change bought: a fresh adoption cannot commit past the placeholder hook until every command slot is filled, and the diagnostic is the fill instruction; re-apply under a newer ref preserves filled slots and updates the prose around them; an upstream change to a slot itself is reported by name with the re-fill action; the audited skills carry no dead commands for any consumer; and the mirrored corpus is now provably free of hdsh development commands.

What the change cost: the three affected skills live twice — hdsh's live file beside its genericized template — and only the mirror-equality discipline keeps the other skills single-sourced; the slot grammar is new machinery, bounded by marker lines and the managed-block precedent; and the placeholder hook is commit friction by design, mitigated only by the diagnostic being the instruction.
