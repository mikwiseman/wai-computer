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
- [~] Backend: `POST /items/upload` — DOCUMENTS done (PDF/txt/md → extract text → Item; 200MB cap; UUID storage key; dedup-unlink; shared `_enqueue_item_summary`). PENDING: audio/video → Recording (needs async enqueue — `import_media_as_recording` transcribes inline, too slow for an HTTP request); SSRF guard is a separate fetch-path slice.
  - IMPL NOTE: build a NEW `/items/upload` route — do NOT overload `/recordings/{id}/upload` (recordings.py:2853), it's intricate (claim-race `_claim_audio_upload`, size-mismatch, `_mark_recording_failed`). Reuse `_stage_upload_to_disk` (recordings.py:987) + `MAX_UPLOAD_SIZE` (2850) + `_measure_upload_size` (860). PDF→`source_fetch._extract_pdf_text` (or pdfplumber) → `ingest_item`; audio/video → `recording_import.import_media_as_recording` (recording_import.py:456, handles video via `_normalize_media_for_transcription`→Deepgram). Storage key `{user_id}/{uuid}.{ext}` — never trust `UploadFile.filename`.
- [ ] Backend: widen `recordings.py` `ALLOWED_AUDIO_EXTENSIONS` to include `SUPPORTED_VIDEO_EXTENSIONS` (only if keeping the recordings endpoint as a video path; otherwise `/items/upload` → import_media_as_recording covers it).
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
- 2026-06-01: Phase 0 COMPLETE across surfaces — backend (01ccea77), web (fa061364), Mac (58bda2f7, xcodebuild ✓).
- 2026-06-01: Phase 1a — `POST /items/upload` for documents (PDF/txt/md → Item). 19 items-route tests green; full backend suite 95.11% (gate ✓). Heads-up: main is red on 2 `test_observability.py` tests (`OPS_FORWARD_GENERIC_ERRORS` default-off, commit c0661d4b — owned by the sentry-telegram-bridge loop, NOT this work). Next: media upload (audio/video→Recording, async), `classify_url` media + SSRF guard, then web drag-drop + Mac .fileImporter.
