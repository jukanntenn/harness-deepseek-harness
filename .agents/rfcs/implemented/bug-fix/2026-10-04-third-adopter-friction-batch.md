# RFC: Repair the third-adopter friction batch

Status: implemented

English | [中文](2026-10-04-third-adopter-friction-batch.zh.md)

## Problem

A second live adoption — the progress repository — cleared plan and apply but surfaced a third batch of frictions, again observed live rather than hypothesized. Four defects make the toolchain contradict itself mid-adoption; five documentation gaps leave the operating manual one step behind the mechanics.

- **The wizard reads every probe failure as a missing credential.** `resolve_lifecycle_actor` probes `gh api user` — a live network call — but any nonzero exit collapses into "gh is not authenticated", directly contradicting a preflight that passed seconds earlier on `gh auth status`; a transient network failure is rerun-and-green, and an absent `gh` surfaces as a raw `FileNotFoundError` traceback.
- **A finished pair cannot link a sibling whose translation has not landed.** While a batch of counterparts is still landing, a Chinese side that links `other.zh.md` fails the cross-link gate (target missing) and its own pair's structural signature (the unresolved link projects to a bare form while the English side's resolves to the pair anchor); linking `other.md` instead fails the locale check, which never falls back. No spelling passes both gates, so per-pair commits cannot go green mid-batch — two independent translation agents hit this and read the gate source to understand it.
- **Apply blesses a template against consumer content.** With a pre-existing real `docs/development.md`, apply skips the English write (mislabeling consumer content "an installed placeholder template"), still writes the generic Chinese template beside it, and records the pair as confirmed-consistent — a record semantics says means reviewed — so verify immediately reports the missing switchers and five structural divergences of a pair adoption never actually wrote.
- **Verify unmasks one divergence per field at a time.** `structure_diff` breaks after each field's first mismatching index, so a README translator fixes one link, reruns, and meets the next; worse, any post-record edit hits the hash-mismatch early return, which hides every structural finding until the pair is re-recorded.
- **The manual's phases run against the dependency order.** Phase 1 says run `plan`/`apply`, whose `--project-number` is required, while creating the Project board is a Phase 2 bullet — a first-time adopter must raid Phase 2 to start Phase 1.
- **A gate-less CI is invisible.** The group-filter drift check only scans existing `prek run --group` lines; a CI that runs commands directly — the adopter's actual shape — scans clean while all six gates stay local-only, and neither apply's output nor the manual mentions the wiring.
- **The wrap migration cost is unstated.** The adopted scope covers the consumer's whole pre-existing corpus and cannot shrink; one adopter met 84 red wrap sites and reflowed 83 paragraphs, a cost ADOPT.md never prices.
- **Full-width punctuation swallows bare URLs.** GFM literal autolinks trim only ASCII trailing punctuation and reference destinations trim nothing, so `详见 https://example.com/a，后续` absorbs the comma and the prose into the destination — on GitHub and in the pairing signature alike; the translation rules never warn.
- **Chinese-first documents have no flip procedure.** The contract permits authoring in either language, but a legacy Chinese document on an English-side path silently becomes "an English document needing translation"; the adopter's agent had to invent the move.

## Decision

