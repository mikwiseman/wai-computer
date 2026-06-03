# Test Coverage → ≥95% — Multi-Platform Plan

## 🎯 Goal (read this first)

**Mission:** Raise automated **test coverage to ≥95% on every platform in this repository that has tests** — backend (Python), web (TypeScript), Swift (`WaiComputerKit`), Android, macOS, and iOS — measured on **testable logic** (pure UI view bodies, hardware audio I/O, and generated code are excluded from the denominator; see §2).

**Repository:** `wai-computer` — "WaiComputer", an AI second-brain for recordings, transcription, search, and summaries. Conventions live in `AGENTS.md`.

**Definition of done (per platform):**
1. The platform's full test suite is **green** — no failing or flaky tests.
2. Measured coverage of in-scope code is **≥95%**, confirmed by two consecutive measures (flake guard).
3. The gate is **encoded** (config threshold + CI/pre-push hook) so it cannot silently regress.
4. Tests are **committed** — one commit per platform / logical step.

**Hard rules (non-negotiable — from `AGENTS.md` + repo norms):**
- **No fallbacks.** Surface errors; no silent degradation or masking defaults.
- **Never weaken a test to hit the number.** If a test fails, fix the *source* or assert the *correct current behavior* — do not delete assertions, loosen matchers, or lower expectations to go green. Trivial smoke tests that don't exercise real branches do not count.
- **Don't alter product code to game coverage.** Exclusions are configured with a documented reason, never by deleting features. Test-only refactors (e.g. injecting a protocol seam) need sign-off — see decision **D2** (§7).
- **Privacy-safe tests:** never log or commit real emails, tokens, transcript text, search queries, or filenames (`AGENTS.md` → Observability).

**⛔ Before writing any test, resolve decision D1 (§7):** the code is fragmented across **7 git worktrees** and the baselines in this plan were taken on a **frozen** branch. Confirm **which branch/tree is the campaign target** (recommended: `main`, after the in-flight feature branches land). Testing the wrong tree wastes the entire effort.

**How to use this document:** §1 = repo state you must understand → §2 = what counts toward 95% → §3 = measured baselines → §4 = per-platform playbook (commands, gap tables, approach, host needs) → §5 = how to execute (workflow pattern) → §8 = copy-paste measure commands. If you're assigned one platform, jump to its §4 entry — but read §1, §2, and D1 first.

> **Status: PLAN ONLY — nothing here is implemented.** Authored 2026-06-02.
> **Author note:** baselines below were measured on this worktree (`feat/tbank-recurrent-compliance` @ `a3ade447`) on 2026-06-01. See §1 — the bulk of the last-24h code lives on *other* branches, so the campaign target must be chosen before mass test-writing starts.

---

## 0. TL;DR snapshot

| Platform | Tooling | Measured baseline | Target | Reachable on this Mac? | Effort |
|---|---|---|---|---|---|
| **Backend** (Python) | pytest + coverage | **95.00%** ✅ (1876 pass) | 95% (gate already enforced) | ✅ | maintain only |
| **Web** (TS) | vitest v8 | ~70.6% lines, thresholds 75/75/60/75 | 95% + raise thresholds | ✅ | medium |
| **Swift** (WaiComputerKit) | swift test + llvm-cov | **47.6%** lines (5,400 uncovered) | 95% (after UI/HW exclusions) | ✅ | **large** |
| **Android** | gradle + (jacoco TBD) | not measured (no jacoco yet) | 95% unit | ✅ unit / ❌ instrumented (no emulator) | medium + setup |
| **macOS** (XCTest) | xcodebuild + xccov | not measured | 95% | ✅ | medium |
| **iOS** (XCTest) | xcodebuild + xccov | **no test target exists** | 95% (needs target first) | ⚠️ needs simulator | large |

Bottom line: backend is done; web is tractable; **Swift and iOS are the big lifts** (Swift is a 10k-line Kit at 48%; iOS has zero tests today).

---

## 1. ⚠️ Critical context — the repo is fragmented across 7 worktrees (24h churn check)

The last ~24h saw **massive parallel development**, but **almost none of it on this branch.** `git worktree list` + `git log --all` show:

