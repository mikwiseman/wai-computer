# Brain Redesign — from cockpit to calm

**Goal:** make the Brain section *simple but super-powerful*. Today it reads like a spaceship cockpit; underneath it is a genuinely powerful, cited, anti-fabrication memory engine. The redesign's whole job is to **show the answer, not the plumbing.**

Produced by a multi-agent analysis workflow (4 UI/backend teardowns → 5 reference studies → a design brief → **8 independent design directions, each scored on a weighted rubric and adversarially code-checked** → ranked synthesis). 2026-06-09.

---

## TL;DR

- **Winner: "Cards That Think"** (8.40 / 10). A calm two-column card grid (your Recent sources + People & projects) under one **Ask / Remember** bar. When you ask, a **cited Answer Card slots in *above* the feed** — an answer never replaces your brain, it *sits on top of it*. Everything else (dossiers, maps, the graph, compare, spaces, export) is one tap behind a result.
- **Runner-up: "Front Door"** (8.30) — the purest one-screen Ask. Loses only because an empty box becomes a blank wall on day one and on every thin topic; a populated card grid is a strictly better resting state.
- **"Should we focus on dynamic diagrams?" → No.** Verdict: **supporting, never the hero** — and a trap as a default *on this codebase* (the graph is data-empty for voice-first users; the map diff never auto-fires). The bounded, cited Living Map survives as an on-demand **"Map this"** lens. The Living-Map-as-hero direction scored **last (6.65)**.
- **One honest engineering caveat:** every direction claimed "100% backend reuse" and **every one is false** in a specific, code-verified way. The winner's only real gap is bounded: it needs a small net-new `GET /brain/feed` endpoint (today `recent_sources`/`top_entities` are hard-capped at `[:8]` with no card summary). That's **P0**, before any SwiftUI.

---

## The diagnosis — why it feels like a cockpit

The UI exposes meta-information *about* the brain (pipeline state, index coverage, diff cardinality, source-type breakdowns) at the **same visual level** as the brain itself (entities, maps, answers). Every internal state variable that *could* be surfaced *was*.

| Surface | Visible elements | "Noise" | Headline sins |
|---|---:|---:|---|
| **Web** (`BrainPanel.tsx`, 2202 ln) | **70** | **29** | Freshness stated **4×**; a "Coverage ledger" (4 tiles); 3 source-coverage meters; a 5-metric "Live status" dashboard (incl. AI advice rendered as a *data tile*); duplicated suggestion chips; DB join-counts as row subtitles |
| **Mac** (`MacBrainView.swift`, 2745 ln) | **52** | **19** | 12 micro-data-points before you scroll a pixel; status-inside-status; **two** coverage blocks = 6 stacked coverage tiles per map |
| **iOS** (`SecondBrainView.swift`) | **60** | **3** | Already lean — its real sin is *dark capability*: multi-item Compare & kind-filter are fully coded but **no button wires them** |
| **Backend** (`brain_*.py`, 4565 ln) | **22 caps** | **3** | The power is real and under-exposed, not missing |

**The 5 real differentiators (must survive any redesign):**
1. **Ask-your-Brain** — one synthesized answer, every claim cited to the exact source, out-of-range citations *dropped*, an honest **gaps** list, and a **freshness** read. Answers only from your own sources.
2. **Unified RRF hybrid search** (pgvector + Postgres FTS, Russian + ICU folding) across recordings + materials + chats.
3. **Compiled-truth living dossiers** — per-entity overview + cited facts + cited timeline + open questions, citation-validated, never fabricated.
4. **Living Maps with diffs** — a saved lens compiles to a cited projection; each refresh stores an immutable revision and diffs vs prior. The only artifact that answers "what changed since I last looked."
5. **Brain as an MCP memory server** — `ask / search / fetch / remember` over one link; the same brain for the app and for external agents.

---

## What the references taught (and the dynamic-diagram verdict)

Mik flagged **gbrain, mem0, mempalace, and integrity.sh**, and floated "maybe focus on dynamic diagrams." The evidence is unanimous and decisive — **against** making a diagram the hero:

