# WaiComputer — Improvement Cherry-Pick · Run #5 (2026-06-14)

> ## ⏸️ RUN #5 (15:41) — no functional change; **3 P0s still open (billing now ~1 h)**
> **Delta since run #4:** ZERO functional code change. Two commits, both non-code: `a8fb86d7f release(macos): 1.0.43 (214)` (version bump) + `eb844eeff docs: add audit and improvement reports` (adds audit `.md`/`.json` artifacts). Working tree clean. No agent sweep run — nothing to audit.
> **Verified still open (grep):**
> - 🔴 **P0-1 BILLING DOUBLE-CHARGE (Impact 10) — still open, ~1 h now across runs 3→5.** No `renewal_charge_attempt`/idempotency/`with_for_update` in `billing_renewals.py`. Every Tinkoff renewal sweep risks a real-money double-charge. **This is the single highest-value action in the repo right now.**
> - 🔴 **P0-2 partial-AAC cache — still open** (`AudioCompressor.swift:49` still `removeItem`+direct-write; the earlier `moveItem` grep was a false-positive — `moveItem` is a substring of `removeItem`).
> - 🔴 **P0-3 rate-limit + `forwarded-allow-ips='*'` — still open** (`rate_limit.py` 3× `request.client.host`; `'*'` unchanged).
> - Run-#3 detailed body below is still the current state.
>
> **🛑 Cadence recommendation (escalated):** This is the **second consecutive no-op/near-no-op run** (run 4 = one file, run 5 = zero). The 30-min loop is now burning cycles re-confirming the same three open P0s that haven't been touched. I recommend one of:
> 1. **Pause the loop** (`CronDelete b787f551`) until you're ready to act on the billing fix — the file already captures everything.
> 2. **Delta-gate it** — I only run the agent sweep when `git` shows real churn; otherwise I just refresh this banner + re-verify P0s (like runs 4–5).
> 3. **Lower to 2–4 h.**
> I won't keep re-notifying. Tell me which (or "fix billing" and I'll start).

---

# WaiComputer — Improvement Cherry-Pick · Run #3 (2026-06-14) — detailed reference (still current)

> **Run #3** of the 30-min loop. Churn since run #2 (~25 min): 5 commits (`aeac74d9c` preserve android recordings on server failure · `6e22b4b32` capture tinkoff renewal failures · `4ce720211` recover abandoned local recordings · `b29d88802` gate iOS onboarding on mic permission · `3142ca18d` telegram local bot files) + heavy native realtime/dictation/recording work + billing. 3 delta-agents ran (native · backend routes · security/billing); algorithms/web/product unchanged and carried forward. **One new finding is the most severe across all 3 runs — see P0-1.**

---

## 0. Executive delta read (from your partner)

Three things this run:

1. **🚨 NEW: a real-money billing double-charge window.** The freshly-touched `billing_renewals.py` charges Tinkoff *via the provider*, then commits the DB session that advances `tinkoff_next_charge_at`. Because the task is `acks_late=True, reject_on_worker_lost=True` and `charge_tinkoff_subscription` mints a fresh `order_id` (uuid4) per call with **no idempotency key**, a worker lost between provider-success and DB-commit → Celery re-delivers → **charges the user again**. There is no "already charged this cycle?" guard. Separately, the failure path nulls `tinkoff_next_charge_at` on **any** error (including transient 5xx/timeout/"bank unavailable"), which drops the sub from every future renewal sweep → permanent unrenewed. So billing has both a double-charge AND a permanent-deactivation window. **This is Impact 10 and time-sensitive — every renewal sweep risks it.**

2. **Several run-#2 native items got fixed (good).** Dictation O(n²) (P1-12) is now bounded (≤64 keys, ≤4096 comparisons, early-exit, regression test). The candidate-selector double-echo (F4r2-4), dictation timeout magic numbers (F4r2-5), and ObjC partial-write detection (F4r2-3) are all FIXED. The new recording-recovery + WS-vault + drain-policy features are well-built and tested.

3. **But P0-3 (corrupt WAV) is still PARTIAL, and two new data-integrity gaps appeared.** `finalize()` now throws correctly internally + per-write partial detection works — but all 7 callers **still use `try?`** and **no caller checks `hasWriteFailure` before upload**, so an in-process failed finalize still ships corrupt audio. And the new recovery feature has a **partial-compressed-AAC cache reused forever** bug: if the process is killed mid-transcode, a truncated `.m4a` (size>0) is reused on every retry → corrupt upload marked complete.

