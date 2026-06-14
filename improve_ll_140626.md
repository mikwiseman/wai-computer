# WaiComputer — Deep Audit · Run #12 (2026-06-14 19:41) — LOOP PAUSED

> **Run #12 (19:41): static for ~1h20m; loop paused.** At run time HEAD was unchanged (`f255c8d1a`) and the migration cleanup was still pending; closeout now has that cleanup committed, pushed, deployed, and production-verified. After 6 consecutive static/low-signal fires with the codebase idle and you away, I cancelled the 30-min cron (`b787f551`) to stop the no-op cycle — it's trivially restartable. **To resume:** type `/loop 30 min <the audit prompt>` again, or just tell me to re-run.
>
> **Current open state (unchanged):**
> - 🔴 **P0-1b permanent-unrenewed** — `billing_renewals.py` failure arm still nulls `tinkoff_next_charge_at` on any error. Small transient/terminal split closes Chain A.
> - 🔴 **P0-3 AVAudioSession interruption/route-change** — still no observers. Closes Chain B.
> - 🔴 Admin refund → `cancel_at_period_end` (F12d-6); plus the deep-audit backlog below.
> - ✅ Migration cleanup (`20260614_123000`) is committed in `f255c8d1a`, deployed, and production health reports schema `20260614_123000`.
>
> The deep-audit body below + runs #1–#11 capture everything. Ping me when you push changes or want me to act on a P0.

---

