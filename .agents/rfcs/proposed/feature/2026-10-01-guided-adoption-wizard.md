# RFC: Derive adoption parameters and gate the out-of-git setup

Status: proposed

English | [中文](2026-10-01-guided-adoption-wizard.zh.md)

## Problem

`hdsh adopt plan` requires six flags for facts the consumer mostly cannot know from the command line, and Phase 2 of the adoption manual is a human checklist the tool cannot see; see [the adopt RFC](../../implemented/feature/2026-09-17-hdsh-adopt-and-templates.md) for the shipped design being extended. The failures arrive late and at the worst places: a wrong project number explodes at the repository's first issue event, an account-type mismatch fails inside every workflow run, missing gh or its stack capability is discovered at the moment a mirrored skill hard-stops, and nothing anywhere verifies the label taxonomy, the board shape, or the secrets. The first adoption needed a debugging session to discover what the tooling could have checked: the parameters are derivable, the GitHub state is queryable, and both `gh` and hdsh itself can be probed.

## Proposal

### Parameter resolution

- `--account-type` derives from the origin remote's owner type; a non-github.com origin remains a blocker.
- `--hdsh-ref` defaults to the latest upstream release tag and fails loud when none exists — upstream release discipline is a declared prerequisite, and there is deliberately no main-HEAD fallback.
- `--lifecycle-actor` derives from the Project credential's identity, because that credential is the identity whose Project mutations the lifecycle compares against; on the organization flavor it is captured at App creation.
- `--time-zone` defaults to the operator's local system zone; GitHub exposes no account time zone to read.
- Every derivation is echoed in the plan output, every flag remains an explicit override, and a fully explicit run stays offline — the hermetic e2e suite depends on that.

### Project creation and binding

- With no project configured, the wizard creates the board titled `"<repository> Issue Management"` with the seven standard statuses, the Priority field, and the Start date field.
- With a `--project-number` or a hand-authored `config.json` present, the wizard binds instead: it resolves the board under the derived owner and account type, validates the shape, and provisions missing statuses and fields through plan and apply.
- Binding captures the number into `config.json` and the Project node id and title into the adopt manifest as a verify-only anchor.
- The anchor never updates automatically: a config number that contradicts the anchor, or a resolved node id that no longer matches, is a blocker-level diagnostic naming the explicit rebind action. Renaming the board stays free — the title is display metadata, and the node id is the only immutable, rename-proof handle the runtime query already fetches.

### Credentials, labels, and preflight

- Credentials: on the user flavor a guided classic-PAT step — the one act the platform mandates a human perform — followed by `gh secret set`; on the organization flavor the App manifest flow (create, generate the key, install) followed by `gh variable set` and `gh secret set`. Verification of secrets, variables, token scopes and identity, board shape, and the label taxonomy is fully programmatic.
- Labels: the `kind/*` set, the initial `area/*` labels, and `type/*` on user accounts are created through `gh`; branch protection stays an explicit checklist item, never a silent mutation.
- Preflight layers, one blocker per failure with its suggested resolution on the existing Blocker ledger: the local toolchain (git 2.26+, an authenticated gh with the needed scopes, the stack capability, a runnable bare hdsh), the remote rendering dependencies (the ref resolves, the hdsh repository is reachable, external actions are allowed), and the GitHub-side state (labels, board shape, secrets and variables).
- Installation canon: consumers host-install hdsh, `uv tool install` until PyPI publication, and Phase 4 of the adoption manual is rewritten accordingly; preflight requires the bare command.

## Alternatives considered

**Interactive preference collection for the ref.** Rejected: adoption is executed by agents; the plan output is the collection surface — an agent reads the resolved defaults, overrides what it disagrees with, and reruns.

**Fall back to main HEAD when no release tag exists.** Rejected: it normalizes bleeding-edge gates for every early consumer, converts an upstream discipline failure into silent consumer risk, and makes two adoptions a day apart irreproducible. Loud failure is the honest signal and the cheaper one.

**Title equality as the wrong-board guard.** Rejected: the board title is consumer-editable by design, so the guard would turn every rename into a pipeline failure; the node id carries the same protection with none of the coupling.

**Per-event runtime node-id comparison.** Rejected: it buys a permanent runtime configuration field and a new runtime failure mode to protect against a manual-edit tail risk; verify-time checking covers the same risk at zero runtime cost.

**Fully automated credentials.** Impossible by the platform's design — PAT creation and App registration require owner consent — so automation belongs where it is possible: upload and verification.

## Acceptance criteria

- A fresh GitHub repository with gh and a host-installed hdsh reaches adopt verify green with no hand-typed parameter beyond choices the wizard asks for by name.
- A wrong project number fails at binding with a diagnostic naming both plausible causes.
- An anchor mismatch fails adopt verify naming the explicit rebind action; a renamed board passes unchanged.
- Preflight fails loud on each absent tool, scope, secret, label, and board field, one diagnostic per blocker.
- A fully explicit plan and apply pair runs offline.

## Risks

- adopt gains network and gh dependencies; the explicit-flag offline path keeps CI and the e2e suite hermetic, at the cost of two execution modes to test.
- Board auto-creation writes GitHub state before any file lands; the plan-then-apply discipline is the guard, and the plan prints the exact mutations.
- Derived defaults can be wrong on shared machines — a gh login that is not the intended actor; every derivation is echoed and overridable, which bounds the exposure to one reviewed plan output.