| Worktree | Branch | HEAD | Activity in last 24h |
|---|---|---|---|
| `wai-computer` (this) | `feat/tbank-recurrent-compliance` | `a3ade447` (2026-06-01 10:51) | **frozen** — no new commits |
| `wai-voice` | `feat/voice-computer-use-agents` | `48396877` | **very active** — voice computer-use agents, ElevenLabs custom-LLM bridge, desktop actuators, companion actions loop |
| `wai-mat-brain` | `feat/sb-materials-brain` | `42545457` | **very active** — Brain graph/wiki/entity pages, Person↔Entity reconcile, comparison builder, media upload |
| `wai-ios-parity` | `feat/ios-mac-parity` | `d5bb6a2c` | active — iOS Brain/Library features |
| `wai-transcription-fix` | `fix/transcription-stability` | `280f6b51` | active (a concurrent session was running `swift test` here) |
| `wai-parity` | `main` | `dd4c6497` | the integration trunk |
| `.claude/worktrees/wf_95214aae-632-{1..4}` | workflow scratch | `f055d437` | ephemeral workflow worktrees (another run) |

**Directories with the most committed churn (last ~30h, all branches):**
`backend/tests` (105), `backend/app/core` (59), `web/src/components` (50), `shared/WaiComputerKit/Tests` (20), `backend/app/api/routes` (27), `ios/.../Features/Brain` (12), plus migrations + models.

### Implications for the coverage campaign (must read)

1. **The baselines below are for a frozen branch.** The code that actually needs coverage (voice agents, materials-brain, etc.) is on branches that are still moving. Driving *this* branch to 95% would test code that may be superseded at merge.
2. **Other sessions are already adding tests** (`backend/tests` +105 files touched, `shared/WaiComputerKit/Tests` +20). A campaign here would collide/duplicate.
3. **A single integration target is required** before mass test-writing. See §7 Decision D1.

### Recommended strategy (pending Mik's call — D1)

- **Do not run the campaign on this `tbank` branch.** Treat the work done so far (web test fixes) as salvageable patches, not the campaign.
- **Primary path:** let the in-flight feature branches land on `main`, then run the per-platform campaign on `main`. Add a **pre-merge per-branch coverage gate** so new feature code arrives already-tested (cheaper than back-filling later).
- **If v1.0 can't wait for all merges:** pick the single branch that will *become* v1.0 and drive that, rebasing the test work forward.

---

## 2. Coverage scope policy — what counts toward 95%

Target **≥95% on testable logic.** Exclude from the denominator (mirrors existing repo precedent: backend already omits `app/db` + `app/models`; web counts only `src/`):

**Excluded (not headlessly unit-testable / not logic):**
- Pure SwiftUI / Compose **view bodies** (e.g. `CompanionView.swift` = 1,671 lines at 0.8%). Cover via snapshot/UI tests separately, not unit %.
- **Direct hardware audio I/O**: `SystemAudioCapture`, `AudioEngineHost`, `DualAudioCapture`, `RealtimePCMEncoder` (Swift); Android `AudioRecord`. These need real devices / CATap and silently no-op in CI.
- **Generated code** (`*.g.cs`, `obj/`, SwiftGen output), **DI-only protocol declarations**, **Compat shims** (`OnChangeCompat`, `ContentUnavailableViewCompat`).

**In scope → drive to ≥95%:** networking/clients, models & (de)serialization, parsing, billing, sync coordinators, view-models, localization, sanitizers, stores, routing/business logic.

> Mechanism: encode exclusions in each platform's coverage config (coverage `omit`, `-ignore-filename-regex`, vitest `coverage.exclude`, jacoco `excludes`, xccov target scoping) — **not** by deleting code. Document every exclusion inline with a reason.

---

## 3. Measured baselines (this branch, 2026-06-01) + caveats

- **Backend:** `TOTAL 12272 stmts / 595 miss = 95.00%`; 1876 passed, 1 skipped; **full suite ≈ 8.5 min**. Gate `--cov-fail-under=95` already enforced (`backend/pyproject.toml`). Omits `app/db/*`, `app/models/*`.
- **Web:** baseline **70.57% lines** (vitest v8, `src/**`). Current thresholds in `web/vitest.config.ts`: lines 75 / functions 75 / branches 60 / statements 75.
- **Swift:** **47.55% lines** (regions 48.08%); 10,296 lines, 5,400 uncovered; 41 of 52 source files <95%; 464 tests already pass.
- **Android / Apple:** not yet measured (heavy native builds were deferred).

