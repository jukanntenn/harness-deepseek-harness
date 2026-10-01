# RFC: Make the adopted corpus transplantable and self-contained

Status: proposed

English | [中文](2026-10-01-transplantable-corpus.zh.md)

## Problem

`hdsh adopt` assembles the consumer corpus by mirroring hdsh's living documents and mechanically rewriting every link that leaves the installed set toward the pinned upstream ref — the design recorded in [the adopt RFC](../../implemented/feature/2026-09-17-hdsh-adopt-and-templates.md). The boundary is drawn by the rewriter after the fact, not by editorial judgment about audience, so repository-internal content leaks into consumer territory. Measured on the current corpus: twenty-eight outbound link rewrites across nine files, mostly citations of hdsh's own decision records; hdsh's community-file and adoption-manual rows inside the mirrored documentation standard; example links inside inline code spans rewritten into dead upstream URLs; `uv run hdsh` invocations that presume a project environment the consumer may not have; and skill text asserting hdsh's concrete toolchain — pytest, ruff, basedpyright, the tests/ layout — as if it were the consumer's. The design goal is the opposite: an adopted repository whose documentation system behaves as if hdsh did not exist, the way a self-contained directory still works after being moved anywhere.

## Proposal

Content specialization in the transplanted corpus follows one four-way model, and an executed gate holds the corpus to it.

### The specialization taxonomy

| Nature of the fact | Mechanism |
|---|---|
| Every repository needs its own value | Template with guided placeholders, gated until filled (the [placeholder-completion RFC](../feature/2026-10-01-guided-placeholder-completion.md)) |
| A carrier alive in both repositories exists | Single-source the fact to that carrier |
| The fact varies mechanically by deployment | Mechanical rewrite at adopt time |
| The consumer does not need the fact | Removed from the consumer form |

The rule that separates the middle rows: a fact with a both-alive carrier is single-sourced to that carrier, never duplicated into a template, because the second copy buys nothing and costs a sync gate; a fact whose value genuinely differs per repository becomes a placeholder, never a generalized pointer, because a pointer is not a value and the target may still be unfilled.

### Applications

- **Decision records move with what cites them.** The corpus cites four implemented RFCs; transitively they cite two more, and the closure of six records — twelve language files with six consistency records — moves as complete triplets, so every rationale link resolves inside the consumer repository. Their source-code citations become command references, the single-sourced carrier: `uv run hdsh pairing brief` is alive in both repositories while `src/hdsh/pairing/brief.py` is alive in one. The measured closure has no remaining outbound target once these citations are converted.
- **`rfcs/README` drops its three source-code links.** The commands and the class table in the same sentences already carry the same facts; the links add nothing for either audience.
- **`docs/AGENTS.md` becomes a template.** The hdsh-specific inventory rows — community files and the adoption manual — are removed and the `src/hdsh/` path is genericized; hdsh keeps its own live file, a deliberate divergence on the `architecture.md` precedent. This extends [the documentation-standard RFC](../../implemented/process/2026-09-07-adopt-documentation-standard.md).
- **The invocation prefix is mapped at adopt time.** `uv run hdsh ` becomes `hdsh ` throughout mirrored content, inside fenced examples as much as in prose — commands exist to be copied and run, unlike link examples. The authoring rule is one form per side: source corpus text writes the uv form only, and the gate rejects both bare hdsh invocations and non-hdsh uv commands. Consumers host-install hdsh, so the mapped form is the one that runs for them.
- **Hidden directories are not prose sources.** The enumerated non-source directory list becomes a class rule — any dot-prefixed path segment is out of corpus scope, with the explicit corpus prefixes excepted — so agent-tool mirrors such as `.zcode/` or `.claude/` never enter discovery, and the pairing manifest remains the valve for genuine exceptions.
- **The rewriter's link extraction moves to the markdown parser.** The pairing gate's parser already knows that inline code spans are not links; the rewriter adopts the same extraction instead of its raw regex, and the code-span defect class disappears instead of being patched around.
- **A self-containment gate holds the invariant.** An executed hdsh-side test asserts that rewriting is the identity over the movable corpus modulo the invocation mapping: zero outbound prose links, zero dead repository paths, moved triplets byte-stable. A new citation outside the closure fails the gate at authoring time, which is what turns this taxonomy from a discipline into a checkable contract.

## Alternatives considered

**Keep outbound citations as pinned references.** Rejected: the adopted system visibly depends on hdsh — a repository rename breaks every consumer's outbound links at once, and consumers read a frozen snapshot of hdsh's documents until re-adoption. The closed model needs no citations, because everything cited moves.

**Generalize toolchain wording into pointers such as the repository's command inventory.** Rejected when the first consumer hit it: a pointer is not a value, the inventory may still be an unfilled placeholder when it is followed, and hdsh's own skill text loses its concrete commands. This is the case that established the per-repo-value row of the taxonomy.

**Template the cited decision records with per-site rewrites.** Rejected: with a both-alive carrier — the command — the second copy buys nothing; it costs a modulo-site sync gate and a permanent fork of a decision record. Templating is reserved for facts that genuinely differ per repository.

**Normalize non-corpus links through a disk-existence fallback.** Rejected: the pairing signature would depend on incidental filesystem state, and the fallback silently blesses wrong-locale links that the corpus discipline exists to reject.

## Acceptance criteria

- The self-containment gate is green over the movable corpus: after rendering, zero outbound prose links and zero dead repository paths remain.
- The moved decision-record triplets verify unmodified under a consumer repository's pairing, RFC, and links gates.
- Inline-code examples land in the consumer repository byte-identical.
- Corpus text authored with a bare hdsh invocation, a non-hdsh uv command, or a citation outside the movable closure fails the gate with the rule named.
- A repository with hidden-directory bilingual documents opts in through the manifest roots valve rather than being discovered.

## Risks

- A permanent byte-delta between hdsh's live files and consumer copies — exactly the invocation mapping — adds one modulo dimension to every mechanical mirror check; it is small, deterministic, and unavoidable given single-source plus mapping.
- hdsh's shared documents lose inline source pointers; the code map stays with `architecture.md`, which the corpus never transplants, at the cost of one indirection for hdsh maintainers.
- The taxonomy is a discipline, not a type system: the gate proves the invariants it knows — outbound links, command forms, closure membership — but cannot prove that a newly added fact was classified into the right row; review still carries that judgment.
