# WaiComputer — Curated Improvement Plan (2026-06-14)

> **What this is.** A single, verified plan distilled from a multi-pass review. Every finding was re-scored and re-verified against the real code by 12 parallel domain agents, then good ones were kept + sharpened and refuted/duplicate/low-value ones removed. Every item cites `file:line` confirmed against current `main`.
>
> **How to read it.** Start with **✅ Ship-Ready Now** (verified, low-risk, no decision). **⚠️ Decision-Gated** items each need exactly one call from you. **🔬 Stage-Carefully** are higher-risk refactors (relief-first). The **Findings by domain** catalog is the complete reference; the **Execution Sequence** orders everything into waves.
>
> Scoring: `I·E·C` = Impact·Effort·Confidence (1–5), `Priority = I×C÷E`. Status: `verified` = re-read line-by-line this pass · `needs-decision` = blocked on one call · `staged` = ship relief slice first.

---

## ✅ Ship-Ready Now (verified, low-risk, no decision)

| # | Item | The exact change | Test | Risk |
|---|---|---|---|---|
| S1 | **Web onboarding "seen-on-mount" bug** | Delete the `markOnboardingSeen()` in the mount `useEffect` (`web/src/components/OnboardingClient.tsx:159`); `submit()`/`skip()` already call it | **invert** the existing `OnboardingClient.test.tsx:50` test (it asserts the bug) | 2 |
| S2 | **reset_password → revoke sessions** | `await db.execute(delete(RefreshTokenModel).where(user_id==user.id))` before flush (`backend/app/api/routes/auth.py:722`) | old refresh 401s, new password works | 2 |
| S3 | **SQL content truncation** | `LEFT(content,320) AS content` in the `unified_search` final projection (`backend/app/core/unified_search.py:215`); full body is unused past the 280-char snippet | snippet byte-identical; run `-m integration` search tests | 2 |
| S4 | **Remove dead web deps** | `pnpm remove @xyflow/react react-force-graph-2d` + delete the `web/src/app/globals.css:1` `@import` (zero JS importers) | `pnpm build` green | 2 |
| S5 | **iOS/macOS `PrivacyInfo.xcprivacy`** | Add manifest: FileTimestamp `C617.1` + UserDefaults `CA92.1`; wire via `project.yml`. **Drop DiskSpace `85F4.1`** — zero `volumeAvailableCapacity`/`systemFreeSize` hits, so declaring it would be false | archive → no ITMS-91053 | 1 |
| S6 | **Mac disk-full crash** | `try handle.write(contentsOf:)` + `offset()` in `AudioFileWriter` **plus an Obj-C `@try/@catch` shim** (NSException can still raise); fix `finalize()` too (`shared/.../Audio/AudioFileWriter.swift:52,80`) | write past a size-capped tmpfs → `false`, no crash, valid header | 2 |
| S7 | **SSRF + size guard** (`_http_get`) | `follow_redirects=False`; resolve-then-validate (block RFC-1918/loopback/link-local + IPv4-mapped); re-validate each hop; ~25MB response cap (`backend/app/core/source_fetch.py:115`) | block `127.0.0.1`/`169.254.169.254`/`[::1]`/`file://`; DNS-rebind seam | 2 |
| S8 | **Drop passlib → bcrypt direct** | Call `bcrypt.hashpw/checkpw` in `security.py`, **pre-truncate `password.encode()[:72]`** (else long passwords 500 on bcrypt ≥4.1), unpin `bcrypt` | cross-tool: a passlib-era `$2b$` hash still verifies | 2 |
| S9 | **HNSW indexes** | `CREATE INDEX CONCURRENTLY … USING hnsw` on **`item_chunks` + `conversation_chunks` only** (in `autocommit_block()`). `recordings`/`items` doc-vectors are unused by search; `segments` already ivfflat | `EXPLAIN` index-scan >1k rows; top-K overlap ≥0.95 | 2 |
| S10 | **Deepgram timeout scales w/ duration** | `httpx.Timeout(read=max(300, minutes*k), connect=10, …)` keyed off the already-computed duration (`backend/app/core/deepgram.py:277,449`) | timeout kwarg scales with duration | 1 |
| S11 | **Breaker-open alert** | On closed→open in `record_provider_result`, call the already-imported `capture_sentry_anomaly` + `notify_ops` (transition-only, try/except) (`backend/app/core/transcription_guard.py:361,368`) | fires once on open, re-fires after close | 1 |
| S12 | **Celery correlation-id** | Propagate `x-request-id` at enqueue + a `task_prerun`/`postrun` that `begin_request_context` (prerun is unoccupied) | eager task log line carries the request_id | 2 |
| S13 | **entity_mentions cleanup** | In `delete_recording`: `DELETE entity_mentions WHERE source_kind/source_id` + dirty affected entities + a one-time orphan-backfill sweep; make the `wake_up` count query orphan-safe (`backend/app/api/routes/recordings.py:2024`) | delete → zero orphan mentions; counts exclude them | 2 |
| S14 | **Web live-transcript a11y** | Split the transcript `<p>` → `<p aria-live="polite">{committed}</p>` + `<span aria-hidden>{interim}</span>` (`web/src/components/LiveRecorder.tsx:222`) | RTL asserts the live region + hidden interim | 1 |
| S15 | **Mac/iOS live-transcript + timer a11y** | `.accessibilityAddTraits(.updatesFrequently)` on the committed `Text` + the timer (announce committed, never interim) | manual VoiceOver | 2 |
| S16 | **`forget` → `MUTATING_TOOLS`** | One line + comment — **defensive only** (already fail-closed via the catch-all) (`backend/app/core/tool_safety.py:61`) | `is_mutating_tool_call("forget")` via the explicit set | 1 |

Other ≤1-effort wins (in the catalog): reciprocal **hreflang** on the EN landing/legal pages (20.0), **billing emails key off `default_language` not `region`**, **stale-recovery runbook entry**, **fold 3 folder-count scans into one `UNION ALL`** (15.0), **silent JSON `"Done"` fallback removal** (15.0).

## ⚠️ Decision-Gated (real + designed; each needs one call)

