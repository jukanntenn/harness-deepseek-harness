# RFC: Community-friendly infrastructure

Status: implemented

English | [中文](2026-09-08-community-friendly-infrastructure.zh.md)

## Problem

The repository shipped governance gates for other projects while its own community surface was empty: no code of conduct, no contributing guide, no security policy or private reporting channel, no support routing, no Discussions venue, no review routing, and no repository description or topics. The README answered what the project does but not where to get help or who maintains it, and its consumer example drifted from the shipped hook manifest. A governance framework that models none of the community standards it could help enforce undermines its own pitch.

## Decision

### Community prose files live in `docs/` as gated bilingual pairs

`CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `SUPPORT.md` sit directly under `docs/`, each an English/Chinese pair with its consistency record. GitHub recognizes all four in `docs/`, so the community-standards checklist ticks without changing the pairing corpus: `docs/**` is already in scope, and the pairing, hard-wrap, and link gates cover the new files with zero engine changes. Mechanical files without prose twins stay in `.github/`: the pull-request template and `CODEOWNERS`.

### README completes the five community questions

The README keeps its what/how sections and adds the missing ones: a one-sentence value statement (conventions as mechanically executed checks, on organization and personal accounts alike), a Community & support section routing to Discussions, Issues, and private vulnerability reporting, a Contributing section naming the maintainer and the issue-first rule, and a License section. CI and License badges were added; the consumer example lists all seven shipped hooks with a pin-to-release-tag note (no release exists yet, so the note states the intent instead of naming a live tag — verified against the hook manifest).

### Contributor Covenant 2.1, verbatim, both languages

The code of conduct is Contributor Covenant 2.1 in English and its official Simplified-Chinese translation, unmodified beyond the language switchers; enforcement contact is jukanntenn@outlook.com. A verbatim standard text carries no word budget.

### CONTRIBUTING is an entry, not a second rulebook

The contributing guide carries the process skeleton — issue-first including typo fixes, RFC-in-the-same-PR, pairs move together, minimal commands, pull-request mechanics, acceptance scope, the explain-every-line attestation for AI-assisted work — and links AGENTS.md, the RFC rules, and the i18n contract as the authoritative homes instead of restating them.

### SECURITY routes to private vulnerability reporting only

Reporting goes through GitHub's private vulnerability reporting (enabled as a repository setting); the policy documents a 7-day acknowledgment, severity-paced fixes, coordinated disclosure through a published Security Advisory with Dependabot propagation, and reporter credit. The trust boundary is two-sided: issue and pull-request content is untrusted input to the policy workflows and exploits against it are in scope, while a consuming repository's own configuration files are its trust domain. Until a release is tagged, `main` is the only supported surface.

### SUPPORT routes by situation and states the anti-scope

A routing table sends usage questions to Discussions (English or Chinese both welcome; working language stays English), defects to the issue templates, and security to private reporting. The anti-scope names upstream tooling (prek, uv, GitHub Actions) and consumer governance decisions as out of help's reach, and states best-effort without SLA.

### Pull-request template gains two guardrail comments

Draft-early encouragement and the rule that undisclosed vulnerabilities never travel through public pull requests join the existing reference and priority comments; the issue templates stay as they are.

### Discussions hosts unformed conversation; RFCs own formed decisions

Discussions is enabled with the six default categories carrying curated copy — Announcements (maintainer releases and breaking changes), General, Ideas ("Feature ideas and direction discussions; valuable threads are distilled into an RFC, which links back"), Polls (opinion checks before bigger decisions), Q&A (usage questions; bug reports go to Issues), and Show and tell (consumer setups) — plus one pinned bilingual welcome post in General stating the three-venue split. The bridge rule: whoever drives a thread's consensus distills it into an RFC, and the RFC links the origin thread; misfiled items are converted between Issues and Discussions. The RFC rules themselves are unchanged — they govern records, not venues.

### CODEOWNERS routes review to the reviewing identity

`* @gh2bda` routes every change to the account that reviews and approves, matching the [identity model](../feature/2026-09-08-user-account-issue-policy.md): the developer identity (the account the agent is bound to) authors pull requests, the machine account reviews and approves in the browser, and an author cannot self-approve. The login names are deployment facts carried by the `CODEOWNERS` routing line and the policy config's `lifecycleActor`; this record binds the roles, not the usernames — switching to a different account setup changes those two facts, not the decision. Commented future-owner slots map the domain packages, and a trust-boundary note keeps `.github/workflows/` and `.github/issue-management/` maintainer-owned: they mint CI credentials and validate the trusted policy. Code-owner-required reviews stay off; one approval gate is one mechanism.

### Out-of-git assets are recorded here as the drift-proof inventory

The repository description ("Reusable governance gates for the Python ecosystem: GitHub issue/PR policy, bilingual documentation pairing, and pull-request workflow tooling, wired through prek") and the eleven topics — `python`, `pre-commit`, `pre-commit-hooks`, `github-actions`, `code-quality`, `documentation`, `i18n`, `governance`, `rfc`, `ai-agents`, `developer-tools` — plus the Discussions category copy, the welcome post, and the private-reporting toggle exist only as repository state; this record is their in-git source of truth. The social preview image is deferred until brand assets exist.

## Verification

`uv run hdsh pairing verify` covers the four new pairs and the re-recorded README pair; `uv run hdsh rfc verify` covers this record; `uv run hdsh docs wrap|links|budgets` cover the corpus with the new ceilings (README 600/600, CONTRIBUTING 550/550, SECURITY 350/350, SUPPORT 250/250). The consumer example's hook list was checked against `.pre-commit-hooks.yaml`. Out-of-git state was verified after landing: the community-standards checklist fully green, live topics matching this record, six categories matching the copy above, the welcome post pinned, and the Security tab exposing private reporting. `hdsh-rfc-archive` was confirmed to pass on a tree without `.agents/rfcs/archived/` content, keeping the all-seven-hooks example honest for consumers.

## Alternatives considered

**Community files at the repository root or `.github/`.** Outside the pairing corpus, their Chinese twins would escape every gate — the exact rot the gates exist to catch; `docs/` placement is recognized by GitHub and already gated.

**YAML issue forms for community-facing reports.** The engine's body contract (at most 50 visible units outside one collapsed details region) applies to every issue, and form-generated bodies put user input outside any collapsed region; the post-hoc audit is the enforcement, so the markdown templates stay.

**A separate RFC pull request before implementation.** The design was settled topic-by-topic with the maintainer before any artifact existed; the same-PR rule and the implemented/proposed discriminator ("a decision already made starts in implemented/") make one pull request correct. The two-phase form stays right for genuinely new, undiscussed designs.

**An English-prevails note on the Chinese Covenant.** The pairing contract grants both languages equal authority; the standard translation practice of preferring the source text was dropped to keep that contract intact.

**`* @jukanntenn` in CODEOWNERS.** Routes review requests to the author, who cannot self-approve; the benchmark rule adapted to this identity polarity points at the account that actually reviews.

**Topic words for internal process (ci, automation, lint).** dcs's precedent — every topic is a word a consumer searches or browses by; process-internal words attract no audience.

**Requiring code-owner reviews in branch protection.** Duplicates the existing one-approval gate; one mechanism, not two overlapping ones.

## Consequences

- The community surface is fully bilingual and gate-enforced: four more pairs must move together forever, and their word ceilings force future additions to relocate rather than accrete.
- Out-of-git assets can silently drift from this record — category copy, welcome post, topics, and the reporting toggle have no mechanical check; the record is the comparison source for periodic audits, the same failure mode the benchmarks documented.
- The issue templates stay minimal by explicit deferral: enriching fields inside the collapsed region remains available without touching policy, and the decision to do nothing is revisited when real intake friction shows.
- The README consumer example references the not-yet-existing first release tag by intent rather than name; cutting v0.1.0 later turns the note into a literal tag with a one-word edit.
- Discussions adds a moderation surface to a sole maintainer: the Q&A and Ideas copy deliberately pushes bug reports and trackable work back into Issues, where templates and the policy engine carry the load.
