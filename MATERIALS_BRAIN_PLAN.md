# Materials + Brain upgrade — plan & progress

Branch: `feat/sb-materials-brain` (worktree `/Users/mikwiseman/Documents/Code/wai-mat-brain`, off `origin/main`).
Migrations chain off head **`20260601_130000_memory_proposals`**.
Full audit/research/roadmap JSON: `/private/tmp/claude-501/-Users-mikwiseman-Documents-Code-wai-computer/569b3edf-f67e-42f2-9351-0cddbfd2c083/tasks/wyzg3788q.output`

## Keystone insight
The Brain viz is not the real blocker — **the knowledge graph is data-empty in prod**: `extract_entities()` has zero callers, `EntityRelation` is built nowhere, `entity.embedding` is never written, and `EntityRelation` has no `item_id`. Any graph/wiki UI built before the graph is populated renders empty (current Mac failure mode). Order: **fix → fill → visualize**.

## Confirmed decisions (Mik, 2026-06-01)
- **Brain default view:** Index → ego/local graph. Tri-view: Index (default) / Wiki / Graph.
- **Graph nodes:** entities **+ items** as nodes (true Obsidian), with a toggle to hide item nodes.
- **Surface order:** web **and** Mac **in parallel**.
- **Video by link:** direct-media-URL (.mp4/Vimeo/Loom) → Deepgram now; YouTube captions now; **yt-dlp deferred** (opt-in + daily cap, Phase 5).
- Uploaded video/audio → **Recording** pipeline (reuse diarization/status/trash); items get a pointer later if needed.
- Storage: **local-disk behind a swappable interface**; hold 200MB cap with an honest "share a link" refusal.
- Entity merge: exact normalized-name upsert only; fuzzy/cosine → human-confirm Review queue (never silent-merge).
- Web graph lib: `react-force-graph-2d` (≤2k nodes; sigma.js+graphology upgrade path documented). Mac graph: SwiftUI Canvas + capped Verlet.
- OCR (scanned PDF) + browser/Share extension: **deferred** (separate builds).

## Phases (ordered by leverage)

### Phase 0 — Quick wins + no-fallbacks compliance
- [x] Backend: derived `status` (fetching|summarizing|ready|needs_input|failed) + `error{code,message}` in `ItemResponse`/`ItemListEntry`. (commit 01ccea77)
- [x] Backend: kill silent enqueue swallow in `items.py` (state=failed + processing_error on broker fail). (01ccea77)
- [x] Backend: kill silent enqueue swallow in `comparisons.py` (mark set failed, drop dead intent block). (01ccea77)
- [x] Backend: race-safe idempotency in `ingest_item` (SAVEPOINT + IntegrityError → re-SELECT). (01ccea77)
- [x] Backend: GIN FTS index on `item_chunks.content` (migration 20260601_140000, validated on scratch DB). (01ccea77)
- [x] Web: onCreated add→feed fix (reloadKey signal replaces loadRecordingsState); status-driven badges + error tooltips; poll-while-pending + focus refresh; real API error in AddAnything/ItemDetail; `status`/`error` TS types.
- [~] Web+Mac taxonomy + `pdf` chip: WEB + Mac `pdf` chips done; WaiComputerKit single-source taxonomy (labels+icons) still pending (Phase 1).
- [x] Mac: errorMessage inline banner in Content feed; `MacBrainView try? getBrain()` → do/catch + error/Retry (distinct from empty); `addDraft()` background poll; pdf chip. (xcodebuild ✓)

### Phase 1 — File ingestion: the missing entrance
> SEQUENCING (2026-06-01): document upload (1a/b/c) is DONE across backend+web+Mac = the core of goal #1. The remaining Phase 1 items (media-upload async, `classify_url` media, video allow-list, needs_input reprocess UI, SSRF guard) are DEFERRED to a pre-launch hardening pass — SSRF isn't urgent pre-v1 (no other users). **Pivoting to Phase 2 (graph keystone) next** to unblock the flagship Brain viz.
- [~] Backend: `POST /items/upload` — DOCUMENTS done (PDF/txt/md → extract text → Item; 200MB cap; UUID storage key; dedup-unlink; shared `_enqueue_item_summary`). PENDING: audio/video → Recording (needs async enqueue — `import_media_as_recording` transcribes inline, too slow for an HTTP request); SSRF guard is a separate fetch-path slice.
  - IMPL NOTE: build a NEW `/items/upload` route — do NOT overload `/recordings/{id}/upload` (recordings.py:2853), it's intricate (claim-race `_claim_audio_upload`, size-mismatch, `_mark_recording_failed`). Reuse `_stage_upload_to_disk` (recordings.py:987) + `MAX_UPLOAD_SIZE` (2850) + `_measure_upload_size` (860). PDF→`source_fetch._extract_pdf_text` (or pdfplumber) → `ingest_item`; audio/video → `recording_import.import_media_as_recording` (recording_import.py:456, handles video via `_normalize_media_for_transcription`→Deepgram). Storage key `{user_id}/{uuid}.{ext}` — never trust `UploadFile.filename`.