| # | Item | The single decision | Risk after |
|---|---|---|---|
| D1 | **Turn on the reranker** | Provision a paid ZeroEntropy key **and** accept it on without a RU A/B (it *raises* on a vendor outage → breaks Ask + MCP search) **vs** run the A/B first. **Not a config quick-win.** | 4 |
| D2 | **iOS background recording** | `UIBackgroundModes: audio` + App-Store justification (locked-screen recording) **vs** honest pause-on-background | 4 / 2 |
| D3 | **iOS interruption resume** | Auto-resume on `.shouldResume` **vs** explicit "tap to resume" banner *(recommended)* | 3 |
| D4 | **Tinkoff idempotency** | Confirm the deterministic `OrderId` keys on **`subscription_id`** (+ period epoch); handle nullable `current_period_start` | 3 |
| D5 | **untrusted.py wiring** | Redaction scope: fetched-source bodies only, **or** also user-typed notes? + accept/tighten the `credit_card` regex false-positive rate first | 3 |
| D6 | **Refresh-token reuse detection** | Dual-instance policy: short grace window returning the same new token **vs** strict single-use + fix shared-`session.json` separately (gates the migration) | 4 |
| D7 | **Free-tier copy** | Ratify **"3,000 words/week + 30-day memory"** as canonical (backend + pricing + RU landing already say it) → fix the stray EN `page.tsx:534` "10 recordings"; decide enforce vs "free during beta" | 1 |
| D8 | **entity_facts on delete** | Purge orphaned facts **vs** supersede/`invalid_at` (the table is explicitly bi-temporal "supersede-not-delete") | 2 |
| D9 | **complete_action_item MCP tool** | Gate behind `mcp:write` scope (like `remember`/`forget`) **vs** read-only | 3 |
| D10 | **DB pool bump** | Approve `pool_size=10/overflow=10` × workers vs Postgres `max_connections` headroom on the 3.8GB VPS | 2 |
| D11 | **Brain answer language** | RU user + EN recording → answer in **Russian** (their pref, matches summarizer) **vs** the source language. Same decision unblocks the shared `UserFacingErrorFormatter` localization | 2 |
| D12 | **Re-introduce a Brain surface?** | Build a user-facing Ask/Brain home over the shipped `/brain/feed`+`/brain/ask` **vs** commit to headless-MCP-only (the Brain UI was deliberately removed `1d9b9258f`). Gates the Ask-surface, "Cards-That-Think", and SPECS.md items | — |

## 🔬 Stage-Carefully (ship relief slice first, restructure behind a test)

| # | Item | Relief slice (now, low risk) | Restructure (staged) | Hazard |
|---|---|---|---|---|
| T1 | **`ask_brain` connection-hold** | Pool bump + an LLM `asyncio.Semaphore` | "retrieve → release session → run LLM unheld → reopen" | double-session/request if the route still injects `Database` |
| T2 | **Mac config-change tap reinstall** | **Mic-only**, post the reinstall **off-lock**, verify `hasReceivedAudio` ≤3s | full `DualAudioCapture` two-tap reinstall | deadlock/double-install under the hand-rolled `os_unfair_lock` |
| T3 | **`segments` ivfflat → HNSW** | `SET LOCAL ivfflat.probes=10` per search txn (risk 1) | `CREATE INDEX CONCURRENTLY` + drop-old on the largest embedded table | build cost/churn on the biggest table |

---

# Findings by domain

