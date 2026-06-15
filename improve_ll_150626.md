# WaiComputer — Deep Audit + Competitive Intelligence (12-agent ultracode pass) · 2026-06-14

> **Loop check 2026-06-15 07:32** (hourly `d0aa0747`, delta-gated): still **no code change** since the ultracode pass — HEAD `f2c5e2619` unchanged, clean tree (8th static fire). 3 items still OPEN: 🔴 billing permanent-unrenewed · 🔴 AVAudioSession interruption · 🔴 keystone `EntityFact`→`ask_brain`. No agents run (delta-gate held); loop stays armed to trip on the next real push.

> 12 agents (ultracode workflow `wf_35dd56ab`): **6 competitive-research agents** (meeting · AI-notes/second-brain · ambient-memory · voice-dictation · hardware · content/MCP-agents) + **6 code-re-audit agents** across **all platforms incl. Android/Windows/Linux** (previously excluded). 856K tokens, 467 tool-uses, ~14 min. Competitive research via WebSearch (June 2026); code audited at HEAD `f2c5e2619`. Companion to `improve_ll_140626.md` (the technical reference); this file adds the **competitive + product-strategy** layer and an **updated P0 verification**.

---

## 0. The thesis (your partner's read)

The competitive research and the code audit converged on one conclusion: **WaiComputer has built genuinely rare, hard-to-replicate architecture — but several of its strongest pieces are unplugged, underexposed, or not productized as differentiators, and competitors are closing in on exactly those.**

- **Unplugged:** the bi-temporal `EntityFact` model exists but `ask_brain` never queries it (audit F3d-8, OPEN). Meanwhile **Zep/Graphiti are making bi-temporal facts their entire 2026 marketing pitch** — you have it built and switched off.
- **Underexposed:** you shipped `wai.computer/mcp` first — but **Otter, Granola, and Read.ai now ship MCP as a headline feature**. The moat you invented is eroding because it's a Settings URL, not a marketing surface.
- **Not productized as a differentiator:** cited, provenance-linked memory (every fact links back to the exact recording/moment) is **the one thing ChatGPT/Claude memory structurally cannot do** (they have no recordings). It's buried, not the hero.
- **The capture → action gap:** the 2026 category move is "agents that *act*, not just summarize" (Tana files Linear issues mid-meeting; Granola fires Zapier follow-ups; Grain writes back to CRM). Your MCP tool-safety layer is the ideal substrate for this but no turnkey write-back flows exist.

**The window is now.** Rewind.ai/Limitless shut down (Dec 19 2025, Meta acquisition) and orphaned power users — an open acquisition wedge. Convert latent architecture into visible moat before Zep owns "temporal memory," before Otter/Granola own "MCP brain," before Tana owns "typed-entity action."

The two live technical chains remain: 🔴 **billing permanent-unrenewed** (Chain A) and 🔴 **AVAudioSession/audio-focus interruption handling** (Chain B — now confirmed across **all 3 native clients**, not just iOS).

---

## 1. Competitive intelligence — best features to steal (ranked, converged across 6 niches)

Across meeting recorders (Otter, Fireflies, Grain, Read.ai, Granola, Fathom, tl;dv, Tactiq, Avoma), AI-notes/second-brain (Tana, Granola, Notion AI, Capacities, Heptabase, Mem, Obsidian+AI, superwhisper), ambient memory (Mem0, Zep/Graphiti, Fabric, Recall, Omi, Saner, Plaud, Limitless/Meta, ChatGPT/Claude memory), voice dictation (Wispr Flow, Superwhisper, Monologue, Voicenotes, Dragon, Apple), hardware (Plaud, Omi, Limitless pendant), and content/MCP (Descript, Riverside, Cursor, Claude Desktop, ChatGPT Apps), the same ~18 opportunities recurred. Ranked by impact-to-effort:

