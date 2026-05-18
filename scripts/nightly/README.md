# WaiComputer Nightly QA Harness

Hourly end-to-end QA loop. Runs as a cron-fired agent iteration. Complementary to `scripts/qa-loop.sh` (which covers backend/shared/remote/native gates).

## What this harness does

Each iteration generates fresh TTS audio from Inworld, streams it through the same STT pipeline WaiComputer uses in production, computes word error rate (WER) and latency against the source text, then writes a structured report.

Two tiers:

- **Tier 1 (always on)**: Inworld TTS → Inworld STT round-trip + backend session minting. No virtual mic, no app launch, no reboot dependency. Validates the audio pipeline correctness on every iteration.
- **Tier 2 (opt-in via `NIGHTLY_TIER2=1`)**: BlackHole virtual mic + real WaiComputer.app launch + hot-key trigger + clipboard verification. Requires `BlackHole 2ch` driver installed (one-time `brew install --cask blackhole-2ch` + reboot).

## Outputs

```
scripts/nightly/.artifacts/
  last-report.md         # human-readable summary of latest run
  last-report.json       # machine-readable for trend tracking
  runs/<UTC-timestamp>/
    audio/<scenario>.wav # generated TTS
    transcripts/<scenario>.json
    metrics.json
    log.txt
```

## Iteration prompt

1. `cd /Users/mikwiseman/Documents/Code/wai-computer && git pull --ff-only origin main`
2. `./scripts/nightly/run.sh`
3. Read `scripts/nightly/.artifacts/last-report.md`
4. For each `FAIL` or `REGRESSION` row: investigate root cause, fix only at 100% confidence, add regression test, commit + push.
5. Verify CI green via `gh run list --limit 3 --branch main`.
6. One bounded improvement per iteration (speed OR stability) — only if 100% sure it doesn't break anything; back with tests.
7. Maintain coverage ≥95%: `cd backend && pytest -q --cov`, `cd web && pnpm test:unit`, `cd shared/WaiComputerKit && swift test -q`.
8. Remove ONE unnecessary fallback per iteration if obvious.

Reference: AGENTS.md, scripts/nightly/scenarios.json, Whispr Flow as UX bar (<700ms E2E after end-of-speech).

## Credentials

- `INWORLD_API_KEY` is read from `~/.config/waicomputer/inworld.env` (mode 0600, fetched once from prod `/etc/waicomputer/backend.env`).
- Production STT session minting uses `https://wai.computer/api/transcription/session` with a test access token from `~/.config/waicomputer/test-token.env` (optional — falls back to direct Inworld auth).

## Why hourly, not on every push

This loop is for **drift detection**: provider regressions, model drift, latency creep. Push-time CI already covers green-builds. Hourly catches things that change outside our repo (Inworld voice updates, network conditions, prod env drift).

## Scenario coverage

`scenarios.json` enumerates the matrix. Categories:
- `core_command` — short imperative dictations (5-15 words)
- `long_form` — paragraph-length monologue (50-200 words)
- `multilang` — RU + EN switching mid-sentence
- `numbers_punct` — phone numbers, emails, URLs, dates
- `whisper_low_gain` — soft speech, low SNR
- `accent` — non-native English speakers
- `code_dictation` — programming jargon, snake_case, CamelCase
- `proper_nouns` — names, brands, places
- `interruption` — pauses + resumes mid-sentence
- `silence_only` — pure silence (should produce empty transcript)

Each scenario specifies:
- expected text (ground truth)
- voice ID
- language
- max acceptable WER
- max acceptable end-of-speech-to-final latency

Add a scenario by editing `scenarios.json` and committing. The harness auto-picks them up next iteration.