- [ ] Backend: widen `recordings.py` `ALLOWED_AUDIO_EXTENSIONS` to include `SUPPORTED_VIDEO_EXTENSIONS` (only if keeping the recordings endpoint as a video path; otherwise `/items/upload` → import_media_as_recording covers it).
- [ ] Backend: `classify_url` for direct media (.mp4/Vimeo/Loom) + reroute audio/* video/* content-type to transcription.
- [ ] Backend: `needs_input` reprocess endpoint (append body / attach file + re-enqueue).
- [~] Web: AddAnythingPanel drag-drop + Attach-file → `uploadItem` (native HTML5, no new dep) — DONE. PENDING: paste-detect type chip before submit, multi-file queue, per-file progress bar.
- [x] Mac: `.dropDestination` + `.fileImporter` (PDF/text/markdown) in Content feed; `APIClient.uploadItem(fileURL:folderId:title:)` streaming multipart-from-temp-file; VM `uploadFile` + background poll. (swift test 473 ✓, xcodebuild ✓)
- [ ] Web+Mac: render `needs_input` recovery (why + Paste/Attach/Retry).

### Phase 2 — Populate the knowledge graph (keystone)
- [x] Backend: recording-pipeline entity seeding — `apply_summary_result` (live/regenerate) + `_persist_summary` (import) seed people/topics → entities + mentions (cheap, zero extra LLM), mirroring items. DEFERRED enrichment (gated/nightly, not inline): the richer `extract_entities` LLM pass for typed relations (works_on/reports_to) + `entity.embedding` for similarity edges.
- [x] Backend: item-pipeline entity seeding — `generate_item_summary` promotes people_mentioned/topics → entities + mentions (cheap, zero extra LLM) via `app/core/entity_graph.py` (`upsert_entity` exact-dedup + IntegrityError race-safe, `record_mention`, `seed_entities_from_summary`).
- [x] Backend: polymorphic `EntityMention(user_id, entity_id, source_kind, source_id, chunk_id?, context, weight)` table + `entities(user_id,type,name)` unique constraint — migration 20260602_100000 (validated on scratch DB).
- [~] Backend: feed Items into nightly consolidator (`_gather_user_material`) — DEFERRED enrichment (not blocking Phase 3; makes items compound into durable memory blocks).

### Phase 3 — Brain visualization on web (flagship)
- [x] Backend: `GET /api/brain/graph` — entities + item/recording source nodes; mention + co-occurrence edges; `?focus=` ego graph; `limit` degree cap; honest empty graph. `core/brain_graph.py` + 5 tests. (similarity edges deferred — need `entity.embedding` from the gated LLM pass.)
- [ ] Backend: enrich wiki — `GET /api/entities/{id}/page` (backlinks + co-occurrence + sources).
- [~] Web: Brain section — nav (Library → Brain) + **Index** view + **Graph** view + Index/Graph tab switcher DONE. Graph = `react-force-graph-2d@1.29.1` (dynamic `ssr:false`, color-by-kind, size-by-degree, `nodeLabel` tooltip, click entity→backend ego-focus + Reset, show-sources toggle, explicit canvas height, no-fallback error/retry). `getBrainGraph` client + `BrainGraph` types + `BrainPanel` + `BrainGraphView` (pure `buildForceGraph` helper, unit-tested). PENDING: Wiki tab (needs `GET /api/entities/{id}/page`) + the authenticated browser verification (login → populate entities → check `/ru`).

### Phase 4 — Brain on Mac + comparison hardening + power features
- [ ] Mac: tabbed Graph|Wiki|Index in MacBrainView (wiki backlinks tappable; Canvas Verlet graph; BrainGraph kit models).
- [ ] Backend: comparison correctness (intent column, distinct items, deleted filter, retry, rebuild, parallel rows, export, cell edit).
- [ ] Web: switch search to unified `/api/search/all`; comparison builder; connect-a-source UI.

### Phase 5 — Robustness + governance
- [ ] Tiered video-by-link / yt-dlp (opt-in + daily cap); media classify_url; simhash fuzzy dedup; governance for items+entities; Person↔Entity reconcile; Brain-health lint; optional OCR (docling, MIT only).

## Progress log
- 2026-06-01: worktree + analysis workflow (21 agents) done; decisions locked; starting Phase 0 backend.
- 2026-06-01: Phase 0 COMPLETE across surfaces — backend (01ccea77), web (fa061364), Mac (58bda2f7, xcodebuild ✓).
- 2026-06-01: Phase 1a — `POST /items/upload` for documents (PDF/txt/md → Item). 19 items-route tests green; full backend suite 95.11% (gate ✓). Heads-up: main is red on 2 `test_observability.py` tests (`OPS_FORWARD_GENERIC_ERRORS` default-off, commit c0661d4b — owned by the sentry-telegram-bridge loop, NOT this work). Next: media upload (audio/video→Recording, async), `classify_url` media + SSRF guard, then web drag-drop + Mac .fileImporter.
- 2026-06-01: Phase 1b — web AddAnythingPanel drag-drop + Attach-file → `uploadItem` (native HTML5, no dep). 8 AddAnything tests green; eslint + tsc clean. Next: Mac `.fileImporter` + `APIClient.uploadItem`, then media-upload async routing.
- 2026-06-01: Phase 1c — Mac upload (kit `APIClient.uploadItem` + `.fileImporter`/drop in Content feed + VM `uploadFile`). swift test 473 ✓; xcodebuild ✓. **Document upload (PDF/txt/md) now works web AND Mac, end-to-end.** MEDIA-UPLOAD design recon: reuse `import_media_as_recording` (creates the Recording, normalizes video, transcribes) from a NEW Celery task that reads staged bytes — recordings' own `process_staged_recording_upload` is audio-only (no video normalize).
- 2026-06-02: Phase 2a — knowledge-graph FOUNDATION. `EntityMention` polymorphic table + `entities` dedup constraint (migration 20260602_100000, scratch-DB validated); `app/core/entity_graph.py` (upsert/mention/seed, exact-dedup + race-safe); item-pipeline seeding so **items now create person/topic entities + mentions at zero extra LLM cost** — the graph finally gets data. +3 entity-graph tests, item_summary test extended; full suite 95.10% (gate ✓). 2 pre-existing observability failures still unrelated. Next: wire recording-pipeline `extract_entities` (LLM pass — sets `entity.embedding` + EntityRelation edges) + feed items to the consolidator, then Phase 3 (`GET /api/brain/graph` + web Brain viz).
- 2026-06-02: Phase 2b — recording-pipeline entity seeding (cheap path) wired into `apply_summary_result` + `_persist_summary`, mirroring items. **Graph now has data from BOTH recordings and items** (people/topics → entities + mentions), zero extra LLM cost. test_summary_generation_core extended; full suite 95.10% (gate ✓). Phase 2 graph-DATA done (LLM extract_entities pass + consolidator items DEFERRED as gated enrichment). **Pivoting to Phase 3 — the flagship: `GET /api/brain/graph` (nodes+edges: mention + co-occurrence + similarity) then the web Brain tri-view (Index/Wiki/Graph, react-force-graph-2d, ego default, items toggle).**
- 2026-06-02: Phase 3a — `GET /api/brain/graph` backend (`core/brain_graph.py`): entities + item/recording source nodes, co-occurrence (entity↔entity shared-source) + mention (source→entity) edges, `?focus=` ego graph, `limit` degree cap, honest empty graph. 5 tests; full suite 95.12% (gate ✓). Next: Phase 3b — the **web Brain section** (nav + route + tri-view Index/Wiki/Graph; Graph via `react-force-graph-2d` dynamic-import ssr:false, ego default, items toggle, no-fallback error/retry). Then verify in a real browser + surface to Mik.
- 2026-06-02: Phase 3b-1 — web Brain section scaffolding: **Brain** nav entry (Library group) + route + `BrainPanel` Index view (people/topics/projects chips from `GET /api/brain/graph`, sorted by degree, stats row, honest empty + error/retry), `getBrainGraph` client + `BrainGraph` types + CSS. 3 BrainPanel tests green; eslint + tsc clean (the 3 failing DashboardClient tests in the combined run are the pre-existing recording-delete timing ones). Next: Phase 3b-2 — the **Graph tab** (`react-force-graph-2d`, verify latest version first; dynamic ssr:false; color-by-kind, size-by-degree, hover-highlight-neighbors, click→ego focus; no-fallback error/retry), then the authenticated browser pass + surface to Mik.