| # | Opportunity | Source apps | Impact | Why now |
|---|---|---|:---:|---|
| 1 | **Wire `EntityFact` into `ask_brain` + NL temporal queries** ("what changed about X since Y") | Zep/Graphiti (their whole pitch), ChatGPT/Claude memory | **10** | You built it; it's unplugged (F3d-8). Ship first or Zep owns the category. Highest-leverage moat move, code exists. |
| 2 | **External connectors / federated cited search** (Slack, Linear, Drive, GitHub, Notion) | Notion AI Enterprise Search, Granola (8000-app Zapier), Read.ai | **10** | Notion's 2026 wedge is "search beyond your notes." Your MCP brain + `source_fetch` are the substrate no competitor has. Turns "voice brain" → "whole-work brain." |
| 3 | **OS-wide dictation "Command Mode"** — highlight text + speak a transform → replace in place | Wispr Flow (paid), Superwhisper, Dragon | **10** | You have every building block (`DictationContextCollector` grabs selection+app+context, LLM cleanup runs). One second hotkey + route. Wispr gates it paid for a reason. |
| 4 | **Agentic write-back actions** — companion extracts action items → creates Linear/Jira/Slack/CRM | Tana (issues mid-meeting), Grain (CRM write-back), Read.ai (Ada agent) | **9** | The 2026 category move: capture → action, not capture → text. Your MCP tool-safety layer is half-built for this. |
| 5 | **Visible, editable "Memory" panel** — every fact links to its source recording/moment + ChatGPT/Claude memory import | ChatGPT/Claude memory (opaque, uncited), Mem0 | **9** | The single sharpest differentiator: platform memory is free but **opaque and uncited**; your provenance-linked memory is structurally impossible for them. Make it the hero. |
| 6 | **Cross-recording "Action Items" dashboard** — aggregate every spoken commitment with due dates/owners, each cited | Otter (My Action Items — stickiest feature), Granola, Saner | **9** | You have all transcripts; extracting "I'll send it Friday" into a cited task view is high-value, low-risk, monetizable. |
| 7 | **Typed entities as first-class browsable objects** — People/Projects/Decisions views + saved live queries | Tana (supertags, search nodes), Capacities (object notes) | **9** | The user-facing flip of #1: render `EntityFact` as Tana/Capacities-style typed nodes. Lowest-cost way to convert architecture into a visible feature. |
| 8 | **MCP write-back memory tools** — `add_memory` / `update_fact` / `invalidate` / `search_memory` | Mem0 / OpenMemory, Screenpipe | **8** | Mem0 proves write-back is the killer MCP use case. Yours is read-only today. Small surface change, big value: "library" → "living memory agents maintain." |
| 9 | **Output/extraction templates** (standup, 1:1, sales-MEDDIC, interview, medical) | Granola (29 templates), tl;dv (MEDDIC/BANT), Tana | **8** | Templates materially improve perceived quality + open verticals (medical/legal/sales). Days to ship on existing summarization. |
| 10 | **Local-first / on-device tier** (offline Whisper on Apple Neural Engine + local embeddings) | Obsidian Smart Connections, Superwhisper, Screenpipe | **8** | Cloud-only (Granola) is the loudest 2026 privacy complaint + churn reason. Your native clients can do this. Defensible vs cloud-only incumbents. |
| 11 | **"press enter" / inline-send voice command** (strip token + emit Enter) | Wispr Flow | **8** | Tiny post-filter rule; closes the chat-send loop. Value-per-line-of-code is extreme. |
| 12 | **Proactive memory nudges + related-content surfacing** ("you mentioned X — 3 past recordings relate") | Saner.AI, Granola (Crunched), Screenpipe (day-recap) | **8** | Proactive beats reactive for daily-return retention. Your hybrid search already computes similarity — expose it as ambient suggestions. |
| 13 | **Auto knowledge-graph extraction at ingest + visual graph view** | Recall (Graph View — most-screenshotted), Omi, Zep | **8** | Auto-populate `EntityFact` from every transcript (no manual curation) + clickable entity explorer. Makes the bi-temporal moat tangible to humans. |
| 14 | **Live collaborative notes + live-updating summary** on realtime transcription | Otter (live collab), Fathom (live summary), Tactiq (in-meeting Ask AI) | **7–8** | Realtime STT is already done in WaiComputerKit; no shared live-edit surface + summaries are post-hoc. Biggest realtime-UX gap. |
| 15 | **Zero-friction auto-organization + chat-as-default-landing** (no folder prompt; AI auto-tags into the graph) | Mem ("never file"), Fabric, Saner | **7** | Folder-first UX adds friction at the exact moment (record) where friction kills capture. Reframes "recordings app" → "AI brain." |
| 16 | **Spatial canvas / board view** over recordings + EntityFacts (use a whole board as companion context) | Heptabase (AI-on-canvas), Obsidian (graph view) | **7** | Differentiated for synthesis-heavy users (researchers/writers); visualizes the unique time-aware graph no competitor has. |
| 17 | **Speaker diarization + per-industry custom vocabulary** as a paid feature | Plaud NotePin S, Otter, Dragon | **7** | Deepgram supports both; expose custom glossaries (medical/legal/tech) + voice-training of hard terms. Near-zero infra, fits existing billing. |
| 18 | **Browser extension + email-forward capture channel** | Recall, Saner, Fabric | **6–7** | Research happens in the browser, decisions land in email — extend capture beyond native apps to grow corpus (the core metric). |
| 19 | **Public citation-accuracy + temporal-recall benchmark** vs plain vector RAG (and Zep) | Zep (DMR benchmark marketing) | **6** | Zep wins deals by waving a benchmark. Your cited hybrid search should beat plain vector RAG measurably — publish it. Cheap, credible marketing. |