**Caveat:** valid only for `a3ade447`. Re-measure on the chosen integration target (§1/D1) before acting.

---

## 4. Per-platform plans

### 4.1 Backend (Python) — DONE / maintain
- **State:** 95.00%, gate enforced. No action beyond keeping it green as features merge.
- **Measure:** `cd backend && source .venv/bin/activate && pytest -q --cov=app --cov-report=term-missing`
- **Watch:** it's *exactly* at 95.00% — zero margin. New uncovered lines from merges will break the gate. Add a small buffer (target ~96–97% internally) when feature branches land.

### 4.2 Web (TypeScript / vitest)
- **Baseline:** 70.6% → **95%**. Threshold bump required afterward.
- **Measure:** `pnpm -C web vitest run --coverage --coverage.reporter=json-summary --coverage.reporter=text` → parse `web/coverage/coverage-summary.json`.
- **Immediate debt (already partly done this session, uncommitted):** 5 originally-failing tests were fixed; ~253 tests added; **3 tests in the new `LiveRecorder.test.tsx` still fail** (system-audio mock: `getDisplayMedia` returns 1 track not 2; "No system audio was shared" warning copy not found in EN+RU). → Fix the mock to match `LiveRecorder.tsx`'s real display-media handling, or correct the asserted copy.
- **Top uncovered files (baseline):** `lib/realtime.ts` 12.9%, `components/DictatePanel.tsx` 10.5%, `sentry.sanitize.ts` 2.9%, `components/Toast.tsx` 6.9%, `components/LiveRecorder.tsx` 23.7%, `lib/api.ts` 59.7%, `components/CompanionPanel.tsx` 57%, `app/admin/AdminConsoleClient.tsx` 82%, `components/BillingDashboard.tsx` 83%.
- **Approach:** fan-out one test file per uncovered module (vitest + @testing-library/react, jsdom, `@`→`src`). Mock network/next-navigation. Then set `web/vitest.config.ts` thresholds to 95/95/90/95 (branches slightly lower is acceptable for UI).
- **Note:** Playwright e2e (`pnpm test:e2e`) is separate from the % gate — keep green but don't count it toward unit coverage.

### 4.4 Swift (WaiComputerKit) — **largest lift**
- **Baseline:** 47.6% → **95%** (after UI/HW exclusions). 464 tests already exist.
- **Measure:**
  ```bash
  cd shared/WaiComputerKit && swift test --enable-code-coverage
  PROF=.build/arm64-apple-macosx/debug/codecov/default.profdata
  BIN=.build/arm64-apple-macosx/debug/WaiComputerKitPackageTests.xctest/Contents/MacOS/WaiComputerKitPackageTests
  xcrun llvm-cov report "$BIN" -instr-profile "$PROF" -ignore-filename-regex='(Tests|\.build|checkouts)'
  ```
- **Gap breakdown (uncovered lines / % / disposition):**
  | File | Uncov | % | Disposition |
  |---|---|---|---|
  | `Views/CompanionView.swift` | 1671 | 0.8% | **EXCLUDE** (pure SwiftUI view) |
  | `Audio/SystemAudioCapture.swift` | 609 | 6.9% | **EXCLUDE** (CATap HW) |
  | `Network/WebSocketManager.swift` | 511 | 38.3% | **TEST** |
  | `Network/APIClient.swift` | 476 | 66.2% | **TEST** |
  | `Network/ProviderBackedRealtimeSession.swift` | 339 | 35.7% | **TEST** |
  | `Audio/DualAudioCapture.swift` | 198 | 58.8% | EXCLUDE (HW) / partial |
  | `Audio/AudioEngineHost.swift` | 187 | 0% | **EXCLUDE** (HW) |
  | `Network/DictationSession.swift` | 160 | 0% | **TEST** |
  | `Monitoring/SentryHelper.swift` | 152 | 53.2% | **TEST** |
  | `Localization/LanguageManager.swift` | 75 | 0% | **TEST** (keystone — also unblocks iOS/Mac parity) |
  | `Network/WebSocketHandshakeCoordinator.swift` | 72 | 6.5% | **TEST** |
  | `Models/AppModels.swift`, `Models/Recording.swift`, `Billing/BillingModels.swift`, `Auth/SessionStore.swift`, `Models/User.swift` | — | 43–87% | **TEST** (high ROI) |
  | `Compat/*`, `RealtimePCMEncoder.swift` | — | 0% | EXCLUDE (shim/HW) |
