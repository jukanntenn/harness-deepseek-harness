# RFC: Make the adopted corpus transplantable and self-contained

Status: implemented

English | [中文](2026-10-01-transplantable-corpus.zh.md)

## Problem

`hdsh adopt` assembles the consumer corpus by mirroring hdsh's living documents and mechanically rewriting every link that leaves the installed set toward the pinned upstream ref — the design recorded in [the adopt RFC](../feature/2026-09-17-hdsh-adopt-and-templates.md). The boundary is drawn by the rewriter after the fact, not by editorial judgment about audience, so repository-internal content leaks into consumer territory. Measured on the corpus at the time: twenty-eight outbound link rewrites across nine files, mostly citations of hdsh's own decision records; hdsh's community-file and adoption-manual rows inside the mirrored documentation standard; example links inside inline code spans rewritten into dead upstream URLs; invocations presuming hdsh's project environment; and skill text asserting hdsh's concrete toolchain as if it were the consumer's. The design goal is the opposite: an adopted repository whose documentation system behaves as if hdsh did not exist, the way a self-contained directory still works after being moved anywhere.

## Decision

Content specialization in the transplanted corpus follows one four-way model, and an executed gate holds the corpus to it.

### The specialization taxonomy

| Nature of the fact | Mechanism |
|---|---|
| Every repository needs its own value | Template with guided placeholders, gated until filled (the [placeholder-completion RFC](../feature/2026-10-01-guided-placeholder-completion.md)) |
| A carrier alive in both repositories exists | Single-source the fact to that carrier |
| The fact varies mechanically by deployment | Mechanical mapping at transplant time |
| The consumer does not need the fact | Removed from the consumer form |

The rule that separates the middle rows: a fact with a both-alive carrier is single-sourced to that carrier, never duplicated into a template, because the second copy buys nothing and costs a sync gate; a fact whose value genuinely differs per repository becomes a placeholder, never a generalized pointer, because a pointer is not a value and the target may still be unfilled.

### What shipped

- **Decision records move with what cites them.** The corpus cites four implemented RFCs; transitively two more, and the closure of six records moves as mirrored pairs — adopt transplants both language files and records the pair in the consumer repository. Their source-code citations became command references, the single-sourced carrier: `uv run hdsh pairing brief` is alive in both repositories while `src/hdsh/pairing/brief.py` is alive in one. The measured closure has no remaining outbound target.
- **`rfcs/README` dropped its three source-code links.** The commands and the class table in the same sentences already carry the facts.
- **`docs/AGENTS.md` became a template.** The hdsh-specific inventory rows — community files and the adoption manual — are removed and the source path is genericized; hdsh keeps its own live file, a deliberate divergence on the `architecture.md` precedent. A pre-existing consumer `docs/AGENTS.md` takes the standing-orders treatment: skipped, tracked as a pending merge, anchors named. This extends [the documentation-standard RFC](../process/2026-09-07-adopt-documentation-standard.md).
- **The invocation prefix is mapped at transplant time.** `SOURCE_INVOCATION` (``uv run hdsh ``) maps to `CONSUMER_INVOCATION` (``hdsh ``) across mirrored Markdown, inside fenced examples as much as in prose — commands exist to be copied and run. The authoring rule is one form per side: the source corpus writes the uv form only, and the gate rejects bare backticked invocations in the mirrors. The rejection of non-hdsh `uv run` commands in the mirrored corpus lands with the placeholder-completion program, which converts the two skills still carrying hdsh's development commands into slot templates — recorded there as that program's amendment.
- **Hidden directories are not prose sources.** The enumerated non-source directory list became the class rule — any dot-prefixed path segment marks machine-owned territory and stays out of the corpus, with `.agents/rfcs/` the explicit exception — so agent-tool mirrors such as `.zcode/` or `.claude/` never enter discovery, and the pairing manifest remains the valve for genuine exceptions.
- **A self-containment gate holds the invariant.** An executed hdsh-side test walks every mirrored document and asserts that transplanting is the identity modulo the invocation mapping — zero outbound prose links, zero upstream blob URLs — that the source keeps the uv form only, and that every cited decision record ships with the corpus. A new citation outside the closure fails the gate at authoring time, which is what turns this taxonomy from a discipline into a checkable contract.

Two amendments against the proposal, recorded where they apply: the rewriter's link extraction keeps its link grammar with inline code spans masked by the CommonMark backtick-run rule rather than swapping wholesale to the markdown parser — the identity gate, not the extractor's pedigree, is the enforceable invariant, and the masked grammar is that rule for every span in the corpus; and the non-hdsh `uv run` authoring rejection is staged with the placeholder program named above, because that program is what makes the corpus satisfiable.

## Verification

The self-containment gate is green over the movable corpus: after rendering, zero outbound prose links and zero dead repository paths remain. The moved decision-record triplets verify unmodified under a consumer repository's pairing, RFC, and links gates — pinned by the adopt round-trip tests, which also assert the transplanted README carries the consumer invocation form and no upstream blob URL. Inline-code examples land byte-identical (the first-adopter batch's code-span fix, kept). Corpus text authored with a bare backticked invocation fails the authoring assertion with the file named. A repository with hidden-directory bilingual documents opts in through the manifest `roots` valve rather than being discovered.

## Alternatives considered

**Keep outbound citations as pinned references.** Rejected: the adopted system visibly depends on hdsh — a repository rename breaks every consumer's outbound links at once, and consumers read a frozen snapshot of hdsh's documents until re-adoption. The closed model needs no citations, because everything cited moves.

**Generalize toolchain wording into pointers such as the repository's command inventory.** Rejected when the first consumer hit it: a pointer is not a value, the inventory may still be an unfilled placeholder when it is followed, and hdsh's own skill text loses its concrete commands. This is the case that established the per-repo-value row of the taxonomy.

**Template the cited decision records with per-site rewrites.** Rejected: with a both-alive carrier — the command — the second copy buys nothing; it costs a modulo-site sync gate and a permanent fork of a decision record. Templating is reserved for facts that genuinely differ per repository.

**Normalize non-corpus links through a disk-existence fallback.** Rejected: the pairing signature would depend on incidental filesystem state, and the fallback silently blesses wrong-locale links that the corpus discipline exists to reject.

## Consequences

What the change bought: an adopted repository's documentation resolves entirely inside itself — rationale links land on the transplanted decision records, commands run under the consumer's installation, and nothing points back at hdsh; the identity gate makes regression a test failure rather than a consumer's discovery; hidden-directory tool mirrors stopped entering the corpus by default; and the documentation standard finally describes the adopter's tree instead of hdsh's.

What the change cost: a permanent byte-delta between hdsh's live files and consumer copies — exactly the invocation mapping — adds one modulo dimension to every mechanical mirror check; hdsh's shared documents lost their inline source pointers, so the code map lives entirely with `architecture.md`, which the corpus never transplants; the taxonomy remains a discipline rather than a type system — the gate proves the invariants it knows (outbound links, invocation forms, closure membership) but cannot prove that a newly added fact was classified into the right row, and review still carries that judgment.