## Backend & API
- **B1 · Tinkoff renewals double-charge-proof** — `billing_renewals.py:64,122` selects due rows unlocked and `charge_rebill()` (`tinkoff_provider.py:247`, fresh `uuid4` OrderId, no idempotency key) fires before any dedup → overlapping beat / lost-response retry bills twice. The `tinkoff_order_id` UNIQUE column (migration `20260522_120000`) exists but is **unwired**. → `FOR UPDATE SKIP LOCKED` + deterministic `OrderId` persisted before charge. **I5·E3·C5** · **[D4]** (real money; latent — terminal is DEMO).
- **B2 · Trusted proxy headers** — prod gunicorn (`docker-compose.yml:88`) sets no `--proxy-headers`; behind Caddy, `rate_limit.py` keys on the proxy's docker IP → all auth limiters collapse to one global bucket. → `--proxy-headers --forwarded-allow-ips`. **I4·E1·C5 → 20** · verified.
- **B3 · Auth rate limiter → Redis** — `rate_limit.py:23` is a per-process `dict`; real limit is `5 × workers`, resets each deploy. → Redis INCR+EXPIRE fail-open (the `transcription_guard.py` pattern). **I4·E2·C5 → 10** · verified.
- **B4 · Offload sync decoders** — `source_fetch.py:141,157` (pdfplumber) + `voice_enrollment.py:150` (`AudioSegment.from_file`) block the event loop. → `anyio.to_thread.run_sync`. **I4·E2·C4 → 8** · verified *(corrected file: `source_fetch.py`; `document_extract.py` already offloads)*.
- **B5 · Telegram webhook durability** — `telegram.py:4013` marks the update `accepted`, commits, returns 200, then runs `_handle_update` in an in-process `BackgroundTask`; a worker death orphans it forever (Telegram won't redeliver). → Celery task keyed on `update_id`, or a stale-`accepted` re-dispatch beat. **I4·E3·C5 → 6.7** · verified.
- **B6 · `process_item` redelivery guard** — `item_processing.py:49` re-fetches + re-embeds (paid) + re-summarizes with no `state=="ready"` short-circuit. → early-return when ready. **I3·E2·C5 → 7.5** · verified.
- **B7 · Hash MCP OAuth `client_secret`** — `mcp_oauth.py:439` stores it plaintext (the lone unhashed credential). → `sha256`. **I3·E2·C4 → 6** · verified. *(See Security.)*
- **B8 · Retry/backoff on paid AI tasks** — `summary_audio_generation.py:85` + `item_summary_generation.py:44` have no `max_retries` (siblings use `retry_policy.py`); a transient 429 permanently fails paid work. **I3·E2·C4 → 6** · verified.
- **B9 · Index hot status columns** — `Subscription(provider,status)` + `Recording.status` scanned by every beat, unindexed. **I3·E1·C4 → 12** · verified.
- **B10 · Validate audio by magic bytes** — `recordings.py:973` trusts client extension/Content-Type. **I3·E2·C4 → 6** · verified.
- **B11 · Admin N+1 invoice fetch** — `admin.py:2445` queries invoices per-subscription in a loop. **I3·E2·C4 → 6** · verified.
- **B12 · Keyset-paginate `GET /recordings`** — `recordings.py:1215` deep `OFFSET`. → row-value cursor. **I3·E2·C4 → 6** · verified. *(See Journeys "100-recording wall".)*
- **B13 · python-jose → PyJWT** — `security.py:8` (+ `realtime_transcription.py`, `voice_session.py`); PyJWT is already installed transitively. **Note:** the installed jose 3.5.0 post-dates CVE-2024-33663/4 — the case is dependency hygiene, not an open CVE. **I2·E2·C4 → 4** · needs-decision.

## Algorithms, Search & Brain
- **A1 · Turn on the reranker** — `config.py:67` `reranker_enabled=False`; the complete zerank-2 stack (`reranker.py`) runs at ×1.0 and feeds Ask + MCP `search` (not plain `/search`). **I5·E1·C5 → 25** · **[D1]**.
- **A2 · HNSW on `item_chunks` + `conversation_chunks`** — no ANN index → every semantic arm in `unified_search.py:89-127` is a full per-user seq scan (the items migration promised an HNSW follow-up that never landed). **I5·E2·C5 → 12.5** · verified-ship **[S9]**.
- **A3 · Scale the Deepgram batch timeout** — `deepgram.py:277` flat 300s; 1h+ recordings `ReadTimeout` → fail (+ retried timeout re-bills). **I5·E2·C4 → 10** · verified-ship **[S10]**.
- **A4 · Wire the bi-temporal `EntityFact` table into synthesis** — `reconcile_facts` writes/supersedes it (`entity_graph.py:703`) but `entity_page_synthesis.py` never *reads* it, so superseded facts co-exist in dossiers. **I4·E3·C4 → 5.3** · **[D8]**.
- **A5 · Ground action items + nullable `priority`** — highlights are grounded to the transcript; `action_items` aren't (`summary_generation.py:225`); strict-mode forces a non-null `priority` with no rules (silent DB default, not a crash). **I4·E2·C4 → 8** · verified.
- **A6 · Learned dictionary into LIVE dictation** — `load_user_replacements` is batch-only; `RealtimeTranscriptionProxyClaims` carries `keyterms` but not `replacements`, so live dictation ignores corrections (`build_realtime_websocket_url` already supports `replace`). **I4·E2·C5 → 10** · verified.
- **A7 · Wire the search-eval golden harness as a CI gate** — `tests/eval/brain_eval.py` ships a RU+EN P@k/MRR set but `run_against_db` has zero callers. → one `@pytest.mark.integration` asserting `mrr≥0.8`. The safety net D1/A2 need. **I4·E2·C5 → 10** · verified.
- **A8 · Neighbor-window contextual embeddings** — each segment is embedded with only a static title prefix (`recording_audio_processing.py:1070`). **I4·E3·C4 → 5.3** · verified.
- **A9 · Scope the nightly consolidator** — `consolidate_user_memory.py:286` scans ALL users (incl. soft-deleted), opens a session before discovering inactivity, runs serially, no per-(user,day) idempotency. **I3·E2·C5 → 7.5** · verified. *(See Performance.)*
- **A10 · Pin Brain output language** — `brain_ask.py:46` + `entity_page_synthesis.py:55` have no language clause (summarizer does) → RU users get English answers/dossiers. **I5·E2·C4 → 10** · **[D11]**.
- **A11 · Reduce-pass: title via `_title_sample`, summary from structured** — `summarizer.py:464` re-summarizes per-chunk prose for >40k (double-lossy) and discards per-chunk titles, while a head/middle/tail titler already exists. **I3·E2·C4 → 6** · verified.
- **A12 · Chunk entity extraction over long transcripts** — `summary_generation.py:41` extracts from `transcript[:24000]` single-pass → every entity after ~24k dropped. **I4·E3·C5 → 6.7** · verified.
- **A13 · Sort-before-truncate + fuzzy-dedup the merge** — `_merge_partial_summaries` truncates in list order (drops end-of-meeting items) and dedups exact-casefold only. **I3·E3·C4 → 4** · verified (bundle with A11/A12).
- **A14 · Sub-batch `generate_embeddings`** — one-shot `input=texts`; a long PDF/chat >2048 chunks hard-fails the OpenAI cap → whole doc un-searchable (the `item_ingest` path is exposed; backfill is safe). **I3·E2·C4 → 6** · verified.

## Web (Next.js)
- **W1 · Onboarding "seen-on-mount"** — **[S1]**. **I4·E1·C5 → 20** · verified.
- **W2 · Live-transcript `aria-live`** — **[S14]**. **I5·E1·C5 → 25** · verified.
- **W3 · Remove dead graph deps** — **[S4]**. **I3·E1·C5 → 15** · verified.
- **W4 · Reciprocal hreflang + canonical** on the EN landing + legal/pricing (`app/page.tsx` exports no `alternates`; `/ru` already points back). **I4·E1·C5 → 20** · verified.
- **W5 · Set the canonical web accent** — `layout.tsx:58` SSRs `data-accent="amber"` but `tokens.css:233` comment says teal. **I3·E1·C4 → 12** · **[needs-decision: amber vs teal]**.
- **W6 · Add `error.tsx`/`global-error.tsx`** — none exist; a render throw white-screens the 4251-line `DashboardClient`. **I3·E2·C5 → 7.5** · verified.
- **W7 · Data layer (TanStack/SWR) + stale-response guards** — `http.ts` is `cache:"no-store"` no-dedup; detail/`ItemDetail` loaders lack the monotonic guard the inbox already has → click A then B fast, A overwrites B. **I5·E4·C4 → 5** · verified *(absorbs the mis-scoped "virtualize inbox")*.
- **W8 · Visibility-gate stacked polling** — 4 `setInterval` loops hit `/api` in hidden tabs; only the Telegram poll checks `document.hidden`. **I4·E2·C5 → 10** · verified.
- **W9 · Clickable Ask citations + announce the stream** — citations are non-focusable `<span>` (`CompanionPanel.tsx:993`), the chat log has no `role="log"`/`aria-live`, auto-scroll fires per token. **I4·E2·C5 → 10** · verified.
- **W10 · Virtualize + memoize the transcript** — `RecordingDetailPanel.tsx:700` re-runs `mergeTurns` unmemoized + remounts every turn; no windowing in `src`. **I5·E3·C5 → 8.3** · verified.
- **W11 · Per-section loading/error states** for Recordings/Trash/Search (the inbox does it right). **I3·E2·C5 → 7.5** · verified *(the "stale search results" sub-claim was refuted)*.
- **W12 · SSR the dashboard locale + in-app language switch** — locale is `navigator.language` client-side (flash for RU); `LocaleSwitcher` exists only on landing; no `/ru/dashboard`. **I4·E3·C4 → 5.3** · verified.
- **W13 · `<html lang="ru">` for `/ru`** — currently nested `div lang="ru"` under `lang="en"` (WCAG 3.1.1). **I3·E1·C4 → 12** · verified.
- **W14 · Rollback the dictionary delete** — `:1627` has no snapshot/revert while the dictation-delete sibling does. **I3·E2·C4 → 6** · verified.
- **W15 · Disable dictionary submit in-flight** — `:2772` isn't disabled → double-click dupes. **I2·E1·C4 → 8** · verified.
- **W16 · Folder-form Enter/Escape + tab arrow-keys** — modals lack `onKeyDown`; `role="tab"` strips lack arrow nav. **I2·E2·C4 → 4** · verified (fold into the Dialog primitive).
- **W17 · Shared focus-trapping `Dialog` primitive** — 6+ hand-rolled modals with no focus move/trap/restore (WCAG 2.4.3/2.1.2). **I3·E3·C5 → 5** · verified.
- **W18 · Hardcoded colors → tokens** in `globals.css` (~6 hex literals bypass theming). **I2·E2·C5 → 5** · verified.
- **W19 · Off-canvas mobile sidebar** — at ≤960px the sidebar is a horizontal grid strip, not a drawer. **I3·E3·C4 → 4** · verified.
- **W20 · Split the 4251-line `DashboardClient`** — extract feature panels; enables the memoization/error-boundary wins. **I4·E5·C4 → 3.2** · verified · schedule deliberately.

## macOS
- **M1 · Disk-full crash** — **[S6]** (needs the Obj-C shim). **I5·E2·C4 → 10** · verified.
- **M2 · Orphaned `.localRecording` resume** — `PendingRecordingSyncCoordinator.swift:119` `continue`s past any `.localRecording` forever; a crash mid-record strands the only local copy. → launch-time sweep (no-live-owner / older-than-launch guard), finalize header, upload. **I5·E3·C5 → 8.3** · verified *(shared coordinator → fixes iOS too)*.
- **M3 · Config-change tap reinstall** — observer exists only in dictation; recording capture drops the tap silently on AirPods/device switch. **I5·E3·C5 → 8.3** · staged **[T2]**.
- **M4 · Delete dead `MacTranscriptView`** — instantiated nowhere, but the textbook `ScrollView{LazyVStack}` you migrated away from; the live `SegmentRowView` shares its file so it looks alive. **I3·E1·C5 → 15** · verified.
- **M5 · Live-transcript + timer a11y** — **[S15]**; committed `Text`/timer have no `.updatesFrequently`. **I4·E2·C5 → 10** · verified.
- **M6 · Label icon-only buttons** — ~11–13 icon buttons expose only `.help()`; the detail view's rename pencil already does it right. **I4·E2·C5 → 10** · verified *(corrected count; the cited `CompanionView:826` doesn't exist — Mac Wai is record-only)*.
- **M7 · `bufferCount` Swift-6 data race** — `MacRecordingViewModel.swift:443` `var` mutated from a `Task.detached` closure (debug logging only). **I3·E2·C5 → 7.5** · verified.
- **M8 · Semantic warning/info tokens** — banners hardcode `Color.orange`/`.yellow` + `.black` text (ignores dark mode); `Palette` has no `warning`/`info`. **I3·E2·C5 → 7.5** · verified.
- **M9 · Bound the dictation cleanup SSE** — `DictationManager.swift:1097` awaits with no wall-clock deadline; a wedged stream hangs the commit forever. → race a deadline, fall back to raw transcript. **I4·E3·C4 → 5.3** · verified.
- **M10 · System sleep/wake** — nothing observes `NSWorkspace.willSleep/didWake`; lid-close tears the engine into a dead-but-recording state. **I4·E3·C5 → 6.7** · verified.
- **M11 · Auth-class WS close → re-mint** — `ProviderBackedRealtimeSession.swift:432` maps every close to `.networkLost`; an expired token on an hour-long socket dies with no re-mint. → add `.authExpired`. **I4·E3·C4 → 5.3** · verified *(file corrected from `WebSocketManager`)*.
- **M12 · `session.json` cross-process coordination** — `.atomic` write + per-process queue only; dev+prod racing a refresh signs both out. → `NSFileCoordinator`/lockfile. **I4·E3·C4 → 5.3** · **[D6-adjacent]**.
- **M13 · Defer-commit (1.5s) vs handshake (10s)** — a slow connect lets `commit()` return empty and drop the press. **I3·E3·C4 → 4** · verified.
- **M14 · System-audio format on device change** — `SystemAudioCapture` bakes `nativeSR` into the IOProc; switching output sink mid-record garbles audio. **I3·E3·C4 → 4** · verified (fold into M3).
- **M15 · Dynamic-Type typography** — all 14 `DesignSystem` type tokens are fixed `.system(size:)`; "Larger Text" scales nothing. **I4·E3·C4 → 5.3** · verified. *(See Craft.)*
- **M16 · `.task`/`.defaultFocus` over `DispatchQueue.main.async{focus=true}`** — 2 fragile focus pokes. **I2·E2·C5 → 5** · verified (low value).
- **M17 · `Equatable` transcript/list rows** — not `Equatable` (inbox rows already are). Largely subsumed by M18 — pick one. **I3·E3·C4 → 4** · verified.
- **M18 · `MacAppState` + streaming VMs → `@Observable`** — `WaiComputerMacApp.swift:626` is a 15-`@Published` `ObservableObject`; ticking `duration`/`currentTranscript` invalidates every observer — root cause of the accent cache + Equatable gates + scroll battles. **I5·E4·C4 → 5 (strategic)** · verified · schedule deliberately.
- **M19 · Lazy onboarding slides** — all slides realized eagerly. **I2·E2·C4 → 4** · verified (low value).

