# RFC: Derive adoption parameters and gate the out-of-git setup

Status: implemented

English | [中文](2026-10-01-guided-adoption-wizard.zh.md)

## Problem

`hdsh adopt plan` required six flags for facts the consumer mostly cannot know from the command line, and Phase 2 of the adoption manual was a human checklist the tool cannot see; see [the adopt RFC](../feature/2026-09-17-hdsh-adopt-and-templates.md) for the shipped design being extended. The failures arrived late and at the worst places: a wrong project number exploded at the repository's first issue event, an account-type mismatch failed inside every workflow run, missing gh or its stack capability was discovered at the moment a mirrored skill hard-stops, and nothing anywhere verified the label taxonomy, the board shape, or the secrets. The first adoption needed a debugging session to discover what the tooling could have checked: the parameters are derivable, the GitHub state is queryable, and both `gh` and hdsh itself can be probed.

## Decision

### Parameter resolution

- `--hdsh-ref` defaults to the latest upstream release tag (`git ls-remote --tags` filtered to `vX.Y.Z`, highest wins) and fails loud when none exists — upstream release discipline is a declared prerequisite, and there is deliberately no main-HEAD fallback. The upstream repository still carries no tag at the time of this writing, so every early consumer passes the flag explicitly; the default activates with the first tagged release.
- `--account-type` derives from the origin remote's owner type through `gh api repos/{owner}/{repository}`; a non-github.com origin remains a blocker.
- `--lifecycle-actor` derives from the authenticated gh identity — the credential that will write Project mutations is the identity the lifecycle compares against.
- `--time-zone` defaults to the operator's local system zone read from the `/etc/localtime` link; GitHub exposes no account time zone to read.
- Every derivation is echoed in the plan output, every flag remains an explicit override, and a fully explicit run stays offline — the hermetic e2e suite depends on that, and it is pinned by test.
- An existing `config.json` remains the binding input it became under the [configuration-ownership RFC](2026-10-01-consumer-configuration-ownership.md); absent flags no longer conflict with it — only a passed flag that contradicts a file value is a blocker.
- `--project-number` and `--project-title` stay hand-typed: the board identity is the one thing only the consumer (or a future board-creation step) can state.

### The binding anchor

- Apply records the resolved project number into the adopt manifest as `projectAnchor` — the board binding.
- Verify compares `config.json`'s `projectNumber` against the anchor: a mismatch means the consumer moved boards, and the diagnostic names the explicit rebind action — rerun apply under the new number. The anchor never updates silently; a rename of the board stays free because the number is the address, not the title.
- The node-id identity guard and the network-side bind/shape-validation flows remain proposed work: they need live GitHub state, and the offline anchor conflict check covers the misconfiguration class the first adopters actually hit.

### Preflight and the installation canon

- `hdsh adopt preflight` runs the local-toolchain layer — git runnable, gh authenticated, bare hdsh on PATH — one diagnostic per failure, each naming the installation step.
- The installation canon is host-installed hdsh (`uv tool install` until PyPI publication); Phase 4 of the adoption manual was rewritten accordingly, and the manual now leads Phase 1 with the host-install step and the preflight check.
- Credentials, label creation, and board-shape validation remain the manual Phase 2 checklist: they are the platform-mandated owner-consent steps the wizard cannot and should not automate away, and their programmatic verification belongs to the same future bind step as the node-id guard.

## Verification

Focused tests pin each resolution through an injected transport: the flag always wins; the latest release tag is the ref default and a tagless upstream fails loud with no main fallback; owner types map to flavors and an unreadable owner fails loud; the gh identity derives the actor and an unauthenticated gh fails; the local time zone links to its IANA name and an unlinkable zone fails; preflight reports one diagnostic per absent tool and none when ready. Integration tests pin the echoes in plan output, the fully flagged offline run, the anchor recorded at apply, the moved-board conflict naming the rebind action, and a non-board edit raising no conflict. The real-world probe confirmed the loud-failure path: a tagless upstream and an unauthenticated gh each produce their named blocker.

## Alternatives considered

**Interactive preference collection for the ref.** Rejected: adoption is executed by agents; the plan output is the collection surface — an agent reads the resolved defaults, overrides what it disagrees with, and reruns.

**Fall back to main HEAD when no release tag exists.** Rejected: it normalizes bleeding-edge gates for every early consumer, converts an upstream discipline failure into silent consumer risk, and makes two adoptions a day apart irreproducible. Loud failure is the honest signal and the cheaper one.

**Title equality as the wrong-board guard.** Rejected: the board title is consumer-editable by design, so the guard would turn every rename into a pipeline failure; the number is the address and the anchor carries it.

**Fully automated credentials.** Impossible by the platform's design — PAT creation and App registration require owner consent — so automation belongs where it is possible: the preflight probes and the manual's Phase 2 ordering.

## Consequences

What the change bought: a consumer with gh and a host-installed hdsh types two parameters instead of six; every derived default is visible in the plan before anything lands; a wrong board number is caught at verify with the rebind action named instead of surfacing at the first issue event; the toolchain gaps preflight names are the gaps that used to surface as mid-workflow hard stops; and the manual finally states the installation canon it expects.

What the change cost: adopt gained a network-dependent path, contained by the flag-first resolution order and the offline guarantee for fully flagged runs — two execution modes to keep tested; the anchor stores the number only, so a same-number board replacement (deleted and recreated) is invisible to the offline check and waits for the node-id guard; and the credential, label, and board-shape verification remain manual checklist items whose automation is deliberately deferred rather than silently dropped.
