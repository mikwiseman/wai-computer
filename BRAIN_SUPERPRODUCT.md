# Wai Brain → Super-Product Plan

> **Wai Brain: the second brain that answers what's true *now*, cites every word, forgets the noise — and your agents recall it in one tap.**

*Produced 2026-06-09 by a two-workflow, ~48-agent research+design run (see [Methodology](#methodology)). This is a buildable plan, not shipped code. The Brain is under active parallel development — re-confirm every file:line anchor at build time and work on a worktree off the latest `main`.*

---

## TL;DR

The brief was: make Wai's Brain as powerful as **gbrain**, **karpathy-wiki/qmd**, **mem0**, and **mempalace** (and best worldwide practice as of June 2026), keep it **dead-simple for non-technical users**, and make integrating it into the user's **OpenClaw.ai + Hermes agents** frictionless.

The single biggest finding from mining + adversarial verification: **Wai already ships the rare, hard parts.** Hybrid RRF search, cited single-shot Ask with honest gaps, an entity graph (with `record_relation` now wired), compiled living-wiki dossiers, a *nightly sleep-time consolidator with a governance/review gate*, a FastMCP server with OAuth + PATs, and draft OpenClaw/Hermes providers — all exist today. mem0's "Dream Cycle," Letta's "sleep-time compute," ChatGPT's "Dreaming" — Wai has the equivalent.

So the super-product is **not a rebuild.** It is wiring proven power through machinery that exists, in power-per-effort order, plus the handful of genuinely-missing pieces. Eight phases:

| Phase | What | Why it matters | Effort |
|---|---|---|---|
| **P0·eval** | Golden query→source eval set (RU+EN) | Measure every retrieval change, never vibes | S |
| **P0a** | Per-page max-pool + graph arm + contextual chunking | Stops long meetings burying short notes; cheap recall lift; **invisible** | M |
| **P0b** | `GET /brain/feed` "Cards-That-Think" home + <60s first-wow | The calm, populated front door + instant proof | L |
| **P0c** | One-tap agent connect (OpenClaw/Hermes/Cursor/VS Code) + **server-side smoke-test** | The headline differentiator | M |
| **P1** | Cross-encoder reranker (managed, flagged, RU A/B-gated) | The single biggest precision multiplier | M |
| **P2** | Bi-temporal `entity_facts` (supersede-not-delete) | "What's true *now*" becomes a query, not a guess (+38% temporal) | M |
| **P3** | Living-wiki O(changed) dossier recompile + "what changed" | Dossiers self-heal between dream cycles | M |
| **P4** | Trust×salience×recency ranking + reversible **Forget** | Lights up stored-but-ignored governance signals | M |
| **P5** | `wake_up()` tier + richer agent tools + opt-in resurfacing | Agents recall-before-asserting; anti-write-only brain | M |

**Five decisions need Mik** (see [Decisions](#decisions-for-mik)): reranker provider (managed vs self-host — a privacy call), how to reconcile with the in-flight "Brain is a wiki" work, which phases to greenlight first, supersession aggressiveness, and the onboarding first-wow style.

---

## Methodology

Two background workflows, 48 subagents, ~4.9M agent tokens, all sources current to **June 2026**:

- **Workflow A — mine & score** (36 agents, 3.66M tok): 14 parallel deep-miners (4 named refs + 10 worldwide best-practice areas) → editor dedup into a **71-mechanism catalog** → 3 independent scorers (pragmatist / architect / integrator) on a 5-axis rubric (power · ease-for-non-tech · agent-fit · Wai-fit · low-effort) → **18 top picks adversarially pressure-tested** (every one came back *adopt* or *adapt*; none *skip*).
- **Workflow B — design & verify** (12 agents, 1.27M tok): 6 specialist design tracks (each reading the real code) → one architect synthesis. *The 4 adversarial critics + final revision hit the API session rate limit; that adversarial pass + finalization was done by me inline (I'd read every design-critical file and all 18 verdicts) — see [My critique](#my-adversarial-pass).*

**Primary sources mined (real code/papers, not blogs):** gbrain `v0.42.37.0` (Garry Tan/YC), mem0 `v2.0.4` + v3 docs, mempalace, qmd (Tobi Lütke, the "karpathy-wiki" referent), Letta/MemGPT (`sleeptime`), Zep/Graphiti (`arXiv:2501.13956`), Microsoft GraphRAG + adversarial re-evals, Anthropic Contextual Retrieval, Stanford Generative Agents (`arXiv:2304.03442`), ChatGPT "Dreaming" V3 (2026-06-04) / Claude / Gemini / Copilot memory, Supermemory MCP 4.0, Hermes (NousResearch) + OpenClaw memory providers, EchoLeak `CVE-2025-32711`.

The adversarial pass earned its keep — it caught that several "top" mechanisms were **already shipped** in Wai (sleep-time consolidation, governance proposals, the Hermes provider), that mem0 **reversed** ADD/UPDATE/DELETE → ADD-only, that one cited paper was **fabricated**, that gbrain's "one-command connect" is a CLI that can't ship to non-technical SaaS users, and that Cerebras has **no prompt-cache discount** (so the contextual-retrieval cost story had to change).

---

## What Wai Brain already has (verified June 2026)

- **Hybrid search** — `unified_search.py`: RRF (k=60) over recordings(segments) + items(item_chunks) + chats(conversation_chunks), Russian FTS + pgvector cosine, 30-day recency half-life, pool=limit×3.
- **Cited Ask with honest gaps** — `brain_ask.py`: retrieve → diversity cap (2/source) → Cerebras strict-JSON synthesis → cited answer + gaps + freshness; citations validated against the retrieved set; evidence-only.
- **Entity graph** — `entity_graph.py`: `upsert_entity` (identity-key then exact-name dedup), `record_mention` (source→entity), and **`record_relation` (entity→entity, now wired at ~`:376`)**; zero-LLM extraction for bulk synced items.
- **Living-wiki dossiers** — `entity_page_synthesis.py` → `EntityPageSnapshot`, cached by `source_fingerprint`. **macOS 1.0.36 (207) shipped "Brain is now a wiki."**
- **Sleep-time consolidation + governance gate** — `tasks/consolidate_user_memory.py` (nightly 03:00 UTC, "Letta sleep-time × gbrain Dream Cycle") → `core/memory_proposal.py` (additive + confidence≥0.8 auto-applies; destructive edits queue for one-tap review) → Mac `Features/Review/MacReviewView.swift`.
- **Durable memory blocks + audit log** — `core/user_memory.py` + `user_memory_blocks` (+ append-only `UserMemoryLogEntry` with before/after rollback), injected into the companion prompt every turn.
- **Agent surface** — FastMCP at `wai.computer/mcp`: `ask/search/fetch/remember/list_*`; OAuth + `wc_live_` PATs; `mcp:write` opt-in. Draft OpenClaw skill + **a real Hermes memory-provider** (`integrations/hermes/memory-provider/waicomputer/__init__.py`, prefetch + async write).

> ⚠️ **Moving target.** Since this session began, the concurrent loop shipped 8+ commits to `main` (including the wiki Brain and the dictation-dictionary merge). Build this on a `git worktree` off the **latest** `origin/main`, chain migrations off the real `alembic heads`, and re-confirm anchors.

---

## The genuine gaps (what's actually missing)

After subtracting what exists, the high-ROI, non-duplicative gaps are tight:

1. **No reranker** — RRF is the final ranking; no cross-encoder second stage (the biggest single precision lever).
2. **Chunk-grain results** — `unified_search` returns one row per *chunk*, so a long recording floods top-K and buries short notes (a *verified* failure; users see the same title repeated).
3. **Voice/segment chunks embed raw** — items already get a static `"title › "` prefix; segments don't (the real contextual-retrieval gap).
4. **Governance signals stored but unused in ranking** — `authority_score`, `salience_score`, `privacy_level` never touch recall; `salience_score` is hardcoded `0.5`.
5. **No fact-level time model** — conflicting facts ("I use Postgres" / "I migrated off Postgres") both persist and both surface; freshness is document-recency only.
6. **No "what I know about you" edit surface** — `GET /brain` is read-only; no view/edit/delete/pin/pause/export despite the full substrate existing.
7. **Agent connect is 4–6 manual steps with no verification** — no one-tap, no smoke-test; OpenClaw skill is a draft.
8. **No `GET /brain/feed`** — blocks the "Cards-That-Think" home; `recent_sources`/`top_entities` are hard-capped at 8.
9. **No proactive resurfacing / `wake_up()`** — the brain is "pull-only"; agents must remember to recall.

---

## The plan — 8 phases (power-per-effort)

**Conventions:** Backend-first; **Mac leads** each client-facing phase, then web (teal accent) and iOS — all on shared endpoints. TDD throughout. Migrations serialize into **one chain** off the confirmed head. Every retrieval change is gated on **P0·eval**. No fallbacks; cost bounded by keeping the zero-LLM path the floor for bulk synced items.

### P0·eval — measurement first *(added in critique; do this before P0a)*
A small golden set of ~40–60 real **Russian + English** questions, each tagged with the source(s) that should be retrieved, plus a tiny harness computing precision@k / recall@k / MRR. **Every** retrieval change (P0a max-pool, graph arm, contextual; P1 rerank; P4 ranking) reports against it. Without this, "better retrieval" is a vibe. Effort **S**. Success: one command prints before/after metrics for any flagged change.

### P0a — Invisible retrieval precision (no schema)
- **Per-page max-pool** (`m5`): `DISTINCT ON (source_kind, parent_id)` inner CTE → each source surfaces once on its strongest chunk → fixes the long-transcript-buries-short-note failure and the duplicate-title UX bug. *Ask keeps top-2/parent to preserve `_diverse_hits` intent.*
- **Graph arm** (`m1`): a 4th RRF CTE — resolve seed entities by folded-name match, walk one hop over `entity_relations`, join `entity_mentions`, fuse at `1/(k+rn)`. *Now viable: `record_relation` is wired, so relations exist; P2 deepens them.*
- **Contextual chunking** (`m3`, adapted): situate each chunk before embedding **and** FTS. *Honest scope: do "contextual-lite" first (one cheap Cerebras synopsis per source from the **stored summary**, not full-doc-per-chunk — Cerebras has no prompt-cache discount, so per-chunk full-doc is too costly). The genuine gap is the **segment/voice path** (items already have `title ›`). Optionally upgrade high-value sources to per-chunk later.* Align chunk size toward ~512 tokens / 10–20% overlap accounting for Cyrillic token density (`m16`).
- Behind `contextual_retrieval_enabled` (default **on for new content**); an **operator-gated, limit-bounded** backfill upgrades old content in deliberate batches (never on a beat — this is the Deepgram-runaway shape).
- **Files:** `unified_search.py`, `content.py`, `contextual_chunk.py` (new), `recording_audio_processing.py` + `recording_import.py` (segment embeds), `item_ingest.py`, `conversation_brain.py`, `mcp_brain_tools.py`, `tasks/contextual_backfill.py` (new), `config.py`. **Schema:** none (contextual prefix lives inside existing `*.content` columns). **Effort M.** **Success:** ≤1 hit per `(source_kind, parent_id)`; a graph-only neighbour appears; flags OFF reproduce byte-identical behaviour (regression test).

### P0b — "Cards-That-Think" home + <60s first-wow
- **`GET /brain/feed`** (cursor/region/q/limit) → cards with a two-line summary from **stored** summaries (**zero new LLM**), `is_new_since_last_seen`; RRF-ranked (reusing P0a) when querying, recency otherwise; drops the legacy `[:8]` cap.
- **`GET /brain/since-last-seen` + `POST /brain/seen`** (one `users.brain_last_seen_at` watermark) for the "Since you last looked · N new" strip.
- **Clients:** the `BRAIN_REDESIGN.md` winner — calm masonry of source/people cards under one **Ask·Remember** bar, cited **Answer Card above the feed** (skeleton, never a bare spinner; explicit 429/error row; citation chips to `source@start_ms`; one Gaps line; a trust line). Mac leads → web → iOS, demoting the cockpit (meters, always-open map) to on-demand.
- **Onboarding first-wow:** after voice enrollment, a pre-filled editable capture → auto-`ask` → inline cited Answer Card; skippable, non-blocking.
- **Files:** `api/routes/brain.py`, `brain_graph.py`, `models/user.py` + migration, `data_ownership.py`, `MacBrainView.swift`, `BrainPanel.tsx`, `OnboardingClient.tsx`, `BrainHomeView.swift`, `APIClient.swift`, `web/lib/api.ts`. **Schema:** `+users.brain_last_seen_at`. **Effort L.** **Success:** feed paginates >8 deduped cards; brand-new user hits capture→cited recall in <60s on real prod; opening Brain spends zero LLM tokens; same home on Mac/web/iOS + `/ru`.

### P0c — One-tap agent connect with smoke-test *(headline differentiator)*
- **`POST /api/mcp/connect/provision {client, mode}`** → mints a scoped `wc_live_` PAT (write iff readwrite), runs an **in-process smoke-test** (resolve token + 1-row search) and only then returns `{token?, mcp_url, smoke_test, config, deeplink?, install_command?}`. Session-auth only (a token can't mint a token). *Adapts gbrain's `connect --install` insight to a hosted SaaS — server-side, no CLI to ship.*
- **`GET /api/mcp/connect/clients`** catalog so every client grid renders from one source of truth.
- Pure-function builders: Cursor (`cursor://anysphere.cursor-deeplink/mcp/install?config=<base64>`), VS Code (`vscode:mcp/install?<json>`), OpenClaw one-liner (`openclaw mcp add … && openclaw mcp doctor`), Hermes `config.yaml` + `memory.provider` snippet.
- **`ToolAnnotations`** (`readOnlyHint`/`idempotentHint`/`openWorldHint`) on every MCP tool — the hard prerequisite for **Anthropic Connectors Directory / ChatGPT Apps** listing (`m56`/`m57`).
- Web `McpConnectSection` becomes a connect-card grid with a plain-language **"Read my brain" vs "Read my brain and let it save new memories"** toggle + a "Wai verified this connection" badge; PATs show in Connected-clients with one-tap revoke; `ApiKeysSection` demoted to Advanced.
- **Files:** `api/routes/mcp_connect.py` + `core/mcp_connect.py` (new), `api_keys.py`, `models/api_key.py` + migration, `mcp_server.py`, `McpConnectSection.tsx`, `ApiKeysSection.tsx`, `integrations/openclaw/.../SKILL.md`, `integrations/hermes/.../__init__.py`. **Schema:** `+api_keys.{client_label, origin, last_smoke_test_at}`. **Effort M.** **Success:** OpenClaw connects in 2 taps + 1 paste with a verified badge; a bad token fails at provision, never silently mid-chat; Cursor/VS Code open via real OS deeplink.

### P1 — Cross-encoder reranker *(biggest precision multiplier)*
- `reranker.py` calling a **managed** reranker via `httpx` (no GPU on the 3.8GB VPS) with qmd's position-aware blend (Top1-3 75/25, Top4-10 60/40, Top11+ 40/60). No fallback chain — flag ON + vendor error ⇒ raise (loud).
- `unified_search(rerank=False)` over-retrieves (~150 cap) **after** P0a max-pool → rerank → truncate; `brain_ask._search_hits` reranks **before** `_diverse_hits` (citation contract untouched).
- Flags: `reranker_enabled` (default **False**), API key (never logged), model, overfetch, max-candidates.
- **Gate:** flip in prod **only** after a real **Russian A/B** beats OFF on P0·eval (leaderboard numbers are English-slice; one paper shows cross-encoders can *hurt* some first stages).
- **Files:** `reranker.py` (new), `unified_search.py`, `brain_ask.py`, `mcp_brain_tools.py`, `config.py`, `observability.py`. **Schema:** none. **Effort M.** **Success:** rerank ON beats OFF on the RU set; faked in unit tests; key never in logs.

### P2 — Bi-temporal fact layer *(the one new abstraction)*
- **ONE canonical `entity_facts` table** (resolves the extraction-vs-temporal overlap): `subject_entity_id, predicate (snake_case), object_text, object_entity_id?, source provenance, confidence, importance, valid_at, invalid_at (NULL=current), superseded_by_id, content_hash`; `UNIQUE(user_id, subject, predicate, object)`; partial index `WHERE invalid_at IS NULL`.
- `entity_relations` gain `valid_at/invalid_at + fact_id` so an edge shares its fact's lifecycle.
- Summarizer: **fold facts into the existing single Cerebras `extract_entities` call** (add `_Fact` to the schema; resolve relative dates to ISO anchored on source date; `is_current=false` only on explicit end-signals) → **zero net new LLM calls for recordings**.
- `fact_pipeline.py`: deterministic **zero-LLM** reconcile (NOOP/ADD/SUPERSEDE/UPDATE). **SUPERSEDE closes a validity window, never deletes** (this is mem0's v3 lesson done *safely* — keeping the audit trail v3 lost). Ambiguous contradictions write the new fact current **and** emit a `MemoryProposal('fact_conflict')` for one-tap review.
- Gate to **high-value sources only** (recordings, `remember()`-notes, articles/PDFs/videos via a tunable `RICH_ITEM_SOURCES`); bulk `mcp:*` stays zero-LLM metadata path (the cost invariant).
- Entity wiki page gains a current "What I know" list + **`?as_of=<ISO>`** point-in-time view.
- **Files:** `models/entity.py` + migration, `summarizer.py`, `fact_pipeline.py` (new), `entity_graph.py`, `summary_generation.py`, `item_summary.py`, `brain.py`, `api/routes/entities.py`, `tasks/entity_extraction_backfill.py`. **Effort M.** **Success:** after "I migrated off Postgres" follows "I use Postgres," the old fact has `invalid_at + superseded_by_id` (both rows exist), the dossier stops asserting it, `as_of=<past>` returns the then-current fact, and bulk `mcp:*` items produce **zero** facts.

### P3 — Living wiki: O(changed) recompile + "what changed"
- `entities` gain `dossier_dirty + dossier_dirty_at`; `record_mention`/`record_relation` flip the touched entity dirty (zero LLM at write).
- `entity_page_synthesis` writes current facts into P2's `entity_facts`, closes superseded ones, clears the flag; snapshot JSONB tagged `status/valid_from/valid_to`.
- Bounded `recompile_dirty_dossiers(limit=25)` oldest-first (no thundering herd), hourly beat; per-entity isolation.
- `brain_graph` splits current vs superseded into a collapsed **"History — what changed"** fold; Mac/web/iOS render an "Updated" badge.
- **Files:** `models/entity.py` + migration, `entity_page_synthesis.py`, `entity_graph.py`, `tasks/recompile_entity_dossiers.py` (new), `celery_app.py`, `brain_graph.py`, `brain.py`, `api/routes/{entities,brain}.py`, `mcp_brain_tools.py`, `MacBrainView.swift`. **Effort M.** **Success:** a new mention recompiles its dossier within ≤1h with the old fact in a visible History fold; cost scales with entities *touched*, not graph size.

### P4 — Governance & lifecycle: trust-weighted ranking + reversible Forget
- **The keystone `unified_search` scoring rework** (merging importance `m26` + governance `m6` into ONE formula, not competing edits): `score = rrf · recency · trust · salience · usage · privacy`, **every multiplier clamped** (trust 0.5–1.5, salience 0.75–1.25, privacy 'secret' 0.6), applied **only within the matched pool** (never inject non-matches). *Drops gbrain's floor-ratio gate — verified to mis-fire on Wai's RRF score scale.* Hard-filter `state='archived'` from default recall.
- Parity columns so one formula spans all source kinds; `salience_score` filled deterministically from the structured summary (**zero new LLM**); `authority` from a `source_trust` prior (replaces hardcoded literals).
- `consolidate_user_memory` gains two bounded sweeps (archive low-authority+low-salience+90d-untouched; supersession folded into the **existing** nightly call).
- **`POST /items/{id}/forget`** (state=archived, **reversible**) + `/restore`; MCP `forget(id)` tool (symmetric with `remember`); "Forget" + provenance tags + "Pause memory" on the editable Memory surface.
- **Files:** `unified_search.py`, `governance.py` (new), `models/{recording,companion,item,entity}.py` + migration, `item_ingest.py`, `mcp_ingest.py`, `tasks/{item_summary_generation,consolidate_user_memory}.py`, `api/routes/{items,brain}.py`, `mcp_brain_tools.py`, `brain_graph.py`. **Effort M.** **Success:** a fresh relevant note still outranks a stale high-authority hit (clamp regression); "allergic to penicillin" outranks "had coffee Tuesday"; Forget removes from recall instantly with working undo; semantic contradiction → "keep newest?" Review card.

### P5 — Wake-up tier + richer agent tools + resurfacing
- **`wake_up()`** MCP tool (read-only): one cheap call returns `{profile (compiled blocks ~800 tok), taxonomy (folders + top entities), protocol}` — reads already-compiled `user_memory_blocks`, **no new LLM**; `_INSTRUCTIONS` names it as the first call (clear protocol, **not** "do-not-use-other-tools" poisoning language).
- `recent(limit)` + `related(entity)` + `ask(question, scope)` tools; **`create_safety` ('exists'|'novel') + provenance** surfaced on search/ask so a write-capable agent doesn't duplicate (`m50`/`m46`).
- Opt-in daily "On your plate" digest — a cron agent turn over `ask` (reuses the **existing** `Agent` cron + `dispatch_due_agents`), OFF by default, one tap to enable/stop.
- Hermes `prefetch()` calls `wake_up()` once per session; OpenClaw `SKILL.md` references both.
- **Files:** `mcp_server.py`, `mcp_brain_tools.py`, `user_memory.py`, `tasks/agents.py`, settings (digest opt-in), `integrations/{hermes,openclaw}/...`. **Schema:** `+users.memory_paused`. **Effort M.** **Success:** a fresh-connected agent calls `wake_up` and answers a profile question without guessing; `ask(scope='Acme')` narrows; an agent about to re-`remember` a known fact sees `create_safety='exists'`; Pause genuinely stops the consolidator + agent writes.

---

## How it beats the references

| Reference | Their strength | Wai's response |
|---|---|---|
| **gbrain** (Garry Tan/YC) | Dream-Cycle wiki; cited "think"; per-page max-pool; graph-as-retrieval; `connect --install` that mints + smoke-tests | Wai already has the Dream Cycle + cited Ask. P0a adopts max-pool + graph arm; P3 adds O(changed) recompile (refresh *between* cycles); P2 adds the bi-temporal axis gbrain lacks. P0c moves gbrain's connect+smoke-test insight **behind a tap** with a read/write toggle — server-side, because a hosted SaaS can't ship a CLI to non-technical users. |
| **karpathy-wiki / qmd** (Tobi Lütke) | Hand-curated, fully-cited personal wiki; RRF k=60 + position-aware rerank | P1 adopts qmd's exact k=60 + position blend with a managed cross-encoder, over **three** fused source kinds + a graph arm, on Russian-first content. P4's trust×salience ranking reaches "every claim is trusted" **automatically** (no hand-curation); P2/P3 keep it self-correcting where a static wiki carries stale claims forever. |
| **mem0** | Two-phase EXTRACT→UPDATE-DECISION; v3 turns rerank on; two-verb UX | Adversarial pass caught mem0 v3 **retired** UPDATE/DELETE → ADD-only (doesn't resolve write-time contradictions). P2 takes the two-phase decision but **supersede-not-delete** keeps the audit trail v3 lost; genuine conflicts → one-tap Review. P1 also contextualizes chunks *before* indexing (mem0 doesn't). Matches the two-verb simplicity (Ask·Remember) and beats the UI with a calm populated cited home + real edit/delete/pin/pause transparency. |
| **mempalace** | Bi-temporal KG + as-of; salience/decay tiers; layered wake-up | P2 matches bi-temporal supersede + as-of on **plain Postgres, no new graph DB**; P4 matches salience/decay but as a **reversible** ranking multiplier + auditable archive (nothing silently lost). Adversarial pass flagged mempalace's room/wing retrieval *regresses* recall and its "30× lossless" is lossy — so Wai adopts only the clean wake-up tier (`m38`/P5), backed by already-compiled blocks. |

---

## The experience

### Non-technical first run (target: first cited recall <60s)
1. Tap **Record**, speak ~10s, tap "Use this" (existing voice-enroll step).
2. One pre-filled, **editable**, skippable capture card: *"Remember: I prefer morning meetings and I'm allergic to penicillin."* Tap Save.
3. Wai instantly asks itself *"what do I prefer for meetings?"* → a cited **Answer Card** appears inline: *"You prefer morning meetings [1]"* with a tappable citation — the capture→recall loop proven before the dashboard.
4. Tap **Open your Brain** → the calm Cards-That-Think home: masonry of source/people cards under one *"Remember something, or ask your Brain…"* bar. No meters, no graph, no filing.
5. Ask anything → a wide Answer Card slots above the feed (skeleton, never a bare spinner), cited prose, citation chips to the exact source, one honest Gaps line, a trust line.
6. Capture without filing: type *"Remember: Pavel owns the legal review"* → "Saved to Inbox" toast with Undo. Never title/tag/organize.
7. **"What I know about you"** (overflow/Settings): three calm groups (About you / Topics / Preferences), plain-language lines with provenance; swipe-delete a wrong line, tap-edit, star-pin, or **Pause memory**. A "Memory updated" toast confirms every change.

### One-tap agent connect (honest about taps)
**OpenClaw / Hermes** lack OS deeplinks, so their flow is **one-tap-provision + one-paste** (their users are developer-ish, so a paste is fine); **Cursor / VS Code** get a true one-click deeplink.

- **OpenClaw:** Settings → MCP → OpenClaw card → pick *Read* or *Read + save* → **Connect OpenClaw**. Wai mints a scoped token, **verifies it server-side**, shows a green-checked prefilled one-liner (`openclaw mcp add … && openclaw mcp doctor`) with Copy. Paste → done (2 taps + 1 paste). Appears as "OpenClaw · read+write · last active" with one-tap revoke. First turn it calls `wake_up()` and recalls before answering.
- **Hermes:** same toggle → **Connect Hermes** → prefilled, token-embedded `~/.hermes/config.yaml` (mcp_servers + `memory.provider: waicomputer`) + verified badge. Paste → `/reload-mcp`. Hermes then auto-recalls **every turn** (`wake_up()` once per session, then `search` per turn).

---

## Decisions for Mik

1. **Reranker provider — managed vs self-hosted (a privacy call).** *Recommend: managed, flagged, RU-A/B-gated.* The 3.8GB VPS already OOMs building 3 images; `bge`/torch would never fit. A managed reranker is the only thing that fits "no heavy new infra," and queries already cross to OpenAI for embeddings. **Tradeoff:** Russian query+candidates go to a US vendor — for a privacy-positioned product this is a real call; a self-host path opens up if a GPU box is ever added. *(Verify the exact model id, Russian support, latency, and pricing before committing — one workflow agent named a specific lite model I couldn't fully confirm.)*
2. **Reconcile with the in-flight "Brain is a wiki" work.** The Brain shipped major changes today (1.0.36/207) and the loop is committing to `main`. *Recommend: build P0 on a worktree off latest `origin/main`, sync with the loop's owner before P0b touches `MacBrainView`.*
3. **Which phases to greenlight first.** *Recommend: P0·eval → P0a → P0c → P0b → P1* as the first shippable arc (precision + one-click agents + the new home + the big precision lever), then P2→P5.
4. **Supersession aggressiveness.** *Recommend: auto-close only on explicit signals (never delete); route ambiguous contradictions to the existing one-tap Review.*
5. **Onboarding first-wow style.** *Recommend: the pre-filled editable example (guarantees a real cited recall), run on whatever the user actually saves; ambiguous input defaults to Ask, explicit "Remember/Запомни" prefix writes.*

---

## Risks & invariants

- **Migrations are load-bearing.** Several tracks independently chained off the head and collided on timestamps. Serialize into one chain off the confirmed head; run `alembic heads` (expect exactly one) before **every** deploy. The tree is moving — re-confirm at build.
- **`unified_search` is touched by P0a, P1, P4** — these MUST be one coherent, clamped, evolving formula with a regression test asserting flags-OFF == today and a fresh-relevant hit still beats a stale high-authority one. A wrong blend silently degrades **every** recall surface at once.
- **Re-embedding/backfill is the Deepgram-runaway shape.** Every backfill is operator-gated, limit-bounded, never on a beat; only new content upgrades for ~$0. Never deploy with pending Celery jobs; build one VPS image at a time.
- **Russian reranking is vendor-claimed multilingual** — do not flip the flag without a real RU A/B; keep it off the live search-as-you-type box initially (use on submit / in Ask).
- **Memory-poisoning via the agent write path (EchoLeak-class).** `remember()` stays opt-in/off-by-default, authority 0.3, provenance='agent'; P5 surfaces `create_safety` + provenance so planted facts are visible/filterable; connect tokens are scoped, copy-once, instantly revocable; never logged.
- **Client regression surface is real** — P0b replaces the large `MacBrainView` + iOS cockpit. Phase behind the existing `.brain` section/tab, keep dossier/EntityPage code, gate on `swift test` + `xcodebuild` + `bun run dev:full` visual check on **real prod data + /ru** (green CI alone ≠ done).
- **Predicate sprawl** ("uses" vs "utilizes") fragments facts — mandate lowercase snake_case + a small normalization map for the top ~20 predicates; exact-triple is the floor; as-of/Review make duplicates visible; the consolidator merges synonyms later.
- **Localization** — every new client string via `t()`/`LanguageManager` (never `String(localized:)`), en/ru, clip-tested RU labels.
- **OpenClaw/Hermes have no OS deeplink** — "one-tap" is honestly one-tap-provision + one-paste; the true one-click is Cursor/VS Code; the ClawHub skill + Hermes catalog entry must actually be **published** (currently drafts).

---

## My adversarial pass

The automated critics + final revision hit the API rate limit, so I ran the four lenses myself against the real code. Changes I folded into the draft:

- **Added P0·eval** — the draft measured only P1 with an A/B; every retrieval change needs a golden RU+EN eval set or "better" is unmeasured.
- **Fixed the P0a graph-arm premise** — verified `record_relation` is now wired (`entity_graph.py:376`), so `entity_relations` is populated and the graph arm is viable (the draft's input had assumed it was empty).
- **Re-scoped contextual retrieval to "contextual-lite" + the voice path** — items already have `title ›`; Cerebras has no prompt-cache discount, so full-doc-per-chunk is too costly; the real gap is segments.
- **Flagged the reranker model-id/pricing/Russian as verify-before-commit** + surfaced the managed-vs-self-host **privacy** tradeoff as an explicit decision.
- **Flagged the moving tree** — concurrent commits to `main` (incl. "Brain is a wiki" today) mean anchors drift; build on a worktree off latest `main`, confirm `alembic heads`.
- **Noted platform scope** — backend endpoints are platform-agnostic and currently serve web, macOS, and iOS.
- **Confirmed the floor-ratio gate was correctly dropped** (a cosine heuristic that mis-fires on Wai's RRF scale) and **m71** (Brain *consuming* external MCPs) is intentionally deferred to the existing Brain×any-MCP sync initiative.

---

## Appendix — the 18 verified mechanisms

All came back *adopt* or *adapt* under adversarial review (none *skip*). Composite score in brackets.

| id | Mechanism | Verdict | Lands in |
|---|---|---|---|
| m52 | Tool-description nudging / **profile-on-recall** [8.48] | adapt (most already done; keep profile-on-recall) | P5 |
| m51 | Self-teaching MCP server / live taxonomy [8.38] | adapt (protocol exists; add taxonomy via `wake_up`) | P5 |
| m3 | Contextual retrieval (situate chunks) [8.32] | adapt (voice path; contextual-lite) | P0a |
| m28 | Sleep-time consolidation [8.10] | adapt (**already shipped**; extend watermark/model) | (exists) + P2/P3 host |
| m5 | Per-page max-pool [7.97] | adapt (collapse on source_kind+parent) | P0a |
| m54 | One-command connect + smoke-test [7.88] | adapt (server-side, no CLI) | P0c |
| m45 | "What I know about you" edit surface [7.83] | adapt (Settings → Memory) | P0b/P4 |
| m22 | Bi-temporal supersede + as-of [7.82] | adapt (new `entity_facts`) | P2 |
| m26 | recency×importance×relevance ranking [7.80] | adapt (discard fabricated paper) | P4 |
| m4 | Cross-encoder reranker [7.78] | adapt (managed, RU A/B) | P1 |
| m56 | "Add to Cursor/VS Code" deeplinks [7.77] | adapt | P0c |
| m65 | Proactive resurfacing (Heads Up / Ask Daily) [7.77] | adapt (Ask Daily reuses cron) | P0b/P5 |
| m21 | ADD/UPDATE/DELETE → v3 ADD-only [7.75] | adapt (supersede-not-delete) | P2 |
| m46 | Provenance + confirm-before-write [7.73] | adapt (provenance exists; surface it) | P4/P5 |
| m15 | Hybrid > pure graph (guardrail) [7.72] | adapt (keep RRF floor, no full GraphRAG) | (strategy) |
| m6 | Bounded metadata boosts + attribution [7.68] | adapt (drop floor-ratio) | P4 |
| m38 | Two-tier wake-up (identity vs lookup) [7.68] | adapt (`wake_up()`) | P5 |
| m53 | Auto-recall-every-turn provider [7.67] | adapt (**Hermes provider exists**; finish) | P0c/P5 |

*Full catalog (71 mechanisms), per-source mining, and verbatim verdicts are in the workflow transcripts under this session's `tasks/` (`wmk1dkepm`, `wrrq0rg1c`).*