## iOS
- **I1 · `PrivacyInfo.xcprivacy`** — **[S5]** (App Store hard blocker). **I5·E2·C5 → 12.5** · verified.
- **I2 · Skip-past-mic-permission dead-end** — `OnboardingView.swift:185` Skip jumps past the permission page; a new install can finish with the mic never requested → non-functional app. macOS fixed this; iOS regressed it. **I4·E2·C5 → 10** · verified.
- **I3 · `UIBackgroundModes` / pause-on-background** — no entitlement + no scenePhase pause → screen-lock truncates a recording. **I5·E2·C5 → 12.5** · **[D2]**.
- **I4 · `AVAudioSession.interruptionNotification`** — zero observers → a call/Siri stops capture while the UI says "Recording…". **I5·E3·C5 → 8.3** · **[D3]**.
- **I5 · Orphaned-recording resume (iOS)** — same `.localRecording`-skip + no `serverRecordingId` persisted pre-upload. Fix in the shared coordinator (M2). **I5·E3·C5 → 8.3** · verified.
- **I6 · Remove/gate fake Settings screens** — `StorageView` shows literal `125 MB`/`2.3 GB`, `ExportView` buttons are empty `{}`, `AudioSettingsView` toggles dead `@AppStorage`. App Store 2.1 + "no fake data". **I4·E2·C5 → 10** · verified.
- **I7 · Live-transcript + timer a11y** — **[S15]** (`RecordingView.swift:126`). **I4·E2·C5 → 10** · verified.
- **I8 · Speaker-chip 44pt target + label** — `SpeakerChipButton.swift:14` is a `.caption` button below 44pt next to tap-to-expand. **I3·E1·C5 → 15** · verified.
- **I9 · Record-button brand accent** — `RecordingView.swift:464` idle returns `.blue` in an amber app. **I2·E1·C5 → 10** · verified.
- **I10 · Localize the Settings subtrees** — `SettingsView.swift:354` + `IdentityAndVoiceSettingsView` use raw `Text("…")` behind translated rows. **I3·E2·C5 → 7.5** · verified.
- **I11 · Route the Library row through tokens + locale dates** — `LibraryView.swift:1124` raw `.headline`/`.caption` + `.formatted()` (wrong-language dates when in-app lang ≠ system). **I3·E2·C5 → 7.5** · verified.
- **I12 · Topic/people chips → Palette + Capsule** — `RecordingDetailView.swift:573` hardcoded blue + `cornerRadius(16)`; iOS's own `ItemDetailView` does it right. **I3·E2·C5 → 7.5** · verified.
- **I13 · Reconcile the divergent audio-session config** — dead `AudioManager` vs the real `.record`/`.default` path (STT-degrading, no Bluetooth). → one coordinator, `.measurement`+`.allowBluetooth`+route-change observer. **I4·E2·C4 → 8** · verified.
- **I14 · Re-check mic permission on scenePhase** in the recording surface. **I3·E2·C4 → 6** · verified.
- **I15 · Permission-DENY recovery for returning users** — `OnboardingView.swift:145` gates "Open Settings" on a session flag. **I3·E2·C5 → 7.5** · verified.
- **I16 · Universal Link for the magic-link token** — `WaiComputerApp.swift:493` accepts the one-time token over a hijackable custom scheme; no `applinks:`. **I4·E3·C4 → 5.3** · verified.
- **I17 · Debounce the sync-loop restart** — every foreground/token-refresh resets backoff to 0 → hammers a failing server. **I3·E2·C4 → 6** · verified.
- **I18 · Unify the two search experiences** — Library button-submit vs Materials live-debounce. **I4·E3·C4 → 5.3** · verified.
- **I19 · Restore iPhone dictation** — `Features/Dictation/` ships only dictionary/history/language UI, no recorder; the shared `DictationSession` is unwired. **I4·E3·C4 → 5.3** · verified.
- **I20 · Bring an Ask-the-Brain surface to iOS** — capture+chat+search but no `/brain/ask` caller. **I4·E4·C4 → 4 (strategic)** · **[D12]**.