**Net:** the systemic P0 backlog (rate-limit cluster, beat SPOF, AVAudioSession, privacy manifest, CI, lockfile) is still untouched, but the most urgent new item is **billing correctness** — that should jump the queue.

---

## 1. Verification — current status of all tracked findings

| ID | Status | Evidence | Note |
|---|---|---|---|
| **P0-1** Rate-limit + `--forwarded-allow-ips='*'` | 🔴 OPEN | `rate_limit.py:115`, `docker-compose.yml:120` | Untouched since run #2. Still fleet-lockout-DoS + spoofable. Was #1; bumped to #3 by the billing bug. |
| **P0-2** iOS Keychain vs SessionStore | 🟢 OK | `WaiComputerApp.swift` Keychain | Confirmed acceptable (iOS doesn't Sparkle-drift). Closed. |
| **P0-3** Corrupt WAV (`finalize()` `try?`) | 🟡 PARTIAL | `AudioFileWriter.swift:83-112` throws now; **callers still `try?`** (`MacRecordingViewModel.swift:604`, `RecordingViewModel.swift:344`); `hasWriteFailure` never gated before upload (`MacRecordingViewModel.swift:922-954`) | Internal fix landed; caller-side gap remains → still ships corrupt audio on in-process failure. |
| **P0-4** Celery beat `-B` + recovery re-enqueue | 🔴 OPEN | recovery commits `4ce720211`/`aeac74d9c` are **client-only** (Swift `PendingRecordingSyncCoordinator`, Kotlin) | Backend recovery still hard-fails. Beat SPOF unchanged. |
| **P0-5/P0-6** SSRF | 🟡 PARTIAL | `source_fetch.py:120-154` | Redirect-to-internal blocked; DNS-rebinding TOCTOU still open (httpx re-resolves at connect). *(Agent 6 run#3 marked FIXED — disputed; the resolve-then-connect pattern is not pinning. Keeping PARTIAL.)* |
| **P0-6** Privacy manifest incomplete | 🔴 OPEN | `PrivacyInfo.xcprivacy` | Still missing `NSPrivacyTracking` + `NSPrivacyCollectedDataTypes`. App Review risk. |
| **P0-1 (run#3 native)** AVAudioSession interruption | 🔴 OPEN | `AudioCaptureProtocol.swift:112-114`, zero observers | Untouched. Still Impact 9. |
| **P1-12** Dictation O(n²) | 🟢 FIXED (committed `b32df8708`) | `dictation.py` Counter-based (exact→stem→bounded-fuzzy, ≤64 keys / ≤4096 comparisons) + word-preservation prompts; test asserts `similarity_calls==0` | Run-#4 confirmed committed. Residual: sync + no per-key length cap (F1r3-3, low). |
| **F4r2-4** candidate double-echo | 🟢 FIXED | `RealtimeTranscriptCandidateSelector.swift:23-36,75-103` + tests | Both echo patterns guarded. |
| **F4r2-5** dictation timeout magic numbers | 🟢 FIXED | `GlobalHotkeyManager.swift` policy centralization | `DictationCleanupTimeoutError` type added. |
| **F4r2-3** ObjC partial-write | 🟢 FIXED | `AudioFileWriter.swift:57-79` offset diffing | `hasWriteFailure` set on mismatch. |
| **P1-7** CI · **P1-8** lockfile · **P1-13** refresh pepper · **P1-9** companion retriever · **P1-15** get_db commits · **P1-16** reranker tie · **P1-17** personalization PII | 🔴 OPEN | unchanged | None touched this delta. |
| **P2-18** GIT_SHA · **P2-19** healthcheck wiring · **P2-20** dead admin config/header · **P2-1** verify_password fail-closed | 🔴 OPEN | unchanged | Cheap wins still pending. |
| **F6-10** bcrypt truncation | 🟡 PARTIAL | explicit `[:72]` | `bcrypt>=5.0.0` still unbounded (pin in lockfile). |

> **Tally this run:** 4 FIXED (P1-12, F4r2-3/4/5), 1 closed-OK (P0-2), 4 PARTIAL (P0-3, P0-5/6, F6-10), 1 NEW CRITICAL (billing), ~13 still OPEN.

---

## 2. Refreshed priority snapshot

| # | Item | Tier | Impact | Effort | Δ |
|---|------|------|:---:|:---:|---|
| 1 | **🚨 Tinkoff double-charge on Celery re-delivery + permanent-unrenewed on transient fail** | **P0** | 10 | 3 | 🆕 **CRITICAL** |
| 2 | **🆕 Partial-AAC cache reused forever on retry → corrupt uploads** | **P0** | 8 | 2 | 🆕 new |
| 3 | Rate-limit + `--forwarded-allow-ips='*'` cluster | **P0** | 8 | 2 | — open (was #1) |
| 4 | AVAudioSession interruption/route-change | **P0** | 9 | 3 | — open |
| 5 | `finalize()` callers still `try?` + `hasWriteFailure` not gated | **P0** | 8 | 2 | 🟡 partial |
| 6 | Privacy manifest missing `NSPrivacyTracking` + collected types | **P0** | 6 | 1 | — open (App Review) |
| 7 | Celery beat split + recovery re-enqueue | **P0** | 7 | 3 | — open |
| 8 | SSRF connect-time IP pinning (rebinding still open) | **P0** | 7 | 4 | 🟡 partial |
| 9 | **🆕 Renewal-vs-webhook race in `apply_tinkoff_event`** | P1 | 7 | 3 | 🆕 new |
| 10 | **🆕 Realtime keyterms/replacements unbounded per-string → JWT inflation** | P1 | 6 | 2 | 🆕 new |
| 11 | **🆕 Dictation `ProviderBackedRealtimeSession` no reconnect** (recording has one) | P1 | 7 | 4 | 🆕 new |
| 12 | CI + Dependabot | P1 | 9 | 3 | — open |
| 13 | Dependency lockfile | P1 | 8 | 2 | — open |
| 14 | Companion retrieval → `unified_search` | P1 | 8 | 3 | — open |
| 15 | Refresh-token HMAC pepper | P1 | 7 | 2 | — open |
| — | *(web + strategic + foundational carried — §7–§8)* | | | | — unchanged |

---

## 3. P0 — Fix now

### 🚨 P0-1 · Tinkoff billing: double-charge window + permanent-unrenewed (NEW, Impact 10)
- **Double-charge:** `billing_renewals.py:84,122-152` charges the rebill at the provider, then commits the session that advances `tinkoff_next_charge_at`. Task is `acks_late=True, reject_on_worker_lost=True` (`:178-179`). If the worker is lost between provider `Charge` succeeding and the DB commit, Celery re-delivers and re-runs the same due subscription → **second real charge**. No pre-charge intent record, no idempotency key sent, `charge_tinkoff_subscription` mints a fresh `order_id = uuid4().hex` per call (`tinkoff_provider.py:247`). The Invoice `provider_payment_id` unique index only dedups duplicate *webhooks*, not duplicate *renewal charges*.
- **Permanent-unrenewed:** the `except Exception` arm (`:153-172`) sets `tinkoff_next_charge_at = None` + `PAST_DUE` on **any** failure — including transient Tinkoff 5xx, network timeout, `"bank unavailable"`. Nulling the field drops the sub from every future sweep (`charge_due_tinkoff_renewals` selects `<= now`). A single blip converts an active paying sub to terminal PAST_DUE.
- **Fix:** (a) persist a `BillingEvent(type="renewal_charge_attempt", cycle_key=tinkoff_next_charge_at)` row + `SELECT ... FOR UPDATE` **before** the provider call; skip if an attempt exists for this cycle; send an idempotency key to Tinkoff. (b) Distinguish transient (5xx/timeout) from terminal (card-declined/4xx): on transient, re-arm `next_charge_at` to a backoff slot and keep ACTIVE; reserve `None`+`PAST_DUE` for confirmed declines. The Sentry capture (already added) is good — now add the distinction to `alert_code`.
- **Why #1:** real money, on every renewal sweep, in just-shipped code. PCI-DSS v4.0.1 §6.5.10 requires controls preventing duplicate processing. *(F6r3-1, F1r3-2)*

### P0-2 · 🆕 Partial-compressed-AAC cache reused forever on retry
- **Problem:** `PendingRecordingSyncCoordinator.swift:345-364` caches the transcoded `.m4a` and reuses it whenever `existingSize > 0`. `compressWAVToAAC` (`AudioCompressor.swift:49-66`) writes **directly to the destination** (no temp+atomic-rename). If the process is killed mid-transcode (OOM, force-quit, crash), a **truncated `.m4a`** with `fileSize > 0` is left on disk → reused on every sync retry → server gets unplayable audio, marked complete/processing. No validity check before reuse.
- **Fix:** write to `recording.m4a.tmp`, on success atomic `FileManager.moveItem` over `recording.m4a`; on failure remove the `.tmp`. Or validate the cached AAC (`AVAudioFile(forReading:)` succeeds + length matches source) before reuse. Impact 8, Effort 2. *(F4r3-1)*

### P0-3 · Rate-limit + `--forwarded-allow-ips='*'` cluster (still untouched)
- `rate_limit.py:115` keys on `request.client.host` → behind Caddy, one global bucket per worker (fleet lockout DoS). `docker-compose.yml:120` `--forwarded-allow-ips='*'` makes X-Forwarded-For spoofable. Fix as one unit: tighten allow-ips to Caddy CIDR + Redis limiter keyed on proxy-derived real IP. *(unchanged from run #2)*

### P0-4 · AVAudioSession interruption/route-change (unchanged, Impact 9)
- Still zero observers. A call/Siri/headphone-unplug silently freezes a recording. *(unchanged)*

### P0-5 · `finalize()` callers still swallow errors + `hasWriteFailure` not gated (PARTIAL)
- Internal `finalize()` now throws correctly + per-write partial detection works — but all 7 callers still `try?` (`MacRecordingViewModel.swift:604`, `RecordingViewModel.swift:344`), and `uploadableFinalizedAudioFileURL` (`MacRecordingViewModel.swift:922-954`) never checks `hasWriteFailure`. An in-process disk-full finalizes partial bytes and ships corrupt audio. Replace `try?` with `do/catch` (capture + flag + discard) and gate upload on `hasWriteFailure == false`. *(F4r3-2)*

### P0-6 · Privacy manifest incomplete (unchanged, App Review risk)
- Still missing `NSPrivacyTracking` + `NSPrivacyCollectedDataTypes`. Add them (Sentry crash/usage diagnostics, `AppFunctionality`). *(unchanged)*

### P0-7 · Celery beat `-B` SPOF + recovery re-enqueue (unchanged)
- Recording-recovery commits were client-side only; backend still hard-fails. *(unchanged)*

### P0-8 · SSRF connect-time IP pinning (PARTIAL)
- Redirect-bypass fixed; DNS-rebinding TOCTOU still open. Pin validated IP at connect. *(unchanged)*

---

## 4. P1 — High-impact

- **🆕 P1-9 · Renewal-vs-webhook race.** `apply_tinkoff_event` is called inline by the renewal (`billing_renewals.py:151`) **and** by the webhook (`webhooks.py:67`) concurrently for the same OrderId → raced `Subscription` state writes + duplicate `BillingEvent` rows. Wrap dispatch in `SELECT … FOR UPDATE` on Subscription; dedupe on `(subscription_id, order_id, status)`. *(F6r3-2)*
- **🆕 P1-10 · Realtime keyterms unbounded per-string → JWT inflation.** `realtime_transcription.py:98-103` caps list *count* (100/200) but **not per-element length**; the merged list is embedded in a JWT and signed synchronously. 100 × ~30KB ≈ 3MB JWT → CPU exhaustion per request. Add `StringConstraints(max_length=128)` per element + cap total serialized size (reject ≥8KB with 422). Auth-gated so blast radius is authenticated users. *(F1r3-1)*
- **🆕 P1-11 · Dictation `ProviderBackedRealtimeSession` has no reconnect.** Recording's `WebSocketManager` has full reconnect + 30s replay; the dictation session (`ProviderBackedRealtimeSession.swift:432`) just yields `.closed(.networkLost)` on any error → a transient blip kills the press, losing the in-flight phrase. Add a bounded (1–3 attempts, ~3s) reconnect with pending-audio replay. *(F4r3-3)*
- **P1-12 · CI** (still open). **P1-13 · Lockfile** (open). **P1-14 · Companion retriever → unified_search** (open). **P1-15 · Refresh-token pepper** (open). **P1-16 · Win/Linux sanitizer** — `desktop/WaiComputer.Core/Monitoring/Sanitizer.cs` now exists (good); verify it's wired as a `BeforeSend`. **P1-17 · get_db commits on reads** (open). **P1-18 · Reranker tie-collapse** (open). **P1-19 · Personalization PII filter** (open).

---

## 5. P2 — Cheap wins (still open)

- **P2-1 · `verify_password` fail-closed** — broaden except to `(ValueError, TypeError, AttributeError)`. *(F6r3-3)*
- **P2-2 · `get_release_version()` read `GIT_SHA`** — env is plumbed but ignored; one-line. *(F6r3-4)*
- **P2-3 · Wire `/health/live`** into compose HEALTHCHECK + deploy wait. **P2-4 · Delete dead `admin_password` + CORS header.** **P2-5 · `salience_score` server_default.** **P2-6 · Redis `aclose` on re-bind.** **P2-7 · Pin `bcrypt==5.0.0`** in the lockfile.
- Native: Sentry DSN → Info.plist (F4-6); `MicrophoneCapture.deinit` stop engine (F4-9, partial); iOS `baseURL` env override (F4-12); iOS `.voiceChat` + background-audio decision (F4-3).

---

## 6. New lower-priority findings (run #3)

- **F4r3-4** `ProviderBackedRealtimeSession.close()` drain loop busy-polls 50ms and swallows `CancellationError` (`try?` on `Task.sleep`) → `cancel()` doesn't short-circuit. Switch to event-driven + catch CancellationError. Effort 3.
- **F4r3-5** `repairWAVHeaderSizes` validates RIFF/WAVE magic but not sample-rate/channels vs manifest → a recovered wrong-format file transcodes/diarizes on bad assumptions. Assert 16kHz/mono/int16. Effort 2.
- **F1r3-3** Dictation fuzzy validator still sync Levenshtein on event loop (now bounded, residual) — cap per-key length, optionally `asyncio.to_thread`. Effort 2, low impact.

---

## 7. Strategic / Product (carried — code unchanged)

Unchanged this delta; still the highest-leverage product bets on existing infra: **Build the Brain on web** (Impact 10) · **Surface quota honestly** · **Timestamp-jump as flagship UX** · **Reranker + bi-temporal facts** (the moat; ties to companion-retriever fix) · **One-tap MCP connect** · **Onboarding value-before-permission** (note: `b29d88802` just *gated* iOS onboarding on mic permission — verify this doesn't *increase* friction-before-value; it should pair with delivering a first-wow) · **Visible privacy surface** (the privacy-manifest completion, P0-6, is part of this) · **iOS billing parity + StoreKit 2**.

---

## 8. Foundational debt (carried)

i18n (`next-intl` + retire `/ru` tree) · decompose `DashboardClient.tsx` (4,251 lines) · TanStack Query (retire 13 polling loops). All unchanged; Effort 5 each.

---

## 9. Method note

- Run #3 = 3 delta-agents (native · backend routes · security/billing) + carried-forward algorithms/web/product. The **billing double-charge (Impact 10)** is the first run-3 finding to exceed the run-#2 rate-limit cluster in severity — it jumps the queue.
- Where run-#2 and run-#3 agents disagreed (SSRF: run#2 agents said PARTIAL/TOCTOU-open, run#3 Agent 6 said FIXED), I kept the more conservative PARTIAL verdict — the resolve-then-httpx-re-resolve pattern is not connect-time pinning. Re-verify next run.
- Highest-**Impact** open items now: **billing double-charge (10)**, AVAudioSession (9), CI/Brain-on-web/reranker (9), partial-AAC-cache/rate-limit/corrupt-WAV-finalize/quota (8).
- The commit did well (don't re-flag): dictation O(n²) bounded, candidate double-echo fixed, dictation timeout policy centralized, ObjC partial-write detection, recording-recovery + WS-vault + drain-policy (sound + tested), tinkoff-failure Sentry capture (good — just needs transient/terminal split), telegram local-file read (path-traversal already blocked).

---

*Run #3 · 2026-06-14 · 30-min loop. Next run overwrites. HEAD `aeac74d9c`. ⚠️ The billing finding (P0-1) is time-sensitive — every Tinkoff renewal sweep risks a double-charge until the idempotency guard lands.*