- **Approach:** This is the hard one. The network managers (`WebSocketManager`, `ProviderBackedRealtimeSession`, `DictationSession`) likely need **protocol seams** (inject a `URLSessionWebSocketTask`-like / transport protocol) to be unit-testable without live sockets. Two sub-options:
  - **(S1) Test-only seams:** add internal protocol abstractions + fakes (small, surgical source changes) → unit-test the state machines. *This crosses into light implementation — flag as D2.*
  - **(S2) No source changes:** cover only what's reachable (models, billing, localization, sanitizer, session store, handshake parsing) and accept that socket managers cap below 95% → then either exclude them or document the ceiling.
- **Effort:** even with exclusions, reaching 95% on the testable Swift surface is dozens of new XCTest files across many rounds.

### 4.5 Android (JVM unit + instrumented)
- **State:** 17 unit + 7 instrumented Kotlin test files. **No jacoco/coverage config exists** in `android/app/build.gradle.kts` — coverage cannot be measured today.
- **Setup first (small build change — D4):** enable `testCoverage`/jacoco for `debug` and add a `jacocoTestReport` task with excludes (generated `*_*.kt`, Hilt/`*_Factory`, audio HW, Compose `*Kt` view files).
- **Measure:** `./gradlew testDebugUnitTest jacocoTestReport` → `app/build/reports/jacoco/.../*.xml`.
- **Approach:** unit tests (JVM, Robolectric where needed) for view-models, repositories, sync, sanitizer, mappers. **Instrumented tests need an emulator** — not runnable headless on this Mac as configured; flag (D5). Connected coverage (`createDebugCoverageReport`) deferred to a device/emulator host.

### 4.6 Apple — macOS (XCTest) + iOS (no tests yet)
- **macOS:** schemes `WaiComputerTests` + `WaiComputerUITests` exist.
  - **Measure:** `xcodebuild test -project macos/WaiComputer/WaiComputer.xcodeproj -scheme WaiComputer -destination 'platform=macOS' -enableCodeCoverage YES -resultBundlePath /tmp/mac.xcresult` → `xcrun xccov view --report --json /tmp/mac.xcresult`.
  - **Approach:** most app logic should live in `WaiComputerKit` (covered in §4.4); the app target's own view-models/coordinators get XCTest cases. UI tests stay smoke-only (don't count toward %).
