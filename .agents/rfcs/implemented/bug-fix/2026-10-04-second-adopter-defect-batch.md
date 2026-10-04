# RFC: Repair the second-adopter defect batch

Status: implemented

English | [中文](2026-10-04-second-adopter-defect-batch.zh.md)

## Problem

A review of the first completed adoption — the wakewake repository — surfaced a second batch of defects, again observed live rather than hypothesized. They cluster where adopt's own mechanics contradict its contract: probes that cannot pass, derivations that read the wrong remote, transforms that cover only half their paths, and invariants the manual states but no executed check enforces.

- **Preflight's hdsh probe can never pass.** The wizard proves runnability with `hdsh --version`, but the CLI registers no version action, so a freshly installed hdsh exits 2 and preflight reports `bare hdsh is not runnable on PATH` — the manual's documented first step is red on a healthy machine, and the remediation names a PyPI package that does not exist.
- **Ref derivation reads the consumer's remote.** `resolve_hdsh_ref` runs `git ls-remote --tags origin` inside the consumer repository, so a consumer carrying its own `vX.Y.Z` tags silently writes one of them as the prek `rev` of the hdsh repository; the clone fails far from apply.
- **The adoption date ignores `--time-zone`.** Apply stamps dated records from UTC, so an operator adopting at 2026-10-03 06:14 Asia/Shanghai gets a `2026-10-02` decision record — one day off the operator's calendar.
- **Rooted agent instructions demand translation.** The English-only exclusions are six hardcoded paths; a manifest `roots` subtree carrying its own `AGENTS.md` immediately owes a Chinese counterpart, and the only escape is per-file `governed` holes.
- **Off-corpus bilingual links cannot satisfy two rules at once.** The locale convention has each side link its own suffix (`.md`/`.zh.md`), but the structural signature compares non-corpus relative targets by raw bytes, so the convention alone always diverges; the first adopter hit this three times and had to root an entire legacy subtree to escape.
- **The manual undersells the pairing workload.** Phase 3 said "pair the repository's own README"; discovery finds every README pair at any depth plus rooted subtrees — thirty pairs, not one.
- **The actionlint bridge does not ship.** The manual told consumers to "bridge with `paths.ignore`", but apply writes no bridge file and the schema (per-file, per-message regex) is guesswork; the first adopter wrote two wrong schemas before copying hdsh's own.
- **Group-filtered CI still drops gates silently.** The managed hooks carry the `hdsh` group and the manual warns about it, but nothing executes the warning: the first adopter's scoped lint jobs filtered without `hdsh`, and their paths' gates ran nowhere.
- **The invocation mapping covers half the render paths.** Slot templates and token-rendered templates skip `map_invocations`, so `uv run hdsh scope` survived into the reviewing skill and seven `uv run hdsh` forms into a fresh `docs/AGENTS.md`.
- **Transplanted skills carry the harness brand.** Seven "harness-deepseek-harness" strings, an "hdsh documentation" heading, and `src/hdsh/` corpus facts landed in the consumer's skill tree; no mechanism carried the consumer's own facts.
- **ripgrep is assumed, never checked.** The skills instruct `rg` first; preflight probes only git, gh, and hdsh.

## Decision

**D1 — the CLI answers its own probe.** The root parser registers `--version` from the installed distribution; the parser-exit contract generalizes to `InfoShown` for help and version alike; preflight's remediation and the worktree driver hint name the `git+<url>@<ref>` install form until PyPI publishes.

**D2 — ref derivation reads the upstream URL.** `resolve_hdsh_ref` lists tags from `https://github.com/jukanntenn/harness-deepseek-harness` directly, never from the consumer's remotes; the no-main-HEAD-fallback failure stays.

**D3 — dated records follow the Project zone.** The adoption date derives from the resolved `--time-zone` (itself from the system zone when absent); the flag help says so.

**D4 — agent instructions are English-only as a class.** Any `AGENTS.md` is excluded by pattern — subtracted after `roots` extension, so a rooted subtree needs no per-file holes; the translation-memory references stay the only path constants.

