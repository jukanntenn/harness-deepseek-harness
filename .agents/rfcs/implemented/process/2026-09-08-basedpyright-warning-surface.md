# RFC: The basedpyright warning surface: typed doubles and a tests-only private-access exemption

Status: implemented

English | [中文](2026-09-08-basedpyright-warning-surface.zh.md)

## Problem

The type gate (`uv run basedpyright`, as a pre-push hook and in CI) runs with `typeCheckingMode = "all"` and reported 251 diagnostics — every one inside `tests/`, none inside `src/`. Each sat at severity `warning` because the tests execution environment downgraded twelve rules to `"warning"` on the assumption that warnings are advisory; but basedpyright's `"all"` mode enables `failOnWarnings` by default, so every warning failed the CLI anyway. The downgrades therefore carried no weight, the repository could not pass its own type gate on its first push, and the intended policy — strict on `src/`, tolerant of deliberate test doubles — existed only as an unverifiable assumption. Two further facts hid underneath: basedpyright does not honor `# type: ignore` comments at all, so the suite's one suppression was dead text, and the downgrade set had quietly widened beyond white-box private access to a dozen unrelated rules, discarding signal the tests can afford to meet, `reportArgumentType` included.

## Decision

The gate keeps its strictness; the noise is fixed, not relaxed away. `failOnWarnings = true` is explicit in the configuration, so any error or warning fails `basedpyright` in pre-push and CI regardless of future basedpyright defaults. The tests execution environment exempts exactly two rules, `reportPrivateUsage` and `reportPrivateLocalImportUsage` (`"none"`): tests exercise private contracts and patch module internals directly — the same white-box stance the ruff per-file ignores for `tests/**` already encode with `SLF001` and `ARG` — and the exemption is scoped to those two rules under `tests/` alone. Every other diagnostic keeps its strict default everywhere, and the `src/` environment stays untouched.

Reaching zero warnings brought the suite to the standard the gate already claims. The 140 `reportUnknownLambdaType` diagnostics came from stub lambdas whose parameters Python syntax cannot annotate; they are now typed defs mirroring the patched function's real signature, and the repeated fixed-result `subprocess.run` doubles share one generic `completed_run` helper in `tests/helpers.py`. Unused captures were dropped or underscore-prefixed, test-double class attributes annotated, one dead nested helper deleted, and the one duck-typed base-class delegation is suppressed with `# pyright: ignore[reportArgumentType]` beside `# ty: ignore[invalid-argument-type]` — the pyright-form comment being the only kind basedpyright honors.

## Verification

`uv run basedpyright` reports 0 errors, 0 warnings, and exits 0. `uv run pytest` passes 991 tests under the 100% branch-coverage gate with no behavior change, and `uv run ruff check .` plus `uv run ruff format --check .` stay clean. `uv run ty check` passes unchanged.

## Alternatives considered

**`failOnWarnings = false` (advisory warnings everywhere).** The knob is global-only — execution environments override rule severities, not exit behavior — so `src/` warnings would also stop blocking, and a future real defect could ship as a warning. The relaxation must minimize the error surface, so it goes the other direction: fix the suite, exempt one rule family in one environment.

**`--level error` in the gate commands.** The same over-broad relaxation, plus it hides warnings from the output entirely, so the diagnostics lose even their advisory visibility.

**Keeping the twelve-rule `"warning"` downgrades.** They encode the assumption that warnings are advisory, which `"all"` mode's `failOnWarnings` denies; under a blocking gate every downgrade still fails, so the configuration documents a policy that does not exist. Most downgraded rules — unused variables, unannotated attributes, unknown lambda types — are satisfiable in tests at the cost of typing effort only, so the downgrades discard signal the suite can afford to meet.

**basedpyright's baseline feature.** Baselining the 251 diagnostics freezes the noise instead of removing it, auto-updates the baseline as diagnostics decline (masking regressions in the same run), and adds a moving artifact to review. The suite was small enough to fix outright.

**Exporting the private names tests reach for.** Widening `src/` exports to satisfy tests inverts the ownership: the private contract is the thing under test. The scoped exemption documents that stance instead.

**Suppressing per site with ignore comments.** `# type: ignore` is inert under basedpyright, so per-site suppression would sprinkle `# pyright: ignore` through every double; typed signatures document each doubled contract, keeping the one unavoidable suppression an exception.

## Consequences

- `basedpyright` blocks on any error or warning in `src/` and `tests/` alike; the only silence is the two private-access rules under `tests/`. New warnings surface in the author's pre-push hook with no baseline file to update and no threshold to negotiate.
- Test doubles must keep fully typed signatures. This matches the existing ruff `ARG` per-file ignore — fake transports and protocol doubles must keep full signatures — and turns that convention into a type-checked requirement; `completed_run` is the shared shape for fixed-result `subprocess.run` doubles.
- Suppressions in this repository use `# pyright: ignore[rule]`, plus `# ty: ignore[code]` for the secondary checker; `# type: ignore` comments are inert under basedpyright and must not be relied on.
- The tests environment configuration shrinks from twelve downgrades to two exemptions, so the configuration now states the real policy: white-box private access is deliberate, and everything else is held to the strict default.