- **iOS:** scheme is empty (`scheme: {}`) and **no `*Tests` target/dir exists.** iOS has **zero tests today.**
  - **Decision D6:** either (a) create an iOS unit-test target (covering iOS-specific Features/* + shared Kit) — a real chunk of work, needs a simulator destination — or (b) declare iOS coverage out-of-scope for now since logic is shared via the Kit. **Recommend (b) short-term, (a) for v1.0.**

---

## 5. Execution engine — bounded per-platform workflows

The proven pattern (validated on web this session): one **bounded workflow per platform**, run in the background, returning structured results so we stay in the loop between rounds.

**Web / backend (Node/Python — no shared build lock):**
`fix failing → measure+rank gaps → fan-out (1 agent per uncovered file, each writes its own test file and verifies it green) → central full-suite+coverage verify → commit`.

**Native (Swift / Android — single build lock per project):**
`measure+rank → fan-out WRITE-ONLY (agents author test files, no per-agent build) → ONE central build+test+coverage → feed compile/assert failures into a fix round → repeat until ≥95% → commit`. (Concurrent `swift build`/`gradle` in one project contend on the build lock, so do **not** let each agent build.)

**Loop-until-target:** repeat rounds until the platform's measured % ≥ 95 for two consecutive measures (guard against flaky deltas).

**Monitoring loop:** a session-local cron (`*/30 * * * *`) re-reads `/tmp/wai-cov/status.md` + `TaskList`, re-measures changed platforms, and reports a per-platform table. (Created and then **deleted** this session on request — recreate when the campaign resumes.)

**Resource discipline:** one Mac → **one platform workflow at a time**; do not overlap native builds.

---

## 6. Sequencing & milestones

0. **D1 decision** (target branch) — blocks everything below.
1. **Web** to 95% (finish the 3 LiveRecorder failures first) → bump thresholds → commit. *(closest to done)*
2. **Swift** 48→95 (resolve D2 seams first) → commit. *(longest)*
3. **Android** — add jacoco (D4) → measure → unit to 95 → commit.
4. **macOS** XCTest to 95 → commit.
5. **iOS** — D6: create target (or formally defer).
6. Re-run the full matrix on the integration branch; lock per-platform gates in CI/pre-push.

---

## 7. Open decisions for Mik (needs answers before/while executing)

- **D1 — Target branch:** Run the campaign on `main` after feature branches merge (recommended), on a specific v1.0 branch, or per-branch? *(This branch `tbank` is the wrong place — it's frozen.)*
- **D2 — Swift test seams:** May I add **test-only protocol seams** to `WebSocketManager`/`ProviderBackedRealtimeSession`/`DictationSession` so their state machines are unit-testable (light source changes), or stay strictly no-source-change and accept a ceiling on those files?
- **D4 — Android jacoco:** OK to add jacoco config (small build change) to enable measurement?
- **D5 — Android instrumented + emulator:** Is there an emulator/device available, or do connected/instrumented coverage stay deferred?
- **D6 — iOS:** Create a unit-test target now, or defer iOS coverage (logic is shared via the Kit)?
- **D7 — Commit/push policy:** Per your norm (commit per logical step) — commit each platform's tests as its own commit; push at milestones or hold?

---

## 8. Commands appendix (measure recipes)

```bash
# Backend
cd backend && source .venv/bin/activate && pytest -q --cov=app --cov-report=term-missing

# Web
pnpm -C web vitest run --coverage --coverage.reporter=json-summary --coverage.reporter=text

# Swift
cd shared/WaiComputerKit && swift test --enable-code-coverage
xcrun llvm-cov report \
  .build/arm64-apple-macosx/debug/WaiComputerKitPackageTests.xctest/Contents/MacOS/WaiComputerKitPackageTests \
  -instr-profile .build/arm64-apple-macosx/debug/codecov/default.profdata \
  -ignore-filename-regex='(Tests|\.build|checkouts)'

# Android (after jacoco is configured)
cd android && ./gradlew testDebugUnitTest jacocoTestReport

# macOS
xcodebuild test -project macos/WaiComputer/WaiComputer.xcodeproj -scheme WaiComputer \
  -destination 'platform=macOS' -enableCodeCoverage YES -resultBundlePath /tmp/mac.xcresult
xcrun xccov view --report --json /tmp/mac.xcresult

```

---

## 9. Risks & infeasible areas

- **Hardware audio & UI bodies can't reach 95% via unit tests** — handled by exclusions (§2). Without exclusions, the ceiling on Swift is well below 95%.
- **Backend has zero margin** (exactly 95.00%) — merges will break the gate; build a buffer.
- **Branch fragmentation** (§1) — testing the wrong tree wastes the whole effort; D1 is the gating risk.
- **iOS has no tests at all** — "95% on all platforms" silently excludes iOS today unless a target is created (D6).
- **Single-Mac contention** — native builds compete; serialize them.
- **Concurrent sessions** are editing the same files on other worktrees — coordinate or the campaign will conflict (already observed: another session running `swift test` in `wai-transcription-fix`).

---

## 10. What this session already did (so resuming is clean)

- **Backend:** confirmed **95.00%** (no changes).
- **Web (uncommitted, working tree only):** a workflow fixed the 5 originally-failing tests (verified each was a *stale* assertion vs intentional component changes — system font, Mac-parity Action-Items removal, 2-arg delete — and did **not** weaken them) and added ~253 tests (396→649 passing). **3 tests in the new `web/src/components/LiveRecorder.test.tsx` still fail** (system-audio mock). Changed: 9 modified + 5 new `web/src` test files — **not committed**.
- **Loop:** a `*/30 * * * *` monitoring cron was created, then **deleted** on request. No scheduled jobs remain.
- **Decision recorded:** coverage scope policy (§2). Baselines (§3). All in `/tmp/wai-cov/status.md` (ephemeral).

*End of plan. No code has been changed by writing this document.*