**D1 — probes classify before they diagnose.** One classifier serves `resolve_lifecycle_actor`, `resolve_account_type`, and preflight's gh check: an absent binary (a caught `FileNotFoundError`, mirrored by the transport's not-found sentinel) reports "gh is not runnable on PATH"; a rejected credential (gh's own `gh auth login` / HTTP 401 / bad-credentials wording) keeps the authenticate remedy; every other exit reports the command, status, and gh's first stderr line as a probe failure to rerun — never a claim about the credential. No auto-retry: a fully flagged run stays offline and the hermetic transport stays deterministic.

**D2 — pending pairs resolve through the English anchor.** A Chinese-side link to `X.zh.md`, missing while `X.md` is an active corpus source, resolves through to the English source: the structural signature then reads the pair anchor on both sides, the locale check accepts its own expected spelling, the generated-region normalizer agrees, and the cross-link gate passes a missing `.zh.md` whose English sibling exists. The corpus-wide "must merge bilingual" error is untouched — the untranslated document itself, not the links into it, tracks the batch. English sides misusing the `.zh.md` spelling stay unresolved, and links naming no corpus file stay broken.

**D3 — template pairs are atomic and evidence-keyed.** When either side of a templated pair (architecture, development) exists without the previous adoption's manifest listing it as installed, apply writes neither side and records nothing, printing one note that translation from the real content and a manual record are consumer-owned; adopt-installed sides keep today's skip-and-record behavior, and the pairing sizing note counts the deferred pair as outstanding.

**D4 — divergence output is complete.** `structure_diff` reports every mismatching index per field, and the hash-mismatch branch of `_check_pair` no longer returns early: the out-of-sync error stands while the locale, switcher, and structural findings print beneath it, so one verify run carries the full repair list. Positional noise after an insertion is the accepted cost of unmasking.

**D5 — the manual runs in dependency order.** The out-of-git checklist becomes Phase 1 — it creates the board whose number plan and apply require — and install becomes Phase 2, carrying that number; later phases renumber nothing.

**D6 — verify owns the CI wiring contract.** Plan and apply print the wiring note (prek in CI, or a pinned install plus the managed gate commands), and `hdsh adopt verify` reports a CI whose workflows invoke neither `prek run` nor a bare `hdsh` command — the policy workflows' `hdsh-ref:` input names the tool without invoking it and does not count. A repository with no workflows at all gets one informational line, not drift.

**D7 — plan prices the wrap migration.** Plan and apply count hard-wrapped paragraphs across the pre-existing in-scope corpus — adoption's own planned writes excluded — and print the count as one budgeted mechanical reflow commit; the retirement section of the manual states the same cost.

**D8 — the translation rules name the autolink trap.** Typography gains a MUST: a bare URL or reference definition never sits directly before full-width punctuation or CJK text — bracket the link, use the angle form, or leave a half-width space. The gate is unchanged: the renderer swallows too, so the structural divergence it reports is a true warning.

**D9 — the flip procedure is documented.** Phase 3 states it: `git mv docs/foo.md docs/foo.zh.md` makes the existing bytes the Chinese side, then translate the English `docs/foo.md`, then record. No content-language heuristic detects such documents; the sizing note already counts them as outstanding English sources.

## Verification

Focused tests pin each path: a rejected credential still names the login remedy while a connection error keeps its exit status and stderr and never claims a missing credential, an absent gh names the install remedy in the resolvers and preflight alike, and an empty login fails loud; a recorded pair linking an unlanded sibling verifies green while a link naming no corpus file stays broken, the cross-link gate passes an unlanded `.zh.md` with an English sibling and rejects one without, the normalizer folds an unlanded sibling to the English anchor, and an English side's `.zh.md` spelling stays bare; a pre-existing real or Chinese template-pair side lands no counterpart, no record, and one note while adopt-installed sides still record on reapply; multiple divergences print in one run and hash drift no longer hides the structural finding; a gate-less CI is drift and a pinned `hdsh` install or `prek run` is not, `hdsh-ref:` inputs do not count, and no workflows is not drift; a hard-wrapped pre-existing corpus yields the reflow note and a reflowed one yields none.

## Alternatives considered

**A transient en-side fallback for pending pairs (D2).** Rejected: every sibling landing would force flipping links in every already-landed Chinese side and re-recording those pairs — the per-pair workflow would keep mutating finished pairs.

**Auto-retrying transient probes (D1).** Rejected: the hermetic transport and the offline fully-flagged run are contracts; an honest rerun hint reaches the same outcome without nondeterminism.

**Trimming full-width punctuation in the autolink scanner (D8).** Rejected: the scanner mirrors the renderer, and GitHub swallows the same characters — normalizing would make the gate pass a link that renders broken.

**Detecting Chinese-first documents by content (D9).** Rejected: a CJK-ratio heuristic would guess at authorship; the corpus count already prices the work and the procedure states the action.

**Warning instead of drifting on a gate-less CI (D6).** Rejected: an unenforced gate set is exactly the silent space the harness exists to close; the drift message carries the wiring recipe.

## Consequences

What the batch bought: preflight's verdict survives a network blip during plan; a translation batch lands pair by pair with every hook green, writing final-form links from the first day; apply never blesses content it never wrote, and a pre-existing architecture or development document carries no template to delete; one verify run carries the whole repair list, mid-edit included; the manual reads in execution order, prices the wrap reflow and the pairing corpus before apply runs, tells a CI-less adopter how to wire the gates, and gives Chinese-first documents a documented flip.

What the batch cost: ADOPT.md's word ceilings rise (740→900 English, 270→300 Chinese) for the reordered phases and the new procedures; done now includes wiring the gates into CI — a freshly adopted repository stays red in verify until then, where before the gap was invisible; Chinese sides linking unlanded siblings pass the cross-link gate, so mid-batch commits carry links that 404 until the target lands — the corpus-wide counterpart error, not the link, remains the tracker; and a shifted paragraph now reports every downstream index in its field, trading first-divergence quiet for completeness.
