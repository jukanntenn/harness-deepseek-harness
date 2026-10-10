# RFC: Fix the second adoption report — schema-drifted checklist mutation, rebind deadlock, and cache-red skips

Status: implemented

English | [中文](2026-10-10-adoption-report-follow-ups.zh.md)

## Problem

The same adopter's follow-up report carried three defects. First, the Phase 1 checklist's board-setup mutation no longer matched GitHub's GraphQL schema: `updateProjectV2FieldInput` takes no `projectId`, and every single-select option now requires a color from the fixed enum (eight values, no BROWN) plus a description — copying the printed command verbatim failed five ways, and the adopter hand-wrote the mutation to configure the Status options. Second, moving boards deadlocked: verify's anchor check requires `config.json` and the adopt manifest to agree, the commit hook runs adopt-verify, apply refuses a dirty worktree, and a `--project-number` flag contradicting the binding `config.json` is a blocker — so editing the config first could not commit and passing the flag first could not apply; the adopter hand-edited both files. The anchor diagnostic's promised remedy, "rerun hdsh adopt apply with the new number to rebind", was a command that could not be executed. Third, on the adoption pull request both policy workflows still concluded failure on their skip paths: `astral-sh/setup-uv@v9`'s cache post-step errored on a missing cache directory, so the documented "skip with a notice" rendered as the pull request's only two red checks.

## Decision

- The checklist mutation now matches the schema document GitHub publishes: the input takes `fieldId` alone, and each of the seven status options carries its name, one of GRAY, PURPLE, BLUE, YELLOW, ORANGE, GREEN, RED, and a description. The checklist line also says to run the call before items carry Status values, because replacing the option set without option ids clears existing values.
- `hdsh adopt apply --rebind` (also understood by `plan`) is the explicit board-move path: the passed `--project-number` and `--project-title` override the binding `config.json` instead of contradicting it, every other parameter still resolves from that file, and the run itself re-renders `config.json` — the only consumer-config destination apply ever rewrites — so the new anchor and the new binding land together as one committable state. Non-board contradictions still block, and the dirty-worktree refusal stands: with the rebind writing the file, no hand edit is needed. The verify anchor diagnostic names the command and says to revert hand edits first.
- Both composite actions pass `enable-cache: false` to setup-uv: the engine install is one wheel from a pinned ref, so caching buys nothing, and its post step turns skip runs red on a cache miss.

## Verification

The checklist tests pin the printed mutation — fieldId-only input, per-option color and description, no `projectId` variable or argument, no BROWN. The rebind tests prove the round trip: the config is re-rendered with the new number and title while other values keep their `config.json` resolutions, the manifest anchor follows, verify reports no anchor drift, and a rebind run does not waive a non-board contradiction. The mutation shape was checked against GitHub's published GraphQL schema, and the engine's own mutations (`addProjectV2ItemById`, `updateProjectV2ItemFieldValue`) were confirmed unchanged. The full suite, lint, and type gates re-ran green.

## Alternatives considered

**Tolerate one dirty file in apply instead of rewriting the config.** Rejected: it weakens the "adoption never mixes with uncommitted work" invariant for every run to serve one flow, and it leaves the consumer composing the intermediate state by hand; the rebind renders the end state directly.

**Let verify accept config-ahead-of-manifest as a committable middle state.** Rejected: it suspends the anchor invariant for exactly the window where a wrong-board mistake lands unnoticed; the invariant should fail loud until one explicit command re-establishes it.

**Keep `projectId` and only add the missing option fields.** Rejected: the input no longer accepts the argument at all, so the half-fix still fails.

**Leave setup-uv's cache defaults.** Rejected: one wheel from a pinned ref per run gains nothing from a cache, and the post step's failure mode is precisely a red skip on the bootstrap pull request.

## Consequences

What the change bought: the Phase 1 checklist copies verbatim again, a board move is one explicit command with no hand editing, and the adoption pull request's skip paths read as skips. What it cost: a rebind deliberately replaces `config.json` (formatting normalizes to adopt's rendering, so a simultaneous hand edit to that one file must be re-checked), and the option colors are fixed constants rather than operator choices — the palette is part of the harness's board shape.