## Security & Privacy
- **SEC1 · SSRF + size cap** — **[S7]**. **I4·E2·C5 → 10** · verified.
- **SEC2 · reset_password → revoke refresh tokens** — **[S2]**. **I4·E1·C5 → 20** · verified.
- **SEC3 · Hash magic-link/reset tokens at rest** — `auth.py:528/571` store + compare plaintext (refresh tokens are hashed). **I4·E2·C5 → 10** · verified.
- **SEC4 · Share links never expire** — `RecordingShare` has `revoked_at` but no `expires_at`; an eternal unauthenticated bearer URL to a full transcript. **I4·E2·C5 → 10** · verified.
- **SEC5 · Wire the dead `untrusted.py` boundary** — `wrap_untrusted`/`redact_secrets` have zero callers; transcripts/notes/web text hit the tool-calling LLM unfenced and secrets are embedded unredacted. **I4·E2·C5 → 10** · **[D5]**.
- **SEC6 · Hash OAuth DCR `client_secret`** — `mcp_oauth.py:439` plaintext. **I3·E2·C4 → 6** · verified.
- **SEC7 · No "log out everywhere"** — `auth.py:775` revokes only the presented token. **I3·E2·C5 → 7.5** · verified.
- **SEC8 · Refresh-token reuse detection** — rotation without `family_id`. **I3·E3·C4 → 4** · **[D6]**.
- **SEC9 · PKCE-S256 + redirect-URI re-match at the app layer** — `mcp_oauth.py:559` delegates both to FastMCP with no backstop. **I3·E2·C4 → 6** · verified (defense-in-depth).
- **SEC10 · email-verify single-use** — `confirm_email` JWT is replayable for 24h. **I3·E2·C4 → 6** · verified.
- **SEC11 · `get_optional_user` read-only guard** — skips the `SAFE_METHODS` check; a read-only PAT can POST the anonymous benchmark vote (low value). **I2·E1·C5 → 10** · verified (defense-in-depth).

