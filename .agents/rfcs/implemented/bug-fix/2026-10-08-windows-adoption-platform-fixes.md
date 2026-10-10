# RFC: Make the adopted gates line-ending-stable and runnable on Windows

Status: implemented

English | [中文](2026-10-08-windows-adoption-platform-fixes.zh.md)

## Problem

The first Windows adoption reported three platform defects that blocked both deployment paths, plus three adoption-experience defects surfaced by the same report. First, `zoneinfo` has no time-zone database on Windows, so `hdsh adopt plan --time-zone Asia/Shanghai` rejected a valid IANA zone — the diagnostic's own example — and the prek hook environment, which installs only declared dependencies, crashed loading `config.json` with `ZoneInfoNotFoundError`. Second, every tool-owned text write used `Path.write_text`, whose text mode translates `\n` to the platform line separator: on Windows the record command wrote CRLF sidecars that the gate's own parser rejects, so every installed pair read "malformed"/"out-of-sync" immediately after apply. Third, pairing records hashed raw working-tree bytes, so under `core.autocrlf` the same file flipped between CRLF and LF across tool invocations and the gate intermittently went red with zero content change; the reporter stabilized only by pinning `eol=lf` and renormalizing the corpus. The experience defects: `gh auth status` prints its scopes line behind a `- ` list marker, so the missing-`project`-scope notice never fired and preflight reported "ready" with a scopeless token; derivation blockers printed the wizard's message twice — once as the reason, again as the suggestion; and apply installed the template's default word budgets for pre-existing consumer documents, turning the budgets gate red on apply day for content adoption never wrote.

## Decision

- `tzdata` is a `sys_platform == 'win32'` dependency: it is `zoneinfo`'s only IANA source on Windows, so zone validation, the policy config load, and adoption dates work there; Linux and macOS keep reading the system database, and their resolution is unchanged.
- Every tool-owned text write lands through exact bytes (`write_bytes`): pairing sidecars, the adopt manifest, briefed counterparts, and the RFC seal manifest. Record sidecars always carry LF endings and parse under either ending, so a smudged checkout stays readable.
- Pairing records hash and store each side's line-ending-canonical bytes — CRLF pairs folded to LF, the clean-filter view. The worktree and index planes hash alike, an eol flip by any tool cannot push a confirmed pair out of sync, and on LF-committed trees the canonical form is the file itself, so existing records stay valid. Merge composition stores canonical blobs and compares staged and working content in canonical form; line-ending-only differences are no longer "unstaged content", while genuinely different staged merges still refuse. Consumers who recorded raw CRLF bytes with an older hdsh re-record once.
- The gh scope parser accepts both disclosure forms — the bare `Token scopes: ` line and gh's `- `-prefixed list line — and stays silent on any format it does not recognize.
- A failed derivation blocker prints the wizard message once, as the suggested resolution; the reason is the fixed "could not be derived" clause.
- Apply installs no `docBudgets` entry for a template pair judged consumer-owned; the plan output names the dropped destinations so the consumer knows to set a ceiling later.

## Verification

Unit tests pin the CRLF-tolerant record parse; the record command over CRLF content writes an LF-only sidecar and verifies green; an eol flip after recording stays green on both the worktree and index planes while real content drift under CRLF still goes red; the merge resolver tolerates an eol-only worktree flip yet still refuses skewed staged bytes; the bullet-form scope line earns the refresh notice and a project-carrying bullet line stays silent; the derivation-blocker diagnostic prints the wizard message exactly once; and apply with a pre-existing long document installs a docs manifest without its budget entries plus the naming note. The mirror-equality, pairing, docs, and RFC gates re-ran green on Linux.

## Alternatives considered

**Require consumers to pin `eol=lf` for the corpus.** Rejected as the mechanism: it makes gate correctness depend on every consumer editing `.gitattributes` correctly, and adopt deliberately does not own a repository's eol policy. Canonical hashing makes the gates indifferent to checkout configuration on every platform; the pinning remains optional consumer hygiene.

**Hash the git clean-filter output via a subprocess.** Rejected: it spawns one git process per file per check and returns the same bytes as folding CRLF→LF in the case that actually occurs; lone-`\r` or binary content never reaches a pairing record.

**Write with `newline="\n"` instead of `write_bytes`.** Equivalent on paper, rejected in form: `write_bytes` is total — there is no text-mode call site where a future writer can forget the argument.

**Derive the Windows time zone from the registry.** Rejected: the `--time-zone` flag already exists, the derivation surface stays one mechanism per platform class, and the blocker's diagnostic already names the remedy; ADOPT.md now says Windows passes the flag explicitly.

## Consequences

What the change bought: Windows adoption works end-to-end — plan validates zones, the hook environments load the policy config, recorded pairs stay green across checkout configurations on every platform, and the preflight notice, blocker diagnostics, and apply-day budgets behave as documented. What it cost: a consumer who recorded raw CRLF bytes under an older hdsh re-records each affected pair once, and a line-ending-only edit to a paired file is no longer flagged as drift by the pairing gate — by design, since the wrap gate and review still see the file itself.