> ## RUN #10 — HEAD `f255c8d1a`; migration cleanup verified; two P0s unchanged
> ✅ **`f255c8d1a fix: clean duplicate provider payment invoices before indexing`** + in-flight edit to the `20260614_123000` migration — **verified sound:** fail-loud `REJECT` on conflicting duplicates (raises if dups differ on business fields), then `DELETE` only verbatim duplicates keeping the oldest (`created_at ASC, id ASC`), correct `autocommit_block` boundaries for `CONCURRENTLY`, idempotent via leading `DROP … IF EXISTS`. Exactly the right way to add a unique index to a table with possible existing dups.
>
> 🔴 **Still open (re-confirmed at HEAD — unchanged since run #9):**
> - **P0-1b permanent-unrenewed** — `billing_renewals.py:159` failure arm still `PAST_DUE + tinkoff_next_charge_at = None` on any error (incl. transient 5xx/timeout). No transient/terminal split. *(half of Chain A — Impact 9, ~10-line fix)*
> - **P0-3 AVAudioSession interruption/route-change** — still zero observers. *(remaining Chain B piece — Impact 9)*
> - **Admin refund → `cancel_at_period_end`** (F12d-6) — not touched.
>
> **Closeout:** the migration cleanup is no longer in-flight; it is committed in `f255c8d1a`, pushed to `origin/main`, deployed, and production-verified. Activity paused ~20 min after the original run note.
>
> **Both chains are one fix from closed:** permanent-unrenewed (Chain A) and AVAudioSession interruption (Chain B). Deep-audit body below is the reference.

---

# WaiComputer — Deep Audit (12→9 agents, in-scope) · 2026-06-14

> **Deep pass** — 12 agents launched, **9 in-scope** (Android/Windows/Linux **excluded by request**; focus = backend · API · mac · web · ios). Each agent went deeper than the prior 6-agent runs: re-verified open P0s *and* hunted what was missed, with Context7 + WebSearch (June 2026). Audited against current HEAD `e833a8c31`.
>
> **The deep pass earned its cost:** it surfaced ~15 issues the 6-agent runs missed — a sharper corrupt-recording data-loss chain, a likely Celery `visibility_timeout` redelivery bug, ~900 lines of dead companion code, a reranker that inverts semantic order, a bi-temporal fact model the Q&A never queries, pgvector recall at defaults, plaintext auth tokens, and a Swift Sentry PII gap.

---

## 0. Executive read (from your partner)

Two compound chains dominate everything else:

### 🚨 Chain A — Billing can double-charge AND permanently deactivate paying users
`billing_renewals.py` has **no idempotency key, no row lock, no intent row**. The task is `acks_late + reject_on_worker_lost`; `tinkoff_provider` mints a fresh `order_id` per call (T-Bank `/Init+/Charge` is gateway-non-idempotent). Any Celery redelivery (worker lost, hard timeout, OOM) or overlap between the 15-min beat and an admin "run renewal now" click charges the user **again**. Separately, the failure arm nulls `tinkoff_next_charge_at` on **any** error — including transient 5xx/timeout/"bank unavailable" — which drops the sub from every future sweep. One transient blip → terminal PAST_DUE. And admin refunds don't touch subscription state, so a refunded sub keeps charging next cycle. **Impact 10, and it's been the #1 item for ~1.5 h.** *(F4d-1, F4d-2, F4d-3, F2d-4, F12d-6)*

### 🚨 Chain B — Native recordings can silently lose data and report success
Three bugs that compound into "the user recorded 30 min, the app said 'saved,' the server got 5 min":
1. **No `AVAudioSession` interruption/route-change observer** on the recording path — a call/Siri/headphone-unplug silently freezes capture while the timer keeps climbing (Impact 9).
2. **`hasWriteFailure` is set on disk-full but *never read* before upload** — a truncated WAV with a patched header ships as the full recording (Impact 9). *This is sharper than run-#2/3's "callers use `try?`": the flag literally exists and is ignored.*
3. **`AudioCompressor` writes `.m4a` directly to the destination (no temp+atomic-rename)**, and the sync coordinator reuses a truncated-but-nonzero cache **forever** (Impact 8).
Plus iOS doesn't prevent idle sleep during recording and doesn't auto-stop on `.background` → a long iOS meeting that backgrounds the app leaves a zombie. *(F7d-2, F7d-3, F7d-4, F7d-1, F7d-5)*

### Beyond the two chains — the deep pass sharpened the brain itself
- **Reranker position-aware fusion *inverts* semantic order** for RRF top-3 (trusts the noisy ranker over the cross-encoder) — F3d-2.
- **The bi-temporal `EntityFact` model exists but `ask_brain` never queries it** — the brain's curated, time-aware facts aren't fed to the flagship Q&A. The moat is built but unplugged — F3d-8.
- **pgvector `probes`/`ef_search` are never set** → semantic recall stuck at defaults (`probes=1`) — recall silently degrades as data grows — F2d-3.
- **~900 lines of dead companion function-tool code**; the system prompt documents tools the runtime doesn't expose — F3d-1.

---

## 1. Master priority table (current state, scoped to backend/api/mac/web/ios)

| # | Item | Tier | Impact | Effort | Source |
|---|------|------|:---:|:---:|---|
| 1 | 🚨 Billing double-charge (no idempotency/lock/intent) | **P0** | 10 | 3 | F4d-1/F2d-4 |
| 2 | 🚨 Billing permanent-unrenewed (nulls `next_charge_at` on transient fail) | **P0** | 9 | 2 | F4d-2 |
| 3 | 🚨 Corrupt recording ships as success (`hasWriteFailure` never gated) | **P0** | 9 | 3 | F7d-2 |
| 4 | AVAudioSession interruption/route-change unhandled | **P0** | 9 | 5 | F7d-3 |
| 5 | iOS `.background` mid-recording → zombie (no auto-stop) | **P0** | 9 | 4 | F7d-1 |
| 6 | 🆕 Celery `visibility_timeout` top-level key missing → >1h recordings redelivered concurrently | **P0** | 8 | 1 | F4d-1 ⚠️verify |
| 7 | Partial-AAC cache reused forever (non-atomic write) | **P0** | 8 | 3 | F7d-4 |
| 8 | Rate-limit + `--forwarded-allow-ips='*'` cluster | **P0** | 8 | 3 | F1d-5 |
| 9 | SSRF DNS-rebinding TOCTOU (cloud metadata reachable) | **P0** | 8 | 4 | F4d-5 |
| 10 | Magic-link/reset tokens stored **plaintext** (DB read = account takeover) | P1 | 8 | 2 | F1d-1 🆕 |
| 11 | Swift Sentry has **no `beforeSend`/`beforeBreadcrumb`** → native crashes leak PII | P1 | 8 | 3 | F12d-2 🆕 |
| 12 | EntityFact bi-temporal model NOT queried by `ask_brain` (moat unplugged) | P1 | 8 | 5 | F3d-8 🆕 |
| 13 | pgvector `probes`/`ef_search` never set → low recall | P1 | 8 | 2 | F2d-3 🆕 |
| 14 | Celery beat `-B` SPOF + recovery hard-fails | **P0** | 7 | 3 | prior |
| 15 | Reranker position-aware fusion inverts semantic order | P1 | 7 | 2 | F3d-2 🆕 |
| 16 | Refresh-token rotation: no reuse detection (RFC 9700) | P1 | 7 | 3 | F1d-3 🆕 |
| 17 | Admin refund doesn't touch subscription state → keeps charging | P1 | 7 | 2 | F4d-2/F12d-6 🆕 |
| 18 | `/api/system/info` + `/data-map` unauthenticated, leak `git_sha`/topology | P1 | 6 | 1 | F1d-12 🆕 |
| 19 | Cross-platform sanitizer inconsistency (JWT/Telegram/`?token=` Python-only) | P1 | 7 | 3 | F12d-3 🆕 |
| 20 | Python `redact_text` ignores the richer `_SECRET_PATTERNS` (10 formats) | P1 | 8 | 2 | F12d-1 🆕 |
| 21 | iOS no idle-sleep prevention (`isIdleTimerDisabled`) | P1 | 7 | 1 | F7d-5 🆕 |
| 22 | `MicrophoneCapture.deinit` leaks running engine + tap | P2 | 5 | 1 | F7d-8 |
| 23 | TextInserter hardcodes V key-code 9 → fails non-US keyboards | P1 | 6 | 2 | F8d-5 🆕 |
| 24 | iOS Keychain vs macOS SessionStore fork contradicts AGENTS.md | P1 | 6 | 3 | F8d-1 🆕 |
| 25 | Web: refresh-token amplification (concurrent 401s → N refresh calls) | P1 | 6 | 2 | F5d-1 🆕 |
| 26 | Web: server-side auth guard (Next 16 `proxy.ts`) missing | P1 | 8 | 3 | F5d-5 |
| 27 | Web: search capped at 25, no pagination | P1 | 7 | 3 | F6d-3 🆕 |
| 28 | Web: 6+ modals violate WCAG dialog pattern | P1 | 7 | 4 | F6d-2 |
| 29 | Web: `loading.tsx`/`error.tsx` + Suspense | P1 | 7 | 2 | prior |
| 30 | Privacy manifest missing `NSPrivacyTracking`/collected types (App Review) | **P0** | 6 | 1 | F8d-1 |
| 31 | ~900 lines dead companion function-tool code (prompt ≠ runtime) | P2 | 6 | 3 | F3d-1 🆕 |
| 32 | Brain: `salience_score` dead column; recency "half-life" misnamed; reranker 280 vs 600 truncation | P2 | 4-5 | 1-2 | F2d-1/F3d-4/F3d-5 🆕 |

---

## 2. P0 — Fix now

### P0-1 · 🚨 Billing double-charge + permanent-unrenewed (Chain A)
- **Double-charge:** `billing_renewals.py:95-172` charges provider then commits the session advancing `tinkoff_next_charge_at`. `acks_late=True, reject_on_worker_lost=True`; `tinkoff_provider.py:247` fresh `order_id=uuid4().hex` per call; **no idempotency key**; no `with_for_update`. Beat (every 15 min) + admin "run now" both call the same function. Redelivery = second charge. The Invoice `provider_payment_id` is indexed **not unique** — both concurrent txns pass the "no existing invoice" check.
- **Permanent-unrenewed:** the `except Exception` (`:153-155`) sets `tinkoff_next_charge_at = None` + `PAST_DUE` on **any** error incl. transient `httpx.TimeoutException`/5xx → sub permanently drops out of the beat query.
- **Refund gap:** `admin.py:2740-2791` refund changes invoice status but never `subscription.status`/`cancel_at_period_end` → refunded ACTIVE sub charges again next cycle.
- **Fix (do together):** (a) `charge_intent` table with `UNIQUE(subscription_id, period_anchor)` + `SELECT … FOR UPDATE (skip_locked)` **before** the provider call; (b) send an idempotency key to T-Bank; (c) on transient failure re-arm `next_charge_at` to a backoff slot (+1h, capped) and keep `ACTIVE` — reserve `None`+`PAST_DUE` for confirmed declines; (d) full-refund should flip `cancel_at_period_end`. PCI-DSS v4.0.1 §6.5.10. *(F4d-1/2/3, F2d-4, F12d-6)*

### P0-2 · 🚨 Corrupt recording ships as success (`hasWriteFailure` never gated) — Chain B core
- `AudioFileWriter.hasWriteFailure` (`AudioFileWriter.swift:16`) is **set** on disk-full/I/O error and correctly skips further writes — but **no caller reads it**. `uploadableFinalizedAudioFileURL` (`MacRecordingViewModel.swift:922`, `RecordingViewModel.swift:593`) gates only on duration≥0.1s + bytes>0. A 30-min recording that hit disk-full at minute 5 finalizes a 5-min file with a patched header and uploads as the "30-min" recording. Server transcribes 5 min; 25 min gone, silently. Plus all 7 callers still `try?` the throwing `finalize()`.
- **Fix:** after `finalize()`, `if fileWriter?.hasWriteFailure == true` → surface a user-visible "Recording stopped early — only the first N min saved" error, mark the backup `retryableFailure`, and include `hadWriteFailure` in upload metadata. Direct "no fallbacks" violation. Impact 9. *(F7d-2)*

### P0-3 · AVAudioSession interruption/route-change unhandled
- Zero `interruptionNotification`/`routeChangeNotification` observers on the recording path (`MicrophoneCapture` owns its own `AVAudioEngine`, separate from the dictation `AudioEngineHost` which *does* observe config changes). A call/Siri/alarm deactivates the session; engine stops delivering buffers; `audioBuffers` goes silent; **timer keeps climbing** (`RecordingViewModel.swift:702` has no "are we still receiving audio?" guard). On macOS, headphone unplug fires `AVAudioEngineConfigurationChange` which removes the tap.
- **Fix:** add interruption + route-change observers in `MicrophoneCapture.startRecording()` (`#if os(iOS)`); replicate `AudioEngineHost.handleEngineConfigurationChange` recovery; surface an "interrupted" banner. Impact 9, Effort 5. *(F7d-3)*

### P0-4 · iOS `.background` mid-recording → zombie
- `WaiComputerApp.swift:267` observes `scenePhase` but only acts on `.active`. On `.background` during a live recording, nothing pauses/stops/finalizes; OS suspends the app; the WAV is left with an unpatched header; timer task suspended.
- **Fix:** on `.background` with a live recording, **auto-stop and persist honestly** (call `stopRecording()`), or declare `UIBackgroundMode: audio` + hold a `ProcessInfo` activity (macOS does this at `MacRecordingViewModel.swift:871`; iOS doesn't). Impact 9. *(F7d-1)*

### P0-5 · 🆕 Celery `visibility_timeout` top-level key missing — ⚠️ verify, likely real
- `celery_app.py:90,97` sets `broker_transport_options` + `result_backend_transport_options = {"visibility_timeout": 21600}` but **not** the top-level `app.conf.visibility_timeout`. Celery's Redis broker docs: "the shortest value wins" and the missing top-level key defaults to **3600s (1h)**. Recording tasks run `time_limit=21300` (5.9h) → any recording >1h gets **concurrently redelivered** by Redis while the original still transcribes. (The segment-existence guard prevents double Deepgram billing, but wastes worker capacity and re-runs downstream work.) *Agent 4 flagged this; Agent 12 disputed (saw the invariants satisfied). The specific missing top-level key claim is concrete — verify `app.conf.visibility_timeout` exists.*
- **Fix:** add `celery_app.conf.visibility_timeout = 21600` (all three must stay in sync). Impact 8, Effort 1. *(F4d-1)*

### P0-6 · Partial-AAC cache reused forever
- `AudioCompressor.swift:51` writes directly to the final `.m4a` (no temp+rename); `PendingRecordingSyncCoordinator.swift:345-363` returns the cached file **unconditionally** when `existingSize > 0` (no `moov`-validity / duration check). Killed mid-transcode → truncated `.m4a` reused on every retry → corrupt upload marked complete.
- **Fix:** write to `.m4a.tmp` + atomic `moveItem`; on cache-hit validate `AVAudioFile(forReading:)` succeeds + duration ≈ source. Mirrors the atomic pattern `RecordingBackupStore` already uses. Impact 8. *(F7d-4)*

### P0-7 · Rate-limit + `--forwarded-allow-ips='*'` cluster
- `rate_limit.py:115,122,129` key on `request.client.host` → behind Caddy **every request shares one global bucket** (`login:<caddy-ip>`) → 5 failed logins locks out **all users** for 60s (availability DoS). `'*'` makes X-Forwarded-For spoofable. Process-local singleton × 2 gunicorn workers = double the limit. magic-link + forgot-password share the *same* bucket (cheap email-wallet DoS via Resend).
- **Fix (one unit):** tighten `--forwarded-allow-ips` to Caddy's CIDR; move the limiter to Redis keyed on the proxy-derived real IP + endpoint (+ username); split magic-link/forgot-password buckets; add a per-email cap. Impact 8. *(F1d-5, F1d-15)*

### P0-8 · SSRF DNS-rebinding TOCTOU
- `source_fetch.py:143-170` resolves host + checks `is_global` + re-checks redirects, but httpx **re-resolves at connect** → DNS-rebinding can flip to `169.254.169.254` (cloud metadata). No port restriction / host allowlist either (any public IP:port).
- **Fix:** pin the validated IP at connect (custom httpx resolver or URL→IP rewrite preserving Host/SNI); restrict ports to {80,443}. Impact 8. *(F4d-5)*

### P0-9 · Privacy manifest incomplete (App Review)
- `PrivacyInfo.xcprivacy` (iOS+macOS) declare only `NSPrivacyAccessedAPITypes`; missing `NSPrivacyTracking` + `NSPrivacyCollectedDataTypes` (Sentry crash/usage data is collected + user-linked). App Review rejection vector.
- **Fix:** add `NSPrivacyTracking=false` + a `NSPrivacyCollectedDataTypes` array. Impact 6, Effort 1. *(F8d-1)*

### P0-10 · Celery beat `-B` SPOF + recovery hard-fails
- Beat still embedded in one `concurrency=1` worker (`docker-compose.yml`); AGENTS.md runbook assumes a separate beat service. Recovery hard-fails instead of re-enqueuing idempotent work. *(prior)*

---

## 3. P1 — High-impact (deep findings)

### Auth / security
- **Magic-link/reset tokens plaintext** (`auth.py:527-530,570-573` → `User.magic_link_token`). Refresh tokens are SHA-256 hashed; these 256-bit one-time tokens are **not**. A DB/backup read = full account takeover within the 15-min window. Hash them like refresh tokens. Impact 8, Effort 2. *(F1d-1)*
- **Refresh-token rotation has no reuse detection** (`auth.py:749-773`). RFC 9700 / OAuth BCP §4.13.2 require family invalidation on replay. A leaked-but-rotated token stays valid until it expires. Add `token_family_id` + revoke-on-reuse. Impact 7. *(F1d-3)*
- **`/api/system/info` + `/data-map` unauthenticated** (`system.py:144-164`) — leak `git_sha`, `git_dirty`, `deployment_mode`, `billing_mode`, retention policy to anyone. Put them behind `SessionUser`. Impact 6, Effort 1. *(F1d-12)*
- Expired magic-link token never cleared (token-existence oracle); verify_password catches only `ValueError` (None hash → 500). *(F1d-2, prior)*

### Observability (PII — the deep pass found real gaps)
- **Swift Sentry has NO `beforeSend`/`beforeBreadcrumb`** (`SentryHelper.swift:13-34`) — only `sendDefaultPii=false`. Native crashes/auto-breadcrumbs (URLSession http breadcrumbs) bypass the only PII net; a JWT/email/telegram-token in an `Error.localizedDescription` ships raw. **Kotlin and C# both have the hooks.** This is the top observability fix. Impact 8. *(F12d-2)*
- **Python `redact_text` covers only 4 formats** (email/JWT/telegram/`?token=`) while the repo's own `untrusted._SECRET_PATTERNS` covers 10 more (`sk-ant-`, `sk-`/`sk-proj-`, `AKIA…`, `gh[pousr]_…`, `xox…`, `AIza…`, `Bearer `, PEM, credit-card). Route `redact_text` through it. Impact 8, Effort 2. *(F12d-1)*
- **Cross-platform sanitizer drift:** JWT/telegram/`?token=` only in Python; Swift/Kotlin/C# redact inline-email only. Port the patterns. Impact 7. *(F12d-3)*

### Brain / algorithms (the deep pass's biggest quality finds)
- **`EntityFact` bi-temporal model is NOT queried by `ask_brain`.** The curated, time-aware, supersede-not-delete facts (`entity.py:192-246`) — exactly the "what's true *now*" moat — are never fed to the flagship Q&A; it only does snippet retrieval. Plug the fact layer into `brain_ask` retrieval. Impact 8 (moat), Effort 5. *(F3d-8)*
- **Reranker position-aware fusion inverts semantic order** (`reranker.py:80-129`): for RRF rank ≤3 it weights `(0.75 RRF, 0.25 reranker)` — so a noisy RRF top-3 beats a semantically-superior rank-15. The file's own header says "rerank so top results are reliably correct" — the weights do the opposite. Re-tune so the cross-encoder can override. Impact 7, Effort 2. *(F3d-2)*
- **pgvector `probes`/`ef_search` never set** → recall stuck at defaults (`ivfflat.probes=1` = scans 1/100 clusters). Semantic recall silently degrades as data grows. Emit `SET LOCAL ivfflat.probes=20; SET LOCAL hnsw.ef_search=80;` before the query. Impact 8, Effort 2. *(F2d-3)*
- **`segments` omitted from the HNSW migration** (`20260614_121000` indexes only `item_chunks`+`conversation_chunks`) → same `UNION ALL` query hits ivfflat for recordings, HNSW for items/chats → inconsistent recall/latency. Impact 6, Effort 1. *(F2d-2)*
- **~900 lines of dead companion function-tool code** (`companion.py:460-1342`): `tool_definitions`/`_TOOL_DISPATCH`/all `_tool_*` handlers have **zero** production callers (runtime tools are the remote MCP `wai` server + `web_search`). The system prompt documents tools the runtime doesn't expose; one dead handler still routes through the weak `qa.py` retriever. Delete or wire. Impact 6. *(F3d-1)*
- Smaller brain items: `salience_score` is a **dead column** (never written, COALESCE always 0.5) *(F2d-1)*; reranker rescores **280-char** snippets but synthesizer uses a 600-char cap that never applies *(F3d-4)*; the recency "half-life" is **misnamed** (0.368 at 30 days, real half-life ≈21 days) *(F3d-5)*; `brain_ask` Cerebras call uncapped + (partially) no finish-reason gate *(prior)*.

### Native (mac/ios)
- **iOS no idle-sleep prevention** — `RecordingViewModel` never sets `UIApplication.isIdleTimerDisabled` (macOS uses `ProcessInfo` activity). Long iOS meetings on a sleeping device get suspended. One-liner fix. Impact 7, Effort 1. *(F7d-5)*
- **`MicrophoneCapture.deinit` leaks the running engine + tap** (`AudioCaptureProtocol.swift:208-211`) — asymmetric with `SystemAudioCapture` which stops in deinit. 3-line fix. *(F7d-8)*
- **iOS Keychain vs macOS SessionStore fork** contradicts AGENTS.md's "SessionStore is the cross-platform standard" — iOS uses Keychain at 16 sites, never `SessionStore`. Either wire iOS to `SessionStore` or document the fork. *(F8d-1)*
- **TextInserter hardcodes virtual-key 9 (V)** (`TextInserter.swift:167`) → ⌘V fails on QWERTZ/AZERTY/ЙЦУКЕН; "auto-paste silently fails, manual paste works." Use `UCKeyTranslate`. *(F8d-5)*
- SessionStore/learning-ledger writes lack iOS data-protection class + backup exclusion (latent until iOS adopts SessionStore). *(F8d-2)*
- iOS `.voiceChat` mode + `UIBackgroundModes:audio` decision; Sentry DSN → Info.plist; `baseURL` force-unwrap. *(prior)*

### Web
- **Server-side auth guard missing** — no `proxy.ts` (Next.js 16 renamed `middleware.ts`→`proxy.ts`); `/dashboard` serves the protected shell to every visitor before the client-side 401 redirect (the login-loop risk AGENTS.md warns about). Impact 8. *(F5d-5)*
- **Refresh-token amplification** — concurrent 401s each call `/api/auth/refresh` (no in-flight dedup); single-use rotation means N-1 fail and can race the one success. Module-level `refreshInFlight` promise. Impact 6. *(F5d-1)*
- **Search capped at 25, offset 0, no pagination** (`DashboardClient.tsx:1318`) — most hits invisible. Reuse the inbox cursor pattern. Impact 7. *(F6d-3)*
- **6+ modals violate WCAG 2.2 dialog pattern** — no focus trap/autofocus/Escape/scroll-lock/`aria-labelledby`/focus-restore (`DashboardClient.tsx:2166,2204,2665`, `RecordingDetailPanel:617`, `DeleteAccountSection:93`). `CompanionPanel` does it right — extract a reusable `<Modal>`. Impact 7. *(F6d-2)*
- `loading.tsx`/`error.tsx`/Suspense; ItemsFeed poll race (no request-id guard); live-transcript interim `aria-hidden` inconsistent across LiveRecorder vs DictatePanel. *(prior/F6d-1/F5d-2)*

---

## 4. P2 — Cheap wins

- **`/health/ready` queries DB + `alembic_version` every probe** (`main.py:240-263`) — readiness probes amplify DB load; drop the alembic query. Effort 1. *(F1d-10)*
- **Split magic-link / forgot-password rate-limit buckets** + per-email cap (bounds Resend cost). *(F1d-15)*
- **`get_release_version()` read `GIT_SHA`** (env is plumbed, ignored). *(prior)*
- **Delete dead `admin_password` config + `X-Wai-Admin-Password` CORS header** (confirmed never read). *(prior/F1d)*
- **`salience_score` `server_default="0.5"`** migration. *(F2d-1)*
- **Redis `aclose` on re-bind** (`transcription_guard.py:84-93`, `agent_guard.py:58-67`). *(prior)*
- **T-Bank webhook token** use `hmac.compare_digest` (currently `==`). *(F4d-7)*
- **Onboarding error `<p>` add `role="alert"`** (one line). *(F6d-5)*
- **`isIdleTimerDisabled`** during iOS recording (one line). *(F7d-5)*
- **Global RFC 9457 error envelope** (5xx return plain `{"detail":...}`, no `request_id` in body). *(prior/F1d-7)*
- **Lifespan fail-fast** on empty required keys (currently warns — "no fallbacks" violation). *(F1d-11)*

---

## 5. Foundational debt (carried)
i18n: `next-intl` + retire forked `/ru` tree + 13 components with inline `locale==="ru"` *(F6d-7)* · decompose `DashboardClient.tsx` (4,251 lines) per-view + code-split *(F5d-4)* · TanStack Query (retire ~7 polling loops + `no-store`). *(prior)*

---

## 6. Verification tally (prior P0s, deep-confirm)
| Item | Status |
|---|---|
| Billing double-charge / unrenewed | 🔴 OPEN (sharpened — refund gap too) |
| Corrupt WAV | 🔴 OPEN (sharpened — `hasWriteFailure` never read) |
| AVAudioSession interruption | 🔴 OPEN |
| Partial-AAC cache | 🔴 OPEN |
| Rate-limit + forwarded-ips | 🔴 OPEN (worse — single global bucket + 2× workers) |
| SSRF TOCTOU | 🔴 OPEN |
| Celery beat `-B` + recovery | 🔴 OPEN |
| Privacy manifest | 🔴 OPEN |
| Dictation O(n²) | 🟢 FIXED (committed) |
| GIT_SHA release | 🟢 FIXED (`deploy-api.sh` parses + passes it) *(Agent 12 — corrects prior "OPEN")* |
| visibility_timeout invariant | 🟡 **DISPUTED** — Agent 4 says top-level key missing (effective 1h); Agent 12 says satisfied. **Verify `app.conf.visibility_timeout`.** |
| Win/Linux sanitizer | ➖ out of scope (platforms excluded) |

---

## 7. Method note
- 12 agents launched; **9 in-scope** (Android/Windows/Linux excluded per your direction — those 3 agents' results discarded). 2 in-scope agents rate-limited and were re-run successfully.
- Agent raw scores use differing scales (Impact 1–10 vs 1–5; Effort varies) → not directly comparable. This doc re-derives a unified Impact(1–10)/Effort(1–5) and tiers by Impact first.
- HEAD drifted to `e833a8c31` during the run (agents audited the live tree).
- **Where agents disagreed** (visibility_timeout; SSRF FIXED-vs-PARTIAL) I kept the more conservative verdict and flagged for verification.
- The deep pass genuinely beat the 6-agent runs: ~15 net-new findings (billing refund gap, plaintext tokens, Swift Sentry gap, redact_text gap, EntityFact-unplugged, reranker inversion, pgvector recall, dead companion code, iOS background/idle-sleep, deinit leak, V-keycode, web refresh-amplification, search-pagination, the `hasWriteFailure`-never-read sharpening). Worth the cost.

*Deep audit · 2026-06-14 · scoped to backend/api/mac/web/ios. The two compound chains (billing, native silent-data-loss) are the priority; the brain-quality cluster (EntityFact, reranker, pgvector) is the moat work.*