### Cross-cutting trends (the "why now")
- **MCP-as-headline, not just available** — Otter/Granola/Read ship it as marketing; ship demo recipes (sprint-planning, Linear-from-standup) + dev-rel or lose the moat you invented.
- **Agents that ACT** (Tana/Granola/Notion) — emit actions to external systems, not just text.
- **Typed/queryable knowledge graphs** (Tana/Capacities/Zep) — entities as first-class; you have it, don't expose it.
- **Federated/connector search** (Notion) — the brain must know Slack/Drive/Linear.
- **Local-first** (Obsidian/superwhisper) — the 2026 privacy flagship; cloud-only is the top churn complaint.
- **Visible/editable memory** (ChatGPT/Claude) — opaque memory is now a liability; portability (import/export between platforms) is rising.
- **Capture commoditizing** (Plaud/Omi/Limitless hardware; Granola/Otter software) — the **brain/search/citation/agent layer is where defensibility lives**. Position as "the brain for *any* capture device."
- **Rewind/Limitless shutdown (Dec 2025, Meta)** orphaned power users + cut off EU/UK — acquisition wedge ("your memory stays yours, in the EU").
- **Pricing** converging ~$14–20/mo individual, $20–40/seat enterprise, with metered $/hr emerging (Recall $0.50/hr). Your Tinkoff+Stripe dual billing supports both.

---

## 2. Strategic product roadmap (cherry-pick, sequenced)

