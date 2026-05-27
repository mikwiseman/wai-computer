# WaiComputer Nightly QA Harness

Hourly realtime dictation QA loop. Runs as a cron-fired agent iteration. Complementary to `scripts/qa-loop.sh` (which covers backend/shared/remote/native gates).

## What this harness does

Each iteration generates a local macOS `say` fixture, mints the production Deepgram Nova-3 realtime session through `https://wai.computer/api/transcription/session`, streams PCM audio to the returned provider WebSocket, computes word/character error rate and latency, then writes a structured report.

The harness intentionally uses the same server-minted Deepgram realtime path as the native app. It does not maintain separate direct-provider credentials.

## Outputs

```
scripts/nightly/.artifacts/
  last-report.md         # human-readable summary of latest run
  last-report.json       # machine-readable for trend tracking
  last-run.log
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

Reference: AGENTS.md and Whispr Flow as UX bar (<700ms E2E after end-of-speech).

## Credentials

- The script creates an isolated temporary WaiComputer account and uses that access token only for the run.
- Provider credentials stay on the backend. The script never reads provider API keys.

## Why hourly, not on every push

This loop is for **drift detection**: provider regressions, model drift, latency creep, session minting failures, and prod env drift. Push-time CI already covers green-builds. Hourly catches things that change outside our repo.
