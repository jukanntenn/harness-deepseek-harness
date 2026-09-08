# Bilingual documentation

English | [中文](README.zh.md)

This repo works in English, and its documentation is read by people and agents both inside and outside the project, so every document in scope is maintained as an English/Simplified-Chinese pair in which both languages carry equal authority. This page defines the pairing contract, checks, scope, and exclusions; [translation-rules.md](translation-rules.md) defines how to translate; [terminology.md](terminology.md) is the terminology source of truth. Routine agent work follows the lightweight path in [docs/AGENTS.md](../AGENTS.md); the extended [.agents/skills/translating-docs](../../.agents/skills/translating-docs/SKILL.md) workflow is available only through explicit user invocation.

<a id="the-pairing-contract"></a>

## The pairing contract

- **Both languages carry equal authority.** A document may be authored and reviewed in either language first — a Chinese-first RFC is as legitimate as an English-first one — and the counterpart is translated from it. Neither file outranks the other; what binds them is that they must say the same thing.
- **A pair is three sibling files.** The English `foo.md`, the Chinese `foo.zh.md`, and a consistency record `foo.i18n.yaml`, all in the same directory. No locale directories, no separate translation repo, no interleaved bilingual files. Pairs merge whole: a PR never lands one language without the other two files.
- **The consistency record.** `foo.i18n.yaml` holds the full git blob hash of each side as of the last time the two were confirmed to say the same thing:

  ```yaml
  foo.md: 3f786850e387550fdab836ed7e6dc881de23001b
  foo.zh.md: 89e6c98d92887913cadf06b2adb97f26cde4849b
  ```

  Blob hashes, not commit hashes, so the record is computable for files edited in the same PR (`git hash-object foo.md`) and consistency is a pure content comparison. Recording stores those snapshots in the local Git object database before writing the record, including uncommitted worktree contents, and pins every distinct stored blob under a content-addressed `refs/hdsh/pairing/snapshots/` ref so garbage collection cannot invalidate a recorded recovery pointer. The recorded hashes recover the exact last-confirmed text of either side (`git cat-file -p <hash>`), so an out-of-sync pair is updated by patching the counterpart minimally against the edited side's diff — never by re-translating whole files. Routine work makes that patch directly; when the user explicitly invokes the extended workflow, `uv run hdsh pairing brief <pair>` can instead assemble the update at the narrowest safely aligned granularity and `--apply` can splice a code-fence-only change after structural validation ([briefed-updates RFC](../../.agents/rfcs/implemented/process/2026-09-07-briefed-minimal-translation-updates.md)). After bringing the pair back in line, `uv run hdsh pairing record <pair>` re-records both hashes; that yaml diff is the reviewable act of confirming consistency, which is why `hdsh pairing record` requires naming the pairs you confirmed (`hdsh pairing record --all` is the explicit corpus-wide form) and a bare record run is rejected — it would silently bless every drifted pair in the tree.

  When two branches contain valid confirmations of the same pair, the `hdsh-pairing` Git merge driver (declared `merge=hdsh-pairing` for `*.i18n.yaml` in `.gitattributes` and registered worktree-locally by `uv run hdsh worktree install`) composes a new record only if Git's default text merge succeeds for both recorded owner-blob triplets and the merged pair retains its required switchers, link locales, and structural signature: the Chinese side must keep its English backlink, an authored English source must keep its Chinese link, and a manifest-`generated` English source is exempt. Any structure the driver cannot verify remains an ordinary conflict; `uv run hdsh pairing merge --resolve` applies the same fail-closed operation to a merge that has already stopped, stages every safe pairing record, and exits unsuccessfully when other pairing conflicts remain. The [bilingual pairing gate RFC](../../.agents/rfcs/implemented/process/2026-09-07-bilingual-pairing-gate.md) owns the mechanism and its alternatives.
- **Language switcher.** The Chinese file always links back immediately after its H1 heading with `[English](foo.md) | 中文`, and an authored English file reciprocates there with `English | [中文](foo.zh.md)`; a manifest-`generated` English source omits that line so it stays byte-identical to generator output, while its Chinese counterpart still links back. A README published outside GitHub, such as PyPI project metadata, may use the absolute URL the manifest's `public_blob_root` prefix configures for the same counterpart, so the switcher still resolves there.
- **Structure mirrors the counterpart.** Heading depths and order, list kinds, ordered-list starts, list item counts, table row and column counts, semantic link targets with exact query/fragment suffixes, and verbatim code blocks match one to one across the pair; generated regions delimited by `<!-- BEGIN GENERATED ... -->`/`<!-- END GENERATED ... -->` markers are byte-identical apart from paired-document locale paths, which normalize to the pair anchor before the comparison. When a relative document link targets the active bilingual corpus, the English side uses its `.md` path and the Chinese side uses its `.zh.md` path. A missing counterpart in that corpus is a pair-completeness error rather than a fallback; targets outside the active corpus keep the authored path. See [translation-rules.md](translation-rules.md) for the full preservation rules. The repo's Markdown conventions apply to `.zh.md` files unchanged: one physical line per paragraph (`uv run hdsh docs wrap`), resolving relative links (`uv run hdsh docs links`), and exactly one trailing newline.

