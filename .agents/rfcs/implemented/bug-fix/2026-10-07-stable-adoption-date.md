# RFC: The adoption date belongs to the adoption, not the run

Status: implemented

English | [中文](2026-10-07-stable-adoption-date.zh.md)

## Problem

The adopt-RFC anchor derived from the wall clock on every `hdsh adopt apply` — the calendar of the configured Project time zone. The fifth adopter re-ran apply across midnight (2026-10-05→10-06, Asia/Shanghai) and received a second complete dated triplet beside the first: the original `2026-10-05-adopting-the-hdsh-harness.md` and its counterparts lingered outside the manifest's digest pinning while every transplanted corpus link moved to the new anchor. Nothing in the manifest recorded that the adoption already had a date.

## Decision

- The adopt manifest records `adoptDate` — the `yyyy-mm-dd` string as derived in the Project time zone, validated at load; empty only in manifests written before the field existed.
- Apply reuses the recorded date whenever it is present: the RFC anchor, `installed_destinations`, and every rendered template derive from the one date, and the run prints a note naming the reused date so the stability is visible rather than inferred.
- A manifest without the field — an adoption older than this change — derives the date from the Project time zone once, records it, and every later apply reuses it.
- The adoption manual states the once-only dating in both languages.

## Alternatives considered

**Delete the previous triplet when the anchor changes.** Rejected: re-application should never destroy decision records, and reuse makes the orphan question moot instead of answering it with cleanup.

**Derive the anchor from content rather than the date.** Rejected: the date prefix is the RFC tree's ordering convention — the filename carries the first-proposed date — and a second naming scheme for one record splits the corpus's mechanical rules.

**Record the full anchor path instead of the date.** Rejected: the anchor is a pure function of the date; storing the date keeps the manifest minimal and trivially validatable while the path would invite drift between the record and the derived destination.

## Consequences

What the change bought: re-application is date-stable — one triplet, corpus links that do not move, and no orphaned records after a midnight-crossing rerun; the reuse note makes the behavior observable in the run output.

What it cost: one more validated manifest field (a malformed `adoptDate` fails load loud), and a first re-apply under a pre-field manifest derives from the current clock — the pre-change behavior, exercised exactly once per old adoption.

## Verification

Manifest loader tests pin the field — absent defaults empty, a non-string fails loud with the field named, and a round trip preserves it. Apply tests pin the reuse — a monkeypatched next-day clock re-applies onto the recorded date, prints the reuse note, and writes no second anchor — and the migration — a fieldless manifest gets the derived date recorded, with the on-disk anchor matching it.
