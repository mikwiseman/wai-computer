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
- [ ] Backend: expose derived `status` enum (queued|fetching|transcribing|summarizing|ready|needs_input|failed) + `fetch_error{code,message}` in `ItemResponse`/`ItemListEntry` (additive, no migration).
- [ ] Backend: kill silent enqueue swallow in `items.py` (set state=failed + fetch_error on broker fail).
- [ ] Backend: kill silent enqueue swallow in `comparisons.py:~105` (mark row failed / 503, never permanently "generating").
- [ ] Backend: race-safe idempotency in `ingest_item` (catch IntegrityError → re-SELECT).
- [ ] Backend: GIN FTS index on `item_chunks.content` matching unified_search expression (migration).
- [ ] Web: fix `onCreated` add→feed disconnect (DashboardClient ~1825 loadRecordingsState → refresh items + toast); lift items state; poll/refresh-on-focus on ItemsFeed/ItemDetail.
- [ ] Web+Mac: unify kind taxonomy in WaiComputerKit + add missing **`pdf` filter chip**.
- [ ] Mac: render `MacContentFeedViewModel.errorMessage` inline banner; fix `MacBrainView try? getBrain()` → do/catch + .error/Retry; `addDraft()` polling after create.

### Phase 1 — File ingestion: the missing entrance
- [ ] Backend: `POST /items/upload` (multipart, kind-aware: PDF/doc→text→ingest_item; audio/video→import_media_as_recording). Reuse staging + 200MB cap; safe storage key (no filename trust). SSRF guard on fetch.
- [ ] Backend: widen `recordings.py` `ALLOWED_AUDIO_EXTENSIONS` to include `SUPPORTED_VIDEO_EXTENSIONS`.
- [ ] Backend: `classify_url` for direct media (.mp4/Vimeo/Loom) + reroute audio/* video/* content-type to transcription.
- [ ] Backend: `needs_input` reprocess endpoint (append body / attach file + re-enqueue).
- [ ] Web: rebuild AddAnythingPanel — drag-drop (react-dropzone) + file picker + paste-detect type chip + per-file XHR progress + multi-file queue.
- [ ] Mac: `.dropDestination` + `.fileImporter`; `APIClient.uploadItem(fileURL:kind:)` streaming.
- [ ] Web+Mac: render `needs_input` recovery (why + Paste/Attach/Retry).

### Phase 2 — Populate the knowledge graph (keystone)
- [ ] Backend: wire `extract_entities()` into recording pipeline (upsert entities by (user,type,lower(name)); write EntityRelation edges; set `entity.embedding`).
- [ ] Backend: wire entity extraction into item pipeline (promote people_mentioned/topics JSONB → entities; optional body extraction).
- [ ] Backend: polymorphic `EntityMention(entity_id, source_kind, source_id, chunk_id?, context, weight)` table + migration.
- [ ] Backend: feed Items into nightly consolidator (`_gather_user_material`).

### Phase 3 — Brain visualization on web (flagship)
- [ ] Backend: `GET /api/brain/graph` (nodes+edges: mention / co-occurrence / similarity; ego mode `?focus=&depth=`; caps).
- [ ] Backend: enrich wiki — `GET /api/entities/{id}/page` (backlinks + co-occurrence + sources).
- [ ] Web: Brain nav + route + tri-view (Index default / Wiki / Graph via react-force-graph-2d, ego default, items toggle). No-fallback graph error/retry.

### Phase 4 — Brain on Mac + comparison hardening + power features
- [ ] Mac: tabbed Graph|Wiki|Index in MacBrainView (wiki backlinks tappable; Canvas Verlet graph; BrainGraph kit models).
- [ ] Backend: comparison correctness (intent column, distinct items, deleted filter, retry, rebuild, parallel rows, export, cell edit).
- [ ] Web: switch search to unified `/api/search/all`; comparison builder; connect-a-source UI.

### Phase 5 — Robustness + governance
- [ ] Tiered video-by-link / yt-dlp (opt-in + daily cap); media classify_url; simhash fuzzy dedup; governance for items+entities; Person↔Entity reconcile; Brain-health lint; optional OCR (docling, MIT only).

## Progress log
- 2026-06-01: worktree + analysis workflow (21 agents) done; decisions locked; starting Phase 0 backend.