- **mem0** (58k★, YC) **deleted its memory-graph view in v3 (2026)**, removed the whole Neo4j dependency, and replaced it with *invisible* entity-linking (a retrieval ranking boost) + a plain **searchable list of memory sentences**. Called it a net simplicity win. Two verbs: `add` / `search`.
- **gbrain** (Garry Tan's, 146k pages in production) ships **no visual graph at all** — the graph is a *retrieval substrate* (+31.4 P@5), surfaced as evidence *inside answers*. "Search gives raw pages; the brain gives the answer + an honest gap note" — which validates Wai's `ask` as best-in-class.
- **mempalace** (47k★) uses spatial **named regions** (Wings→Rooms) but has **no walkable space** — it's a metadata schema + an ASCII sketch. Spatial = *legibility*, not retrieval. Its transferable mechanic: **scope-before-search** (folder/region) and **filing receipts** ("filed → Project X / decisions").
- **integrity.sh** — the "#organisation" visual Mik linked is a **hand-authored Lottie animation of a tree** (661 SVG paths, **zero** graph/node/diagram primitives in the DOM). *Not a dynamic diagram.* Its real, copyable idea: **"two views of the same objects"** (a tree whose nodes deep-link bidirectionally to a richer surface) + **sidebar transparency**.
- **2026 literature** — the full-vault force-graph ("hairball") is a *documented failure*: fine under ~50 notes, degrades past ~200, useless past ~500; a Tufts/IEEE study found end users **trust the analysis *less*** when shown as a node-link graph. The 2026 frontier is **query-driven, focus+context, one-concept-at-a-time (≤7–12 nodes), edges-on-demand**, rendered from a structured source-of-truth.

**Why a diagram-hero is a trap *specifically on this codebase* (verified in code):**
1. **The graph is data-empty for the lead surface.** `extract_entities` runs only over Wai chats (`conversation_brain.py:199`) and zero-LLM MCP records — **there is no recording→entity pipeline.** So for the canonical voice-first user ("40 sources, +4 voice memos…"), the memos contribute **0 nodes**; a hero map renders as ~3 disconnected source chips.
2. **The map diff never auto-fires and is cardinality-only.** `refresh_brain_map` is called only by the user-tapped `/refresh` route and the agent — *nothing in ingestion re-diffs a map.* And the diff is `{nodes_added, sources_added, changed}` — it can't name "Pavel" or say "+1 risk" without a (banned) LLM diff.

**Verdict:** keep the bounded, cited Living Map (it already caps at 3 source + 8 entity nodes, ≤12 edges, every node carries `citation_ids`, every revision diffs immutably) as an **on-demand "Map this" lens** invoked *from* an answer or entity, rendered small with cited prose beside it, leading with "what changed since you last looked." Demote the force graph to a hidden **⋯ → Explore** lens. **Focus on the cited Answer; let the lensed map be the reward** for "show me how X connects."

---

## The scorecard — 8 directions, independently scored & code-checked

Weighted rubric: **simplicity .25 · power .20 · solves-the-job .20 · feasibility .15 · delight .10 · mac-fit .10**. Each direction was designed by an independent agent, scored by another, and adversarially critiqued by a third that traced the real backend.

| # | Direction | Simp | Pow | Job | Feas | Del | Mac | **Total** | Verdict |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| 1 | **Cards That Think** | 9 | 8 | 9 | 9 | 7 | 7 | **8.40** | **WINNER** — calm populated home; answer-on-top-of-feed is the best single idea in the set |
| 2 | Front Door (Answer-First) | 9 | 8 | 9 | 9 | 6 | 7 | 8.30 | Strong #2; empty box = blank wall on thin topics |
| 3 | Memory Palace (regions) | 8 | 8 | 9 | 9 | 7 | 7 | 8.15 | "Located recall" is a real insight — but scope-before-search isn't wired (post-filter only) |
| 4 | Two-Verb Console (mem0) | 9 | 7 | 8 | 9 | 7 | 6 | 7.90 | Beautiful compression; but `remember` files to `NULL` → the receipt is a lie today; drops orientation |
| 5 | Notebook Canvas | 7 | 9 | 8 | 7 | 8 | 8 | 7.80 | Canvas engine is dead weight gated behind an interaction ~95% never trigger |
| 6 | Timeline River | 7 | 8 | 6 | 9 | 8 | 6 | 7.30 | Map-deltas never auto-fire → degrades to "a second Inbox with an Ask box stapled on" |
| 7 | Living Map Hero (diagram) | 5 | 9 | 5 | 8 | 8 | 6 | **6.65** | **TRAP, correctly last** — empty graph for voice-first users; against the founder's own hypothesis |
| — | Cockpit-Lite (hide meters) | — | — | — | — | — | — | — | Dropped (critic agent failed); the first pass judged it a half-measure that keeps a dashboard IA |

> The adversarial pass earned its keep: it found that **every** direction's "no backend changes" claim was false in a *specific, verified* way. That converts hand-wavy "reuse" into a concrete, honest P0.

---

## The winner — "Cards That Think"

**One screen. One bar. A calm grid. The answer sits on top of your brain.**

It delivers both halves of the mandate without trading one for the other:
- **Simple:** one Ask/Remember bar over a two-column card grid; the entire cockpit (3 meters, live-status dashboard, coverage ledger, stat strips, ambient chips) is *deleted*; all depth strictly behind a tap.
- **Powerful:** nothing is *removed*, only *relocated* — cited Answer with citation→exact-source nav, full dossiers, Living Maps, RRF region scope, governance — all reachable.
- **Signature move:** when you Ask, the **Answer Card materializes *above* the masonry and pushes the cards down**, so the living feed stays visible underneath. *An answer never replaces your brain.* This directly serves the core job — *recall without loss*.

Versus Front Door (the only serious rival, 8.30): identical verified backend, identical calm — but Front Door's resting state is an **empty box** (a blank wall on day one / sparse topics), while the winner's resting state is a **self-explaining grid of trusted, sourced cards**. A calm *populated* home beats a calm *void* for a memory product whose whole promise is "you have things, and I can show you them."

### Recommended Brain — information architecture

**HOME (the only resting screen):**
- **Header:** 🧠 Brain · a *single* freshness chip ("Newest source · 2 days") · "Needs review · N" pill (only when N>0) · a quiet **⋯** overflow (Explore-graph / Compare / Spaces / Export).
- **One full-width bar:** "Remember something, or ask your Brain…" — live Ask·Remember mode-flip; **defaults to Ask** on ambiguous input; explicit "Remember"/"Запомни" prefix to write. `⌘K`/`⌘F` focuses it.
- **Region chips** (from top entities + recording folders): a chip scopes *both* the feed and the next Ask. A folder-backed chip shows a tiny "recordings" qualifier (honest about recordings-only scope).
- **Optional one-liners:** "Since you last looked · N new" (NEW-SOURCE events only) · "N catching up · Link now" (only when there's a backlog).
- **Feed:** a two-column masonry, two card archetypes under faint *Recent* / *People & projects* dividers:
  - **Source cards** (recording/note/chat): title · kind glyph · one body line · faint filing line.
  - **People/Project cards**: name · type · "12 sources · last touched Tue" → the dossier on tap.

**ASK RESULT (on top of home, never a new screen):**
- A wide **Answer Card** slots in above the masonry: cited prose · citation chips (open the exact source at `start_ms`) · one **Gaps** line · a **per-answer trust line** ("Answered from 6 sources · newest 2 wks · 1 catching up") · freshness chip · a recovery row (Browse newest · Exact text · Scope) · a **"Map this ›"** affordance. Skeleton state while the (multi-second, blocking) Ask runs — the hero pixel is never a bare spinner. `Esc` dismisses back to the feed.

**DEPTH (all one tap, never upfront):** Source card → raw source · People/Project card → full cited dossier (with a "compiling…" state when the snapshot is skeleton/stale) · "Map this" → small bounded Living Map (≤~15 nodes, cited, leads with the revision diff) · ⋯ → Explore / Compare / Spaces / Export. Governance is surfaced (header pill), not buried. Every surface bilingual EN/RU via `LanguageManager`/`t()`.

```
┌────────────────────────────────────────────────────────────────┐
│  🧠 Brain          ◷ Newest source · 2 days     ⚑ Needs review·2 ⋯│
│ ┌────────────────────────────────────────────────────────────┐ │
│ │  Remember something, or ask your Brain…              Ask ▾  │ │
│ └────────────────────────────────────────────────────────────┘ │
│  Ask · Remember        ⌘K to focus · ↩ to ask                  │
│  ◉ All  ▢ Project Atlas  ▢ Hiring  ▢ Maria K  ▢ Q3 (recs)   ••• │
│  ◷ Since you last looked · 4 new                          ▸     │
├────────────────────────────────────────────────────────────────┤
│  Recent                                                         │
│ ┌──────────────────────────┐ ┌──────────────────────────────┐  │
│ │▎〰 Atlas pricing sync     │ │▎💬 Standup w/ Dmitri          │  │
│ │  Agreed tiered pricing,   │ │  Blocked on legal review;     │  │
│ │  revisit after May call.  │ │  Maria to unblock Thu.        │  │
│ │  Project Atlas → decisions│ │  Project Atlas → chats        │  │
│ └──────────────────────────┘ └──────────────────────────────┘  │
│  People & projects                                              │
│ ┌──────────────────────────┐ ┌──────────────────────────────┐  │
│ │▌👤 Maria K        Person  │ │▌▣ Project Atlas      Project   │  │
│ │  12 sources · touched Tue │ │  18 sources · touched Wed      │  │
│ └──────────────────────────┘ └──────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘

   ── you Ask → a wide Answer Card slots in ABOVE the feed ──
┌────────────────────────────────────────────────────────────────┐
│ Q: what did we decide about Atlas pricing?                  ✕   │
│ You agreed on tiered pricing [1] and chose to revisit the final │
│ number after the May call with Maria [2]. Legal review is still │
│ blocking the contract [3].                                      │
│ [1 〰 Atlas sync 4:12] [2 💬 Standup] [3 ▭ Q3 note]              │
│ Gaps · No final price captured after the May call.              │
│ Answered from 6 sources · ◷ newest 2 wks   ·  1 catching up     │
│ Map this ›        Browse newest · Exact text · Scope ›          │
└────────────────────────────────────────────────────────────────┘
(The feed stays visible underneath; Esc dismisses the card back to it.)
```

### Removed from the cockpit
3 source-coverage meters · the whole `brainCoverageSection` · `generatedLiveStatus` + "watch next" advice-as-tile · `mapCoverageLedger` + every `coverageTile` · `mapStats` "N cards · M links" · `briefingFocusNote` cardinality headings · the `llmRequests` counter · inline schema breakdowns on rows · duplicate freshness (stated once) · the standing 3 suggested-question chips · transient "synced now / catching up" badges · the header subtitle paragraph · the generated-map-as-default surface · the force graph as any default.

### Kept power (relocated, not removed)
Ask-with-citations+gaps+freshness → the hero Answer Card · freshness → one header chip · RRF search → region-scoped Ask + recovery rail · dossiers → People/Project cards (+ "compiling…" state) · Living Maps → on-demand "Map this" · spaces/folders → region chips · governance → one "Needs review · N" pill · remember/capture → the left verb + honest receipt + Undo · the MCP loop → untouched · citation→source nav → every chip one tap from its proof.

### Best ideas grafted from the runners-up
- **Per-answer trust line** (from Front Door's critic — the single best graft): "Answered from 6 sources · newest 2 weeks" restores the *why-might-this-be-thin* signal the coverage meters used to give, without the cockpit.
- **Named region chips** (Memory Palace), shipped *honestly* (folders scope recordings only — say so).
- **Filing receipt + Undo** (Two-Verb / mempalace), shipped *honestly* as "Saved to Inbox — tap to file" until write-time entity/folder resolution exists.
- **Two-verb bar + instant Undo** (Two-Verb) — but keep the People/projects index it wrongly deleted; default ambiguous input to Ask.
- **"Since you last looked" strip** (Timeline River) — fed *only* by NEW-SOURCE events, never the uncomputable map-delta/"sentence that changed" cards.
- **On-demand "Map this"** (Living Map Hero's one durable idea) — the supporting-role realization of the diagram verdict.
- **A real Mac keyboard model** (Notebook Canvas / Front Door critics) — `⌘K`/`⌘F`/`↩`/`⌥-N`/`Esc`/arrows; table stakes on the priority native surface.

---

## Phased plan (Mac-first)

- **P0 — Net-new backend first (kills the winner's one lie before any SwiftUI):** build `GET /brain/feed?cursor=&region=&q=` returning cards **with a 2-line summary**, >8 via cursor, ranked by RRF when q/region active and by recency otherwise. *Verified necessity:* `BrainOverview.recent_sources`/`top_entities` are hard-capped at `[:8]` (`brain_graph.py:529-530`) and `BrainOverviewSource` has no summary field. Add a per-user `brain_last_seen_at` watermark (for "Since you last looked"). No change to `/brain/ask`, maps, entities, or the MCP loop.
- **P1 — Mac home (lead client):** new `MacBrainHomeView` replacing the 2748-line `MacBrainView`; the two-verb bar, masonry feed off `/brain/feed`, region chips, the Answer Card pinned above the feed (with skeleton/loading + explicit 429/error state — Ask is blocking, ~p95 5s), citation→source, the per-answer trust line, the single freshness chip, the "Needs review · N" pill, the keyboard model. Delete every cockpit symbol. Gate: `swift test` + `xcodebuild` green, then `bun run dev:full` visual confirmation on real prod data.
- **P2 — Mac depth + honest receipt + maps-as-lens:** dossier on tap (+ "compiling…" state) · "Map this" → bounded Living Map beside prose · ⋯ → Explore / Compare / Spaces / Export · the honest "Saved to Inbox — tap to file" receipt (never a fabricated destination).
- **P3 — Net-new honesty upgrades (optional, scoped):** (a) push a `folder_ids`/scope filter *inside* `unified_search`'s SQL so region-scoped Ask actually retrieves region-relevant evidence (today it post-filters a global ~54-chunk pool); (b) write-time entity/folder resolution so the receipt can truthfully read "Saved → Acme"; (c) wire `extract_entities` into recording summarization so People/Project cards and maps stop being chat-only.
- **P4 — Web (teal accent) then iOS parity** on the same endpoints. The masonry+answer-card model ports cleanly (unlike a canvas direction). Gate: authenticated browser verification on wai.computer (logged in, long folder names, `/ru`).

---

## Risks & mitigations (highest first)

1. **"100% reuse" is false** — the feed needs pagination + per-card summaries + relevance order the overview can't give. → **P0 builds `/brain/feed` before any SwiftUI; treat "no schema changes" as the claim to disprove, not trust.**
2. **"Self-organizing feed" is actually "newest 8"** (`recent_sources` is reverse-chron; RRF runs only inside ask/search). → P0 feed ranks by RRF when q/region active, recency otherwise, with a cursor.
3. **Empty/new-user home** (`top_entities` filters `source_count==0`) → first-run shows 2–3 "capture your first thing" cards + one example answer; never a bare void.
4. **Ask is a multi-second blocking Cerebras call** (no streaming; p95 ~5s, occasional 429) → skeleton/partial loading + explicit error state with the recovery row; never a bare spinner.
5. **RU intent misfire** ("Atlas — решили по цене") — a wrong Remember pollutes retrieval → default ambiguous input to Ask; require an explicit Remember prefix; on a read-only MCP connection show "enable write access," not a raw error.
6. **Region chips scope recordings only** (folders don't cover notes/chats) → chip shows a "recordings" qualifier; P3 pushes scope into `unified_search`.
7. **Near-empty dossier vs not-yet-compiled** — calm-by-subtraction would hide the difference → show a "compiling…" state (the one place we deliberately re-add a tiny status signal, because hiding it breaks trust).
8. **One global freshness chip can read green while the relevant sources are stale** → the grafted per-answer trust line makes staleness answer-specific where it bites.
9. **Discoverability of ⋯ power** → items are *labeled*; Compare/Map also surface contextually.
10. **Replacing 2748 tested lines is real regression surface; RU labels can clip** → phase behind the existing `.brain` SidebarSection; every string through `t()`/`LanguageManager` (never `String(localized:)`); final stage is `dev:full` visual confirmation, not green CI alone.
