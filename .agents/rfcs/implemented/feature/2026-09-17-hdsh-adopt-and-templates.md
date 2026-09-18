# RFC: hdsh adopt and the adoption template corpus

Status: implemented

English | [中文](2026-09-17-hdsh-adopt-and-templates.zh.md)

## Problem

Nothing assembled the harness for a consumer. The adoption knowledge was spread across the README hook example, the pairing contract, the RFC rules, and the skills; the assets a consumer needs — manifest seeds, thin policy workflows, issue templates, the RFC mechanism files, all ten skills, the documentation standard, the cookbook — were live files in this repository with no versioned distribution form. Hand-copying them is upgrade-hostile: copy and source drift, and every upstream improvement forks. The pieces that require consumer judgment — `docs/architecture.md`, `docs/development.md`, the root `AGENTS.md` — had no guided shape, so every consumer reinvented them. Two blockers compounded this: the policy workflow glue was not distributable ([now composite actions](2026-09-17-issue-policy-composite-actions.md)) and the merge driver pointed at a repository-relative script ([now a CLI entry](2026-09-17-pairing-merge-driver-cli-entry.md)). Missing were one command that installs the mechanical whole, one guided form for the judgment remainder, and one document that leads a consumer's AI agent from zero to a gated repository.

## Decision

### The adopt domain: plan, apply, verify

`hdsh adopt` registers three command leaves. `plan` preflights and prints the complete installation plan without writing a byte; `apply` writes it; `verify` compares the installed tree against the adopt manifest and counts remaining placeholders. Preflight-then-write keeps a failed adoption from leaving half a tree: every check runs first, and any blocker aborts the whole run with one diagnostic per blocker — which file, why it blocks, the suggested resolution. Checks refuse a non-git directory, a dirty worktree, a `.gitattributes` mapping that sends `*.i18n.yaml` to another driver, an ambiguous prek configuration (a legacy `.pre-commit-config.yaml`, invalid TOML, or a hand-pinned harness entry outside the adopt-managed block), and any target file that already exists with content adoption did not write. The prek entry is a marked `BEGIN`/`END` block — appended or replaced whole, never merged line-by-line — and revalidates the resulting TOML before writing.

### Templates are package data under an equality gate

The migratable corpus ships as package data inside the adopt domain, versioned with the installed hdsh; adopt reads nothing from the network — consumers bootstrap the CLI itself with `uvx --from git+...` at a pinned ref. An executed gate in this repository (`tests/adopt/test_templates.py`) proves each packaged mirror byte-equal to the live repository file it mirrors, so the two copies cannot drift silently — mirror maintenance is a cost the gate keeps honest.

### Three migration classes

Native assets are verbatim mirrors or parameterized generation: the RFC mechanism files with their folder skeleton, all ten skills, `docs/AGENTS.md`, the i18n contract set, the cookbook, the issue and pull-request templates, both `.hdsh` manifest seeds, the policy `config.json`, the prek block, and the `.gitattributes` line. Mirrored Markdown whose links resolve outside the installed set is rewritten at adoption time to tagged upstream URLs — per side, so a Chinese document keeps linking its Chinese upstream — and links inside the installed set keep their relative form.

Bilingual pairs — the RFC rules, the i18n contract, the translation rules, the cookbook, and the templated `architecture.md` and `development.md` pairs — are recorded in the consumer repository after writing, so their consistency records describe the rewritten bytes, not this repository's. An adopt-decision RFC triplet scaffold lands in `implemented/process/` with the adoption parameters rendered in.

Templated assets — `docs/architecture.md`, `docs/development.md`, the root `AGENTS.md` — ship as templates whose consumer-specific content is `TODO(adopt):` placeholders: greppable, each with a one-line completion instruction, and never occupying link-target positions, so the templates arrive gate-clean. An existing root `AGENTS.md` means the consumer already builds agent infrastructure: adopt skips that template without error and says so, leaving the merge of harness pointers into the existing file to the consumer's agent; the template ships the `run-relevant-checks-locally` anchor the reviewing skill links.

### The adopt manifest owns upgrades

