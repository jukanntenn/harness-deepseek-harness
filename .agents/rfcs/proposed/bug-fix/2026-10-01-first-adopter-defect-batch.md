# RFC: Repair the first-adopter defect batch

Status: proposed

English | [中文](2026-10-01-first-adopter-defect-batch.zh.md)

## Problem

The first real adoption of hdsh into a consumer repository surfaced eight defects, each observed live rather than hypothesized. They span the pairing gates, the adopted GitHub wiring, and adopt's conflict handling, and together they break the promise the gates exist to keep: every executed check tells one truth, and misconfiguration fails loud at the earliest resolvable point.

- **The pairing state ledger is split.** `hdsh pairing verify` rejects a pair whose structural signature diverges, but `hdsh pairing list` reports the same pair as `ok`: the structure-diff site appends to the error ledger without writing the pair state, so the fallback marks the pair green. A missing language switcher on either side carries the same defect.
- **The composite actions install the engine from the consumer's own clone URL.** Both actions resolve the engine with `github.event.repository.clone_url`, which inside a consumer workflow names the consumer repository; the pinned ref does not exist there, so the first policy or lifecycle event fails at engine install. The repository's own workflows never execute the actions, so the consumer path was never proven; see [the composite-action RFC](../../implemented/feature/2026-09-17-issue-policy-composite-actions.md) for the shipped design this corrects.
- **The switcher grammar rejects a more precise label.** The language-switcher line accepts only the literal `中文` label, so `简体中文` — the more precise zh-Hans name — fails as a missing switcher although the switcher is present and correct.
- **Group-filtered CI silently runs zero managed hooks.** prek's `--group` filtering excludes ungrouped hooks, the adopt-managed block ships none, and a consumer CI that filters by its own taxonomy executes no hdsh gate at all while local unfiltered runs execute all six: local red, CI green, no error anywhere.
- **The merge driver silently degrades.** `hdsh worktree install` registers one hardcoded driver command, `uv run --no-sync hdsh pairing merge-driver`, and its probe runs the installing process's form rather than the registered one; on a machine whose PATH holds no hdsh and no project environment exists, every pairing-record merge silently falls back to Git's text merge. See [the merge-driver RFC](../../implemented/feature/2026-09-17-pairing-merge-driver-cli-entry.md) for the registered design.
- **Pre-existing standing documents have no merge path.** A conflicting root `AGENTS.md` is skipped with a merge hint, but the corpus links into it keep deep anchors the consumer file does not define, so the consumer's own links gate goes half red with no guidance — one anchor fails, another coincidentally matches a same-named heading. Every other standing document, `docs/AGENTS.md` today, is a hard clobber blocker instead of a skip.
- **The link rewriter mangles inline-code examples.** The raw-regex rewriter treats link-shaped text inside backtick code spans as links and rewrites it into upstream URLs of files that do not exist upstream either: mangled examples and dead links that no gate can see.
- **actionlint schema lag surfaces only downstream.** hdsh's CI never runs actionlint, so the lag between actionlint's bundled schema and GitHub's accepted activity types (`issues.field_added`, `field_removed`) is rediscovered by every consumer independently.

## Proposal

**D1 — one state ledger.** Every error site in the pairing pair check writes the pair state it implies: a structural divergence, a missing switcher on either side, or a malformed record marks the pair `out-of-sync`; an incomplete pair keeps `missing`; only an error-free pair is `ok`. `list` and `verify` then read the same ledger.

**D2 — install the engine from the action's own repository.** The composite actions resolve the engine repository from `github.action_repository` — the repository hosting the action — with the event repository as the fallback for local uses, and a CI rehearsal job exercises the actions exactly as a consumer workflow would, so the consumer path is proven on every change instead of never.

**D3 — accept both switcher labels.** The switcher grammar accepts `中文` or `简体中文` in either label position, independently per side; hdsh's own corpus keeps the canonical `中文` as a style rule the gate deliberately does not enforce.

**D4 — the managed block carries a group.** Every managed prek hook is generated with `groups = ["hdsh"]`, and the plan output and the adoption manual state that CI runs using `--group` filtering must include the `hdsh` group.

**D5 — probe what you register.** `hdsh worktree install` resolves the driver command by probing the forms it could register — the bare `hdsh` form first, the `uv run --no-sync` form for project-environment machines — registers the first form that resolves, prints the chosen form, and fails loud with installation guidance when neither resolves.

**D6 — skip, track, and name the anchors.** A conflicting standing document is skipped and tracked as a pending manual merge; adopt verify computes the required anchor set from the corpus links into the skipped file and names every missing anchor; the links gate remains the permanent enforcement once the merge lands. Links into the skipped file stay relative — no upstream rewriting.

**D7 — code spans are never links.** The rewriter skips inline code spans, so example text lands in the consumer repository byte-identical.

**D8 — run actionlint upstream.** hdsh's CI runs actionlint so schema lag is caught where the workflows ship, and the adoption manual documents the consumer-side mitigation together with its removal condition.

## Verification

Each fix lands with focused tests that prove the broken case fails before and passes after: a structure-divergent pair drives `list` and `verify` to the same verdict; a consumer-shaped rehearsal installs the engine from the hdsh repository; both switcher variants pass the pairing gate; a group-filtered prek run executes every managed hook once the group is added; worktree install without a runnable hdsh exits nonzero naming the installation step; adopt verify lists each missing harness anchor by name; the inline-code example lands byte-identical; and the CI actionlint step reports schema lag as an upstream failure.

## Alternatives considered

**Rewrite skipped-file links to upstream URLs (D6).** Rejected: it reintroduces the outbound dependency on hdsh that the corpus program removes, and a pointer into hdsh's standing orders inside the consumer's review flow is precisely the leak that program exists to close.

**Detect pyproject.toml and pick the driver form (D5).** Rejected: the invocation canon already names the resolution order, and detection would restate it as a second mechanism; probing the forms in canon order and registering the first that resolves merges the probe ledger with the registration ledger.

**Per-repository group names through editable slots (D4).** Rejected: a universal value exists — every filtered CI can add `--group hdsh` — so the value is not per-repository, and slots would add persistence machinery that nothing needs.

**One RFC per defect.** Rejected: each fix sits at or under the mechanical-exemption line on its own; they share one record because they share provenance — a single adoption — and reviewing the batch together is cheaper than eight context switches.

## Acceptance criteria

- `hdsh pairing list` and `hdsh pairing verify` agree on every corpus pair in every state.
- A consumer repository's first policy or lifecycle event installs the engine from the hdsh repository at the pinned ref.
- A pair whose switcher reads `简体中文` passes `hdsh pairing verify` unmodified.
- A group-filtered prek run executes every managed hook after adding `--group hdsh`, and the generated block carries the group without consumer edits.
- `hdsh worktree install` on a machine without a runnable hdsh exits nonzero with installation guidance.
- adopt verify names each missing harness anchor for a skipped standing document, and every anchor resolves after the guided merge.
- Inline-code examples land byte-identical in the consumer repository.
- actionlint runs in hdsh CI, and the documented consumer mitigation carries its removal condition.

## Risks

- D6 turns a hard clobber blocker into a tracked pending merge, so an adopt run can now succeed while a standing document still owes content; the pending item stays visible in every subsequent adopt verify until the merge lands.
- D4 asks filtered CIs for one extra flag; a consumer who forgets it keeps the old silent gap, which is why the plan output and the manual both name the requirement.
- D3 accepts mixed label variants within one pair; the style rule keeps hdsh's own corpus canonical, and the gate deliberately does not police taste.