## Data Integrity & Sync
- **DAT1 · Orphaned `entity_mentions` on hard-delete** — **[S13]** (counts-only inflation; mentions cleanup + orphan-safe `wake_up` count). **I4·E2·C5 → 10** · verified.
- **DAT2 · `entity_facts` on delete** — bi-temporal table orphans silently. **I4·E2·C5 → 10** · **[D8]**.
- **DAT3 · summary-audio stuck-RUNNING recovery** — no recovery beat (summary-generation has one) + no retry → stuck until the 6h visibility timeout. **I3·E2·C5 → 7.5** · verified.
- **DAT4 · `brain_maps` deleted_at filter** — `brain_maps.py:784` leaks soft-deleted sources into the knowledge map; `brain_graph` filters them. **I3·E2·C5 → 7.5** · verified.
- **DAT5 · Optimistic concurrency on recording PATCH** — `recordings.py:2096` is blind last-writer-wins. → `expected_updated_at` → 409. Needs coordinated client work. **I3·E3·C4 → 4** · verified.
- **DAT6 · Tombstone propagation** — `recordings.py:1199` filters `deleted_at IS NULL` even with `updated_after`. **VERIFIED but currently INERT** (no first-party client sends `updated_after`). **I4·E4·C5 → 5** · verified · value-deferred.
- **DAT7 · Watermark keyset boundary** — `recordings.py:1207` `WHERE updated_at > :ts` + composite `ORDER BY` + `OFFSET` skips ties. Also INERT. → row-value cursor. **I4·E2·C4 → 8** · verified · value-deferred.
- **DAT8 · Dossier-recompute on source removal** — `_mark_dossier_dirty` fires only on add. **Gated behind a default-off flag → likely inert in prod** (confirm `backend.env`). **I3·E2·C5 → 7.5 (latent)** · **[needs-decision: confirm flag]**.

## Performance & Scale
- **PRF1 · Release the DB connection across LLM awaits** — `(4+2)×2 = 12` fleet-wide; `/brain/ask` holds its connection across embed+rerank+Cerebras → ~12 concurrent asks stall the whole API. **I5·E3·C5 → 8.3** · staged **[T1]** + **[D10]** (hardest scaling cliff).
- **PRF2 · Truncate `content` in SQL** — **[S3]**. **I4·E1·C5 → 20** · verified.
- **PRF3 · `/brain/ask` answer cache** — none; identical re-asks re-pay retrieval + Cerebras. → Redis fail-open, keyed on `(user, sha256(q), scope)`. **I4·E2·C5 → 10** · verified.
- **PRF4 · `llm_guard.py` cost guard** — `transcription_guard.py` is Deepgram-only; title/summary/synthesis/ask/agents/consolidation are uncapped. → clone the guard (fail-open). **I4·E3·C5 → 6.7** · verified.
- **PRF5 · Project the `list_items` query** — `items.py:540` `select(Item)` hydrates the full `body` Text (MBs) per row but never serializes it, + a per-page COUNT. **I4·E2·C5 → 10** · verified.
- **PRF6 · SQL aggregates for `/analytics`** — `recordings.py:1366` `selectinload(segments)` then sums word counts in Python (millions of rows). → `func.sum(billed_word_count)`. *(weekly-digest does NOT load segments — that claim refuted.)* **I4·E2·C4 → 8** · verified.
- **PRF7 · Split Celery transcription vs control queues** — one queue + `prefetch=1` lets a long transcription starve the every-minute recovery beats. **I4·E3·C4 → 5.3** · verified.
- **PRF8 · Fold the 3 folder-count scans into one `UNION ALL`** — `folders.py:57` does 3 grouped scans per `list_folders`. **I3·E1·C5 → 15** · verified.
- **PRF9 · Hash-cache title generation** — `summarizer.py:792` is the only LLM path with no content-hash cache. **I3·E2·C5 → 7.5** · verified.

## Observability, QA & Release
- **OBS1 · Celery correlation-id** — **[S12]**. **I5·E2·C5 → 12.5** · verified.
- **OBS2 · Breaker-open alert** — **[S11]**. **I5·E2·C5 → 12.5** · verified.
- **OBS3 · Backend↔Swift/.NET contract test** — clients hand-code wire shapes; a field rename / the Decimal-as-string bug ships green and breaks on-device. → snapshot `app.openapi()` examples into `fixtures/`, decode in both client suites. **I5·E3·C5 → 8.3** · verified.
- **OBS4 · `/health/ready` Redis probe** — readiness checks DB only; returns 200 while Redis is down. **I4·E2·C5 → 10** · **[needs-decision: reachability vs queue-depth]**.
- **OBS5 · Recurring-payment-failure Sentry capture** — `billing_renewals.py:152` swallows the failure with an untagged log → revenue loss invisible. **I4·E2·C5 → 10** · verified.
- **OBS6 · Gate backend/web tests in pre-push (or CI)** — `.git-hooks/pre-push:44` runs nothing for backend/web-only pushes; no `.github/workflows/`. **I4·E2·C5 → 10** · verified.
- **OBS7 · Capture nightly-task silent failures** — the live consolidator swallows per-user failures; `recompile_entity_dossiers.py:53` clears `dossier_dirty` even on failure (permanent stale; latent—gated off). **I4·E2·C5 → 10** · verified.
- **OBS8 · MCP request-context + tool-error tags** — MCP traffic is anonymous in logs/Sentry. **I4·E2·C4 → 8** · verified.
- **OBS9 · Migration up→down→up round-trip test** — 11 data-mutating migrations have no-op downgrades → un-rollback-able prod schema. **I4·E2·C4 → 8** · verified.
- **OBS10 · Recovery-sweep cycle-2 test** — the stale-recording sweep isn't driven through its `asyncio.run` wrapper across ≥2 cycles (the NullPool bug hits cycle 2+). **I4·E2·C4 → 8** · verified.
- **OBS11 · Post-deploy `api-smoke.sh` on the documented path** — `deploy-server.sh` ships with no functional smoke (only `qa-loop.sh` runs it). **I4·E2·C5 → 10** · verified.
- **OBS12 · Web + Android funnel Sentry capture** — web has zero `captureException` + no boundary; Android's guest delete-on-`failed` path is uncaptured. **I4·E2·C5 → 10** · verified.
- **OBS13 · Billing state-transition tests** — `test_billing_tinkoff.py:487` asserts only `is not None`; no next-charge-date / partial-batch / money-taken-write-failed tests. **I5·E3·C4 → 6.7** · verified.
- **OBS14 · De-flake the WS handshake test** — green-when-slow 1.5s wall-clock boundary masks the lost-wakeup regression. **I3·E2·C4 → 6** · verified.
- **OBS15 · DB-pool / queue-backlog alerts** — no alert on pool exhaustion (the PRF1 cliff) or queue depth. **I4·E3·C4 → 5.3** · verified (alert-only).
- **OBS16 · Latency/error-rate metrics + SLOs** — only per-call log lines; no exporter. **I3·E3·C4 → 4** · verified (foundational).
- **OBS17 · Stale-recovery runbook entry** in AGENTS.md. **I3·E1·C4 → 12** · verified (cheapest).