**D5 — off-corpus links compare at the English anchor.** Relative targets outside the active corpus project to their `.md` form before the structural comparison — the relative analog of the absolute-URL rule — so the per-side locale convention alone can never diverge a pair; the locale check keeps governing corpus targets.

**D6 — apply sizes the pairing corpus.** Plan and apply print one note over the post-apply corpus — English documents in scope and how many still need a counterpart and record — and Phase 3 names the real corpus shape: every README pair at any depth, `docs/**`, `.agents/rfcs/**`, and manifest `roots`.

**D7 — the actionlint bridge ships with apply.** `.github/actionlint.yaml` becomes a mirrored file: the per-file, per-message-regex bridge with its removal condition and the link to GitHub's documented `issues` activity types; a pre-existing copy blocks loudly instead of being overwritten.

**D8 — verify owns the CI group contract.** `hdsh adopt verify` scans workflow files for `prek run` commands whose `--group` filter omits `hdsh` and reports each as drift; the check executes in CI through the `hdsh-adopt-verify` hook.

**D9 — one invocation transform, every render path.** `map_invocations` runs over token-rendered templates and over slot templates before slot parsing — guidance digests stay stable because no guidance body carries the source form — and verify reports any `uv run hdsh` leftover in adoption-owned files as drift.

**D10 — transplanted skills carry no harness brand.** Live skill wording drops the repository name and brand headings ("this repository", "# Archive RFCs", "# Documentation"); `finding-simplifications` moves from the mirrored set to the slot templates with a `production-corpus` slot carrying its judgment facts.

**D11 — ripgrep joins preflight.** `rg --version` is the fourth probe; the success line and the manual name it.

## Verification

Focused tests pin each path: `hdsh --version` prints the installed version and exits 0; a consumer-origin transport key is never consulted for ref derivation; one frozen instant dates Asia/Shanghai one day ahead of America/New_York; a rooted `.agents/wrfcs/AGENTS.md` stays out of the corpus while the subtree's README joins; an off-corpus `.zh.md` target compares equal to its `.md` twin and a genuinely different target still diverges; the apply output carries the corpus-size note and the installed actionlint bridge with its evidence link; a workflow filtering without `hdsh` is drift at its file and line and clean once the group joins or the filter drops; slot templates and `docs/AGENTS.md` land bare (`hdsh scope`, no `uv run hdsh`) and a hand-reintroduced source form is drift; the transplanted skills contain no "harness-deepseek-harness"; and a transport missing `rg --version` reports one diagnostic.

## Alternatives considered

**Map repository names at transplant time (D10).** Rejected: mirrors must stay byte-equal to live files, and a transform-layer mapping would either corrupt hdsh's own copies or fork the live text from the transplanted text; wording the live files repo-neutrally keeps one source of truth.

**A manifest key for English-only files (D4).** Rejected: the exclusion is a class invariant of agent instructions, not a deployment-varying choice; a key would invite per-file holes the class rule makes unnecessary.

**Warn instead of drift on missing groups (D8).** Rejected: a warning channel is exactly the silent space the harness exists to close; scoped jobs can add `--group hdsh` without harm.

**A separate `--date-zone` flag (D3).** Rejected: the Project zone is the repository's calendar; two zone flags would let dated records and Project rendering disagree by design.

## Consequences

What the batch bought: a fresh machine passes preflight first try; a tagged consumer adopts without passing `--hdsh-ref`; the decision record carries the operator's date; rooted subtrees need no instruction holes; off-corpus bilingual links pass under the locale convention without rooting legacy trees; apply prints the real pairing workload; the actionlint bridge and its evidence arrive with the workflows; a filtered CI missing the group goes red in verify; transplanted files carry only the bare invocation; and the consumer's skill tree names its own repository, with `finding-simplifications` asking for its production corpus through a slot.

What the batch cost: existing adopters re-running apply replace `finding-simplifications` with its slot version and owe one new placeholder; a hand-written `.github/actionlint.yaml` blocks re-application until removed (loud, one-time); ADOPT.md's word ceilings rise (470→740 English, 190→270 Chinese) because the manual gains the retirement section and the real corpus shape; and `--time-zone` now carries a second duty — Project rendering and dated records share one calendar, which is the point.