`.hdsh/adopt.manifest.json` records the hdsh version, the pinned ref, the digest of every upstream-owned file, and the list of consumer-completable destinations. `verify` checks digests against the former and counts placeholders against the latter — completing a placeholder is the intended change, not drift. `apply` under a newer hdsh re-applies files unchanged on both sides, skips completed placeholder templates, and refuses consumer-modified generated files with guidance. Generated files are upstream-owned: consumers redirect changes upstream.

### ADOPT.md: the non-mechanical half

The root document [ADOPT.md](../../../../ADOPT.md) is a bilingual pair under the i18n contract and a new tier in the documentation standard: the consumer-side operating manual, named imperatively like CONTRIBUTING and SECURITY. It is a router — ordered phases, each with preconditions, actions, and verify commands — and it carries what cannot be mechanical: the out-of-git checklist (label taxonomy, Project board fields and statuses, secrets and variables, branch protection) as `gh` CLI commands for the consumer's agent to run and a human to confirm, plus the README-pairing and placeholder-completion work that completes the adoption. The root `ADOPT.md` joins the pairing corpus as a root-paired document alongside README and the community files.

### Engine support the corpus needed

Absolute `.zh.md` document URLs now compare at their `.md` anchor form in the pairing structural signature, mirroring the locale normalization relative corpus links already had — adoption rewrites each side's upstream references with its own locale suffix. The [domain-map RFC](../architecture/2026-09-07-domain-packages-and-unified-cli.md) gained the adopt domain in the same change.

### The version anchor

The engine the actions install, the templates adopt carries, and the manifest upgrades all pin to the same git ref (`--hdsh-ref`, or the repository's own default branch for self-hosting) until the first PyPI release; `ADOPT.md` documents the bootstrap and upgrade commands in those terms.

## Verification

`tests/adopt/` pins the plan/apply/verify round trip on a real scratch repository (including a pre-paired consumer README, recorded pairs, and a corpus-wide pairing check passing after apply), idempotent re-application, ref upgrades replacing unmodified files, the refusal of consumer-modified generated files, the root-AGENTS skip rule, every preflight blocker, the manifest loader's failure modes, the prek block and `.gitattributes` surgery, the token rendering per flavor, the link-rewrite rules including fenced code blocks, and the mirror equality gate. `tests/pairing/` pins the root `ADOPT.md` corpus scope and the absolute-URL anchor normalization; the policy tests pin the config-versus-event cross-validation the actions rely on.

## Alternatives considered

**Documentation-only adoption.** A guide without a command leaves every consumer hand-rolling the same file set; nothing verifies the result, and drift is undetectable — the upgrade complaint this record exists to close.

**Templates fetched from the git repository at adopt time.** Adds a network dependency and a supply-chain surface at install time; package data ships the exact version the consumer installed, with no fetch to trust.

**One-shot scaffold generation without a manifest.** Cookiecutter-style generation has no second act: nothing compares a later run against the first, so upgrades revert to manual re-diffing.

**A uniform digest check over every installed file.** Placeholder templates are meant to be completed; pinning their digest would flag the intended change as drift, so the manifest separates upstream-owned digests from consumer-completable destinations.

**A configurable corpus layout.** Pairing discovery reads every README plus `docs/**` and `.agents/rfcs/**`; making the layout configurable would widen the manifest surface to avoid a convention the harness legitimately prescribes. Adoption states the precondition instead.

## Consequences

- A consumer repository reaches every documentation gate green after `hdsh adopt apply`, its own README pair, and placeholder completion; upgrades are mechanical re-application, and the mirror corpus doubles every mirrored document with an executed gate keeping the copies honest.
- The ten-skill migration turns skill prose into distributed product; behavior-changing edits now carry consumer-upgrade consequences bounded by the adopt manifest, and mirrored-document edits must re-sync the package copies or the equality gate fails.
- A placeholder census can be emptied by deletion rather than completion; verify requires green gates alongside the census, so an emptied template fails elsewhere rather than passing silently.
- Adopt's preflight cannot validate out-of-git state — the Project board, labels, secrets — so a green adoption can still sit on an unconfigured repository until the ADOPT.md checklist is confirmed by a human.