## Accessibility, i18n, Design System & Code Health
**A11y** — Streaming-Ask live region (`CompanionPanel.tsx:877`, +throttle scroll) **12.5** · Summary-audio player label + transcript link (`SummaryAudioControls.tsx:54`) **6** · Auth errors tied to field (`AuthForm.tsx:390`) **6** · Segmented-picker `.accessibilityValue` **6** · Honor reduced-motion on native (zero `accessibilityReduceMotion` in macOS/iOS/kit) **10** · iOS material-delete confirmation **15** · Keyboard path for inbox DnD (Mac already ships a per-row menu) **4** · Mac rename hover-only discoverability **4**. All verified.

**i18n** — Localize shared `UserFacingErrorFormatter` (every Mac+iOS error English-only) **10** **[D11]** · Web localized error map (`http.ts:121` raw English `detail`) **5.3** · Items honor `summary_language` **7.5** · Russian 3-form pluralization **4** · iOS dates follow in-app locale (`LibraryView.swift:1146`; web already does) **7.5** · Billing emails key off `default_language` not `region` **12** · Telegram bot chrome localization **3.75**. All verified.

**Design system** — Unify brand amber (iOS `#d17c2d` vs Mac/web `#ff9500`) **10** · Motion + Radius token scales for Swift (`cornerRadius:999`→`Capsule()`) **Radius 7.5 / Motion 5** · web `<EmptyState>` component · unify iOS empty states (native vs compat shim) · shared native skeleton · shared haptics/feedback contract · converge the search affordance. All verified.

**Code health** — passlib → bcrypt (preserve 72-byte truncation) **[S8]** · remove dead web graph deps **[S4]** · Android `targetSdk` 35→36 (Aug 31 2026 deadline) **7.5** · realtime `try!`+`.utf8!` force-unwraps (`WebSocketManager.swift:397`) **8** · silent JSON `"Done"` fallback (`companion.py:3020`) **15** · dictation-store `FileManager…first!` force-unwraps **15** · type the LLM/webhook `dict` payloads **4** · split `telegram.py` (4019 lines) + `APIClient.swift` (2410 lines) **2.4** (schedule deliberately). All verified.

## Product, Positioning & Monetization
- **Lead with the cited agent-memory wedge** — the landing sells a 5th transcription tool; the moat is the cited, revocable, read-only-by-default MCP memory bank (headless-MCP is now *the* product). → hero pillar + connect-card grid + "Wai verified" badge; mirror `/ru`. **I5·E2·C4 → 10** · verified.
- **Reconcile the free-tier promise** — **[D7]**. **I4·E1·C5 → 20**.
- **Add Telegram Stars billing** — Apple killed RU IAP (Apr 2026); Tinkoff is web-only → mobile RU users can't pay. **I4·E3·C4 → 5.3** · verified (genuinely absent in code).
- **Public `/developers` front door** — the connect cards + PAT + `wake_up()` live only inside authenticated Settings. **I4·E2·C5 → 10** · verified.
- **One-tap connect *UI*** — `mcp_connect.py:70` already mints+smoke-tests scoped tokens + returns a catalog; Settings still shows copy-a-URL. **I4·E3·C5 → 6.7** · verified.
- **Productize freshness/staleness** — `ask()` already returns `freshness`+`gaps` (mem0 calls staleness *the* unsolved problem). **I4·E2·C4 → 8** · verified.
- **Pro+/Brain tier (~$20)** — only Free + Pro ($12) exist; the agent-memory/graph value has no line item. **I4·E2·C4 → 8** · **[needs-decision: tier design]**.
- **Trust/privacy as a positioning surface** — strong, shipped guarantees buried in one FAQ line. **I3·E2·C4 → 6** · verified.
- **Claim the vacated Limitless category + re-anchor off meeting-notes** (Limitless → Meta Dec 2025; Granola $1.5B). **I4·E2·C4 → 8** · verified.
- **Make RU-language + local-rails a three-way moat** (RU quality + Tinkoff/Stars + Western SaaS sanctioned out). **I3·E2·C4 → 6** · verified.
- **Rewrite the drifted SPECS.md** — still declares an "AI Operating System / App Builder" north star vs the shipped product. **I3·E1·C4 → 12** · **[D12-adjacent]**.
- **On-device/private STT decision** — privacy is a pillar yet all audio ships to Deepgram. **I3·E2·C4 → 6** · needs-decision.
- **"Export my brain"** — only a partial Telegram dump exists; portability + GDPR + trust signal. **I3·E2·C4 → 6** · verified.

## Activation, Retention & Journeys
- **Close the action-item loop** — backend `PATCH` + Swift `updateActionItem` exist with zero callers; Mac/iOS render a non-interactive checkmark, web has no binding, MCP has `list` but no `complete`. *(Already live+tested on Android + desktop Core.)* → tappable checkbox on Mac/iOS/web + a `complete_action_item` MCP tool + a `completed_at` column. **I5·E2·C5 → 12.5** · **[D9]**.
- **Instrument activation + retention** — zero analytics on any platform, no `last_active_at`, no events table → DAU/WAU/D1-7-30 unknowable. Foundation for every loop below. **I5·E3·C5 → 8.3** · verified.
- **Deliver the weekly digest + since-last-seen badge** — `GET /digest/weekly` (no delivery beat) + `GET /since-last-seen` (zero clients) are fully built and dark. **I4·E2·C5 → 10** · verified (delivery needs the push spine).
- **Agent-activity ledger + fix `source="agent"`** — `mcp_brain_tools.py:369` hardcodes `source="agent"`; no tool-call log → a developer can't audit what an agent stored/accessed. **I5·E3·C5 → 8.3** · verified.
- **"What Wai knows about you" view/edit** — `wake_up`'s durable profile drives every agent but has no view/edit surface (`memory_proposals` API is still live; only the UI was removed). **I4·E3·C5 → 6.7** · verified.
- **Restore an Ask surface + gaps→capture** — the honest-gaps backend surfaces only as chat text; a gap is a dead end. **I4·E3·C5 → 6.7** · **[D12]**.
- **Brain "Cards-That-Think" home** over `/brain/feed` (zero client). **I5·E3·C5 → 8.3** · **[D12]**.
- **Push-notification spine** — no APNs/FCM, no `device_tokens`; no channel to re-engage a closed-app user. Prerequisite for the loops above. **I5·E4·C5 → 6.25** · verified.
- **Server→client library sync** — everything is pull-only; record on iPhone, Mac/web stays stale. **I4·E3·C4 → 5.3** · verified. **Sync the Wai chat list** the same way. **I3·E2·C4 → 6** · verified.
- **Break the 100-recording wall** — clients fetch `limit:100` once, never paginate (pairs with B12). **I4·E2·C4 → 4** · verified.
- **Payment grace-period + dunning ladder** — `billing_renewals.py:152` flips to `PAST_DUE` on the first decline with no buffer. **I4·E2·C4 → 4** · verified.
- **Self-serve GDPR "export all"** (only scoped exports exist). **I3·E2·C4 → 6** · verified.
- **"On this day" resurfacing** — the feed is recency-only. **I3·E2·C4 → 6** · verified.
- **Android: don't delete the guest's only copy on a server-side failure** — capture the path + don't local-delete before a confirmed `ready`. **I4·E2·C4** · verified.