## The gate: hdsh-pairing-verify

`uv run hdsh pairing verify` enforces the contract mechanically. This repo has no documentation-gate aggregate: prek runs the staged-record form as a fast local checkpoint, and CI runs the corpus-wide pairing check plus the RFC format gate:

1. Every document in scope has a complete pair. README discovery is case-insensitive on the basename and matches any directory, so future directories join the corpus without another manifest edit.
2. Every pair artifact that exists at all is complete and consistent: all three files present, each side's current blob hash equals the recorded one (editing either side without re-confirming the pair goes red), the Chinese side and every authored English source carry their language switchers (manifest-`generated` English sources are exempt), every ordinary relative document link uses its source side's target locale, and the structural signatures match in order — heading depths, verbatim code blocks (info string and content), table row and column counts, list kinds, ordered-list starts, item counts, and semantic link targets with exact query/fragment suffixes apart from the switcher, plus generated regions byte-identical beyond paired-document locale paths.
3. Files listed as `excluded` have no `.zh.md` and no `.i18n.yaml` at all. The frozen `.agents/rfcs/archived/` tree is a discovery exclusion; translation maintenance must never rewrite it.

`uv run hdsh pairing list` prints the current pairing state of every document in scope — missing, out-of-sync, or ok. It never fails; `missing` and `out-of-sync` rows identify violations that the normal check rejects.

`uv run hdsh pairing verify <pair...>` checks just the named pairs — any of a pair's three files (or its bare stem) names it — so an update loop verifies its own pair in seconds instead of re-scanning the corpus. `--cached <pairs...>` checks the exact staged index bytes of the named pairs; the prek hook runs it on staged `.i18n.yaml` records before every commit. The no-argument corpus-wide form is what CI runs; a scoped green never substitutes for it at PR level.

The practical rule this gate creates: **when a PR edits either side of a paired document, the same PR updates the counterpart directly in one terminology-guided pass and re-records the pair with `hdsh pairing record <pair>`**. A PR that leaves a pair out of sync goes red in CI.

The gate's limit, stated plainly: **a green gate means the pair was confirmed consistent at these exact contents, not that the confirmation was sound.** It checks hashes and Markdown structure; it cannot judge whether the two sides say the same thing, or whether the wording is accurate, well-termed, and natural — that is the reviewer's half of the contract, per [translation-rules.md](translation-rules.md). A re-recorded pair with a sloppy counterpart passes the gate; it must not pass review.

## Scope and exclusions

**Scope**: every README anywhere in the tree, every document under `docs/**`, and every document under `.agents/rfcs/**` (the RFC tree), minus the manifest exclusions below. Dependency, cache, build-output, and vendored trees are discovery exclusions, not translation sources.

**Excluded** (never paired, and the gate rejects a `.zh.md` or `.i18n.yaml` for them):

- `docs/AGENTS.md`, `.agents/rfcs/AGENTS.md`, `.agents/rfcs/implemented/AGENTS.md`, and `.agents/rfcs/archived/AGENTS.md` — agent instructions, maintained in English only; the root `AGENTS.md` likewise sits outside the corpus.
- [terminology.md](terminology.md) and [style-samples.md](style-samples.md) — the terminology table is a Chinese-side reference and the style samples are bilingual by construction; pairing cannot check either.
- `.agents/rfcs/archived/` — the whole frozen archive tree: sealed historical records kept for citation, never edited, translated, or re-recorded.

**Universal requirement**: every current or future document in scope must merge as a complete bilingual pair. [.hdsh/pairing.manifest.json](../../.hdsh/pairing.manifest.json) contains only an `excluded` array, an optional `generated` array naming generated English sources exempt from the English-side switcher, and an optional `public_blob_root` http(s) URL prefix accepting absolute-form switcher links — the parser rejects any other field — and there is no per-file rollout list, date cutoff, or README-specific policy class.

## Division of labor

Routine counterparts are updated directly by the working agent in one pass after it loads [terminology.md](terminology.md); it does not generate a briefing, run a separate translation-review pass, or delegate to a subagent. The extended [translating-docs](../../.agents/skills/translating-docs/SKILL.md) workflow retains those heavier mechanisms for explicit user invocation, and recovery is equally direct: recover the last-confirmed text with `git cat-file -p <hash>` and patch the counterpart minimally against the edited side's diff. The gate checks pair completeness, recorded hashes, both switchers (with the manifest-`generated` exception), link locales, generated-region equality, and the structural signature. Review still owns translation quality, terminology, and structural requirements that the signature does not encode.
