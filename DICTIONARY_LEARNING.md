# Dictation Dictionary — Learn-From-Edits (Mac + backend)

Status: in progress · Started 2026-06-09 · Branch `feat/dictation-dictionary-learning`

Goal: turn the existing **manual** dictation dictionary into one that **learns**. When the
user repeatedly fixes the same mis-heard word after dictation, WaiComputer detects it and
**suggests adding it to the dictionary** (one-tap Accept / Make-replacement / Dismiss). This
is the Wispr Flow / Typeless / Willow pattern, built the privacy-correct way.

Decisions (Mik, 2026-06-09):
- **Capture surface:** macOS Accessibility paste-target monitor **+** in-app baseline (edits to dictation-history rows). No web/iOS/Android this cut.
- **Add UX:** *suggest with one-tap confirm* after a recurrence threshold — never silent, never a mid-flow modal.
- **Scope:** macOS app + backend only.

## What already exists (do not rebuild)

- Backend `dictation_dictionary_words` (`word` + optional `replacement`), CRUD `/api/dictation/dictionary`.
  `load_user_keyterms()` (`backend/app/core/personalization.py`) → Deepgram `keyterm` on nova-3 (stream+batch).
  `DictationEntry` stores `raw_text` + `cleaned_text` per dictation.
- Mac/iOS/web/.NET: dictionary UI + local store + server sync (tombstones). Words split **BIAS** (→keyterm) and **REPLACE** (post-STT whole-word swap). Mac/web use proper Unicode word boundaries; .NET has a substring bug (out of scope here).
- Mac flow: `DictationManager.insertFinalText(textToInsert:rawText:cleanedText:)` pastes via `TextInserter.insert` (clipboard+⌘V, Accessibility-gated) then `historyStore.add(...)`.

## The two STT mechanisms (both kept)

1. **STT-side biasing** — dictionary words become Deepgram `keyterm`s so the model hears them right. Primary mechanism, best for Russian (handles inflection at decode time).
2. **Deterministic post-replacement** — `word→replacement` swap for the "always wrong the same way" case + casing. Client-side already; we also wire Deepgram `replace` server-side so **file/recording** transcripts honor the dictionary (they have no client replacement and no LLM cleanup).

## The learn-from-edits loop (5 stages, all on-device)

1. **Capture** — after we paste, watch the same field (macOS AX). When the user edits within a window, `(produced, edited)` is a correction pair. Also: editing a dictation-history row in-app.
2. **Align** — token-level Damerau-Levenshtein diff → substitution pairs. Normalize case + trailing punctuation first (Mac `lowercased()` is ICU-correct; Cyrillic folds fine).
3. **Phonetic gate** — learn **mis-hearings**, not rewrites. EN metaphone-ish; RU reduction rules (vowel-collapse + final devoicing); else normalized edit-distance ratio. Phonetically-distant pair ⇒ discard.
4. **Class gate** — the corrected token must be **OOV / proper-noun**, never a common word (the single most important filter; `NSSpellChecker` decides "known common word"). Drop elongations, missing-apostrophe, pure-case/punct, and pure-numeral edits (numerals route to the formatter, not the dictionary).
5. **Promote & surface** — keep a hit-count per pair in a rolling 30-day window; at **count ≥ 2** surface a non-blocking suggestion. Accept → add a **BIAS** entry (`word: corrected`) [+ optional REPLACE `original→corrected`], marked **learned** (✨). Dismiss → suppress that pair. Everything editable/deletable.

## Privacy (hard rule — AGENTS.md: never log transcript text)

- All diffing/extraction happens **on-device**. We persist only **token pairs + counts** in a local, never-synced, never-logged ledger (`Application Support/WaiComputer/dictation_learning_ledger.json`), pruned to the 30-day window. **No sentences, no surrounding context, ever.**
- AX monitor **skips native secure text fields** (`NSSecureTextField`) and is gated by a Settings toggle. Web/Electron password fields aren't always AX-flagged as secure — but the watcher only arms after we paste dictated text in dictation mode, the read value never leaves on-device extraction, and only token pairs persist, so nothing sensitive is stored or logged.
- Only the *accepted* word (the same sensitivity as the existing dictionary) is written + synced. Telemetry carries content-free events only (`type=proper_noun`, length bucket) — never the word.

## Architecture / file map

### Shared engine — `shared/WaiComputerKit/Sources/WaiComputerKit/Dictation/Learning/` (pure Foundation, AppKit-free, iOS-reusable)
- `CorrectionTypes.swift` — `CorrectionPair`, `CorrectionExtractionResult`, `LexiconChecking` protocol, `DictionarySuggestion`. **(frozen contract — written first)**
- `TokenAlignment.swift` — `tokenize`, `normalize`, `align` (Damerau-Levenshtein over tokens), `locate` (find inserted region inside a larger field).
- `PhoneticMatcher.swift` — `areSoundAlike`, `similarity`, `code` (EN + RU + fallback).
- `CorrectionExtractor.swift` — `extract(produced:edited:language:)` → gated `[CorrectionPair]` (noise + phonetic + class gates).
- `DictionaryLearningEngine.swift` — `@MainActor ObservableObject`; owns the ledger, window, `promoteAfter`; `@Published suggestions`; `observeEdit / accept / dismiss / clearAll`. Persists on-device only.

### macOS app — `macos/WaiComputer/WaiComputer/Features/Dictation/`
- `MacLexiconChecker.swift` — `LexiconChecking` via `NSSpellChecker`.
- `DictationEditWatcher.swift` — AX: snapshot focused element value after paste, re-read at settle (next dictation / app deactivate / timeout), scope to inserted region, call `engine.observeEdit`. Skips secure fields.
- `DictationManager.swift` — inject engine; after successful insert start the watcher with `textToInsert`+`targetApp`; on history-row edit call `observeEdit`.
- `DictationDictionaryView.swift` — suggestions section at top (Accept = BIAS / Make-replacement / Dismiss); ✨ marker on learned entries.
- Settings — "Suggest dictionary words from my edits" toggle (default on).

### backend
- `core/personalization.py` — fix `sanitize_keyterms` token budget to estimate **subword** tokens (Cyrillic ≈ 2 chars/token, Latin ≈ 4), not whitespace words; align loader caps to Deepgram real (100 terms / 500 tokens). Latent prod 400 for Russian dictionaries otherwise.
- `core/deepgram.py` — add `replace=find:replace` wiring (`sanitize_deepgram_replacements`, find lowercased, word-level) to `build_batch_url` (+ `transcribe_audio_file`); load via dictionary REPLACE entries at the file-STT call site.
- `models/dictation.py` + migration + `routes/dictation.py` — add `origin` (`manual`|`learned`, default `manual`) to `DictationDictionaryWord` so the ✨ marker syncs across Macs.

## Defaults (synthesized; tune later)
- `promoteAfter = 2` recurrences · `window = 30 days` · `maxDivergenceRatio = 0.5` (bail on big rewrites) · `minTokenLength = 2` · phonetic similarity accept ≥ `0.72` (or metaphone-equal).

## Tests (TDD)
- Kit: `TokenAlignmentTests`, `PhoneticMatcherTests`, `CorrectionExtractorTests` (EN+RU, with a fake `LexiconChecking`), `DictionaryLearningEngineTests` (recurrence threshold, window pruning, suppress).
- Backend: token-budget estimator (Cyrillic), `replace` sanitizer + batch URL, `origin` round-trip.
- App: build + `swift test` + real-app smoke (dictate → simulate an edit → suggestion appears → accept writes a ✨ entry).