---

## Execution Sequence (waves 0–4)

**Wave 0 — hours each, ship today:** S1 onboarding-mount · S2 reset→refresh-tokens · S3 SQL truncate · S4 dead deps · S16 forget-defensive · D7 free-tier copy · W4 hreflang · PRF8 folder-count UNION · silent-`"Done"` removal · OBS17 runbook.

**Wave 1 — this week (correctness/safety/data-loss, before more users/real money):** S5 PrivacyInfo · S6 disk-full (Obj-C shim) · S7 SSRF · S8 passlib · S13 entity-mention cleanup · I2 skip-past-mic · **[D2/D3]** iOS recording-safety (interruption/background/orphan-resume M2/I5) · **[D4]** Tinkoff idempotency + OBS5 failure capture · **[D5]** untrusted.py · **[D8]** entity_facts · Android guest-copy preservation · DAT6/DAT7 tombstone+keyset (server-side, value-deferred).

**Wave 2 — search quality + scale:** S9 HNSW (2 tables) + T3 `segments` probes · S10 Deepgram timeout · S11 breaker-alert + S12 correlation-id · OBS4 `/health/ready` · OBS7 nightly-failure capture · **[D1]** reranker (after key + A7 eval gate) · **[D10]/T1** DB-connection relief slice · PRF3 ask-cache · PRF4 llm_guard.

**Wave 3 — the act + recall loop + safety nets:** **[D9]** action-item loop (Mac/iOS/web/MCP) · **[D11]** Brain output-language + shared error formatters · agent-activity ledger + "what we know about you" · **[D12]** Ask surface / Brain home / SPECS.md · cross-device sync · OBS3 contract test + OBS6 CI gate · OBS9/OBS10 migration+recovery tests.

**Wave 4 — polish, parity, positioning (continuous):** the a11y bundle · the i18n bundle · design-system unification (brand amber, motion/radius, reduced-motion, iOS row/chips) · client perf (W7/W10 + M18 `@Observable`) · strategy (agent-memory wedge, `/developers`, Telegram Stars, Pro+ tier, freshness).

---

## Verified solid — don't re-litigate
Single Alembic head · MCP tenant isolation + write-scope + PAT read-only · NullPool in Celery · thorough PII sanitization (`observability.py`) · explicit CORS allowlist (not `*`) + `SameSite=Lax` (CSRF safe) · IDOR/BOLA (every route filters `user_id`) · admin gating (`require_admin`, fail-closed) · path traversal (UUID paths + `is_relative_to`) · the MCP approval gate (HMAC + `compare_digest`, fail-closed) · `strict` TS with zero `any` in web source · transcript-merge shared byte-for-byte across backend/web/Swift · FOUC-safe theme/accent script · WCAG-AA token work in `Palette`/`tokens.css` · web skip-to-content link (`layout.tsx:66`) · inbox already cursor-paginated + stale-guarded · `brain_graph` overview counting already single-pass.

## Cut in this curation pass (refuted/duplicate — do not re-add)
- **"recordings/items lack ANN indexes → seq scans"** — those doc-vectors aren't queried by `unified_search`; `segments` is already ivfflat. Only `item_chunks`+`conversation_chunks` need HNSW.
- **"Two contradictory Cerebras price tables"** — intentional (eval heuristic vs billing ledger).
- **"Dictation cleanup → `none`/minimal reasoning floor"** — gpt-oss-120b's API floor is already `"low"`; `"none"` isn't supported.
- **"Android deletes the guest's only copy on `failed`"** — `localRecordingStore.remove()` runs only on success; kept only the capture/guard hardening.
- **"Apple must persist serverRecordingId before upload (DAT-4)"** — Apple uploads with a client id to an idempotent endpoint; no duplicate window.
- **"Media-import child-row swap isn't atomic"** — already single-transaction.
- **"Mac live transcript is one ever-growing `Text`"** — already split committed/interim in a `LazyVStack`.
- **"Mac Brain composer needs an empty state"** — Mac Wai is record-only with an existing empty state.
- **"iOS tab tags are scrambled — renumber them"** — intentional backward-compat for build-42 `@AppStorage`.
- **"Web skip-to-content link missing"** / **"Web dates ignore in-app locale"** / **"next/image for hero icons"** / **"Search keeps stale results"** — all already handled in code.
- **"`forget` is an open mutating hole"** — already fail-closed; kept only as one-line defensive clarity (S16).
- **Verified-safe security items** (IDOR, CSRF, admin gating, path traversal, MCP approval gate) — confirmed solid, not findings.
- **PRF "brain_graph O(N²)"** + **"weekly-digest loads all segments"** — refuted (already single-pass / loads summaries not segments).
- Low-value/net-new-feature items dropped from the queue: iOS Share Extension / App Intents / Live Activity / `@SceneStorage`; "dictation-that-remembers" positioning; reconcile-onboarding-scripts; web guest mode (premature pre-analytics).

---

*Curated 2026-06-14 by a 12-agent scoring + re-verification pass over the full multi-iteration review. Every kept finding was re-read at `file:line` against current `main`; refuted/duplicate/low-value items were removed. Next action: implement the ✅ Ship-Ready-Now queue and make the 12 ⚠️ decisions to unlock the rest.*