**Phase 1 — Plug the moat (weeks, highest leverage):**
1. Wire `EntityFact` → `ask_brain` + temporal queries (#1). *Unblocks everything below.*
2. Visible "Memory" panel with provenance links + ChatGPT/Claude import (#5).
3. Typed-entity views (People/Projects/Decisions) + saved queries (#7).

**Phase 2 — Brain becomes an actor:**
4. Agentic write-back: extract action items → Linear/Slack/CRM via MCP tools (#4) + cross-recording Action Items dashboard (#6).
5. MCP write-back memory tools `add/update/invalidate` (#8).
6. Output templates (#9).

**Phase 3 — Capture + retrieval breadth:**
7. External connectors / federated cited search (#2).
8. OS-wide Command Mode (#3) + "press enter" (#11).
9. Proactive nudges + auto-KG at ingest (#12, #13).

**Phase 4 — Positioning + moats:**
10. Local-first/on-device tier (#10), browser/email capture (#18), public benchmark (#19), botless/privacy marketing.

> Sequencing logic: #1 is the keystone (it's also a single OPEN code item) — it makes #5/#7/#12/#13 possible and is the direct counter to Zep/Graphiti. Do it first.

---

## 3. Code verification — what changed since `improve_ll_140626.md`

### ✅ Newly FIXED this cycle
| Item | Domain | Note |
|---|---|---|
| Reranker position-fusion inversion (F3d-2) | brain | The semantic-order bug — fixed. |
| `app.conf.visibility_timeout` top-level key | security | The disputed item — resolved (confirmed FIXED). |
| Privacy manifest `NSPrivacyTracking`/collected-types | apple | App Review risk closed. |
| Python `redact_text` → routes through `_SECRET_PATTERNS` | security | PII net widened (10 more secret formats). |
| Swift Sentry `beforeSend`/`beforeBreadcrumb` | apple | PII parity with Kotlin/C# restored. |
| Refresh-token amplification (concurrent 401s) | web | In-flight dedup added. |
| iOS idle-sleep prevention (`isIdleTimerDisabled`) | apple | Long-iOS-meeting suspension fixed. |
| `hasWriteFailure` upload gate | apple | Chain B core data-integrity fixed. |
| `/api/system/info` auth (git_sha/topology) | backend | No longer unauthenticated. |
| Android: guest-migration idempotency, magic-link deep link, WorkManager/Flow correctness, Sentry-sanitizer parity | android | Previously-excluded platform, now mostly sound. |

### 🔴 Still OPEN (the live priority)
| Item | Domain | Impact |
|---|---|:---:|
| **Billing permanent-unrenewed** (failure arm nulls `next_charge_at` on any error, no transient/terminal split) | backend | **9** |
| **AVAudioSession interruption/route-change** + (NEW) timer no audio-liveness guard + category split-brain + never-deactivates-on-stop | apple | **9** |
| **Same Chain B on Android** (F-AND-1: audio-focus loss → silence while timer climbs) + **all 3 native clients lack device-disconnection handling** (unified silent-truncation chain) | native | **9** |
| **EntityFact not queried by `ask_brain`** (F3d-8) — the moat, now the #1 competitive opportunity | brain | **10** |
| Rate-limit + `--forwarded-allow-ips='*'` cluster | backend | 8 |
| SSRF DNS-rebinding TOCTOU | backend | 8 (partial) |
| Plaintext magic-link/reset tokens; refresh-rotation no reuse detection; CSRF | backend | 7–8 |
| Celery beat `-B` SPOF + recovery hard-fails | backend | 7 |
| **Windows is non-functional**: magic-link token discarded by empty stub (F-WIN-1) + hotkey manager never started/dictation unreachable (F-WIN-2) + no UnhandledException hook (F-WIN-3) | windows | 8 |
| **Linux is a non-product**: Record/Stop/Search/Auth/Companion/Updates all unwired stubs (F-LIN-1) | linux | 8 |
| No CI (backend/web/android/mac/linux); no dependency lockfile | devops | 8 |

---

## 4. Notable NEW code findings (not in `improve_ll_140626.md`)

- 🔴 **JWT cross-purpose confusion (NF1)** — access-token decode skips audience, so a realtime/voice JWT can authenticate as the user. + access JWT has no issuer claim and decode doesn't enforce it (NF2). Real auth-broadening bug. *backend*
- 🔴 **Old `idx_segments_embedding` ivfflat never dropped after the HNSW migration (N2)** — the segments-HNSW fix landed but left the old index → **dual-index ambiguity** on the same column (planner may pick the worse one). One-line `DROP INDEX CONCURRENTLY` migration. *brain*
- 🔴 **AudioContext never resumed → silent mic on Safari/iOS web realtime (web-new-1)** — web realtime transcription silently fails on Safari/iOS. *web*
- 🟠 **No security headers** (CSP/HSTS/X-Frame-Options/Referrer-Policy) in `next.config.ts` (web-new-2).
- 🟠 **`ask_brain` synthesis boundary** — full question to `safe_text_digest` but `user_content` built from raw excerpts with no transcript-PII sanitization at the synthesis boundary (N8).
- 🟠 **`keyTerms` silently ignored** in `ProviderBackedRealtimeSession` (apple N4) — no-fallbacks violation; the personalized keyterms feature is dead on the dictation realtime path.
- 🟠 **`sendKeepAlive` swallows send failures** — dead socket not detected until the receive loop times out (apple N6).
- 🟠 **`EntityFact` importance/confidence columns written but never used** in ranking/synthesis (brain N4) — dead signals.
- 🟠 **`rerank_hits` "never return empty" fallback masks a no-relevant-results state** (brain N3) — hides the "nothing found" case.
- 🟡 **Supply-chain**: `wrangler` (Cloudflare CLI) + nodejs/npm shipped in the production API image but unused at runtime (NEW-1); `telegram-bot-api` uses unpinned `:latest` (NEW-2).
- 🟡 **gunicorn worker-count mismatch** — Dockerfile CMD=1 vs compose override=2 (NEW-4); rate-limit/singleton assumptions break across them.
- 🟡 **`/health` leaks `git_sha` + `git_dirty` unauthenticated** (NEW-6) — note: `/api/system/info` was fixed, but `/health` still does.

---

## 5. Priority matrix (unified — competitive + technical)

| Tier | Items |
|---|---|
| **Ship-now (P0)** | Billing permanent-unrenewed split · AVAudioSession interruption (iOS) + audio-focus/device-disconnect (all native) · Windows non-functional (magic-link + hotkey) · Linux non-product |
| **Moat (P0 strategic)** | Wire `EntityFact`→`ask_brain` + temporal queries (#1) · Visible cited Memory panel (#5) · Typed-entity views (#7) |
| **High-leverage product** | Agentic write-back actions (#4) · Action-Items dashboard (#6) · MCP write-back tools (#8) · Connectors/federated search (#2) · Command Mode (#3) · Templates (#9) |
| **Security hardening** | JWT cross-purpose (NF1/NF2) · plaintext tokens · refresh reuse detection · CSRF · rate-limit cluster · SSRF pinning · drop old ivfflat (N2) · AudioContext resume (web-new-1) · security headers (web-new-2) |
| **Reliability/devops** | CI · lockfile · beat split · `/health` leak · image bloat (`wrangler`/`:latest`) · worker-count mismatch |
| **Positioning** | MCP-as-headline + dev-rel · botless/privacy marketing · public benchmark · local-first tier · EU "your memory stays yours" wedge |

---

## 6. Method note
- 12 agents via Workflow (6 competitive WebSearch + 6 code re-audit incl. Android/Windows/Linux). Competitive opportunities are remarkably **converged** (the same ~18 themes recurred across all 6 niches — high confidence). Code verifications read against HEAD `f2c5e2619`.
- This file = **competitive + product strategy + updated verification**. The technical reference (full P0/P1 detail, file:line, prior runs #1–#12) remains in `improve_ll_140626.md`.
- The hourly loop (`d0aa0747`) will re-run a *delta-gated* version — full competitive refresh only periodically; code re-audit on real churn.

*Ultracode pass · 2026-06-14 · `improve_ll_150626.md`. The keystone is #1: wire `EntityFact` into `ask_brain`. It's one OPEN code item, it's the top competitive opportunity, and it's the direct counter to Zep/Graphiti owning the "temporal memory" category. Everything else compounds on it.*
