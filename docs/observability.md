# Observability

WaiComputer observability has three layers:

1. Sentry for exceptions, regressions, release correlation, and alertable business anomalies.
2. Server JSON logs for incident reconstruction from Docker logs.
3. Admin and health endpoints for current operational state.

Privacy rule: never log raw emails, tokens, filenames, transcript text, search queries, prompts, or provider payloads.

## Runtime Surfaces

- Public liveness: `GET https://wai.computer/health/live`
- Public readiness: `GET https://wai.computer/health/ready`
- Legacy health: `GET https://wai.computer/health`
- Admin UI: `https://wai.computer/admin?tab=observability`
- Admin API: `GET /api/admin/observability`

The admin observability snapshot is aggregate-only. It includes:

- database readiness
- runtime release/environment/log format
- Sentry configured/release/environment/sample rates
- recording status counts
- last-24h recording failures and failure rate
- stuck processing count
- low transcript coverage count
- alert codes currently above threshold

## Sentry Event Contract

Alertable business anomalies must set `alert_code` in Sentry extras. The backend
`capture_sentry_anomaly(...)` helper emits both a breadcrumb and a warning/error
message, then copies stable fields such as `alert_code`, `provider`, `model`,
`platform`, `purpose`, `failure_code`, and `status_code` to Sentry tags.

Normal successful lifecycle events should stay as breadcrumbs/logs. Only
user-visible anomalies, sustained degradation, timeout, retry exhaustion, or
privacy-safe business failures should become Sentry events.

## Sentry Projects

All WaiComputer surfaces must point at WaiComputer Sentry projects in the `waiwai-diy` organization, not the older `waisay-*` projects.

| Surface | Sentry project |
| --- | --- |
| Backend API and worker | `waicomputer-backend` |
| Web | `waicomputer-web` |
| iOS | `waicomputer-ios` |
| macOS | `waicomputer-macos` |
| Android | `waicomputer-android` |

Production backend env must contain `SENTRY_DSN`. Production builds also
require `SENTRY_AUTH_TOKEN` so web source maps and native debug files are
uploaded during release.

Current alert codes:

- `companion.turn.failed`
- `companion.turn.slow`
- `dictation.first_token.slow`
- `dictation.session.failed_cluster`
- `dictation.total_latency.slow`
- `realtime.session_mint.failed`
- `realtime.session_mint.slow`
- `recording.embeddings.degraded`
- `recording.file_stt.slow`
- `recording.processing.failed`
- `recording.processing.retry_exhausted`
- `recording.processing.slow`
- `recording.processing.stuck`
- `recording.processing.timeout`
- `recording.staged_file.missing`
- `recording.transcript.low_coverage`
- `recording.transcript.empty`
- `recording.upload.size_mismatch`
- `recording.title_generation.degraded`
- `recording.voice_identification.degraded`
- `search.query.slow`

Use Sentry issue or metric alerts on `environment:production` with these tags. Keep alert rules focused on user-visible failure modes, not every debug counter.

Current latency thresholds:

- file STT slow: `max(120s, audio_duration_seconds * 3)`
- end-to-end recording processing slow: `max(300s, effective_duration_seconds * 4)`
- realtime session mint slow: `2s`
- native dictation first token slow: `3s`
- native dictation total hotkey-to-insertion slow: `8s`
- backend search query slow: `5s`
- companion turn slow: `30s`

## Required Sentry Rules

Create or verify these rules in every production Sentry project:

- Critical errors: `level:error environment:production`
- Recording stuck: `alert_code:recording.processing.stuck environment:production`
- Recording processing slow/timeout/retry exhausted: `alert_code:recording.processing.slow OR alert_code:recording.processing.timeout OR alert_code:recording.processing.retry_exhausted environment:production`
- File STT slow: `alert_code:recording.file_stt.slow environment:production`
- Low transcript coverage: `alert_code:recording.transcript.low_coverage environment:production`
- Empty transcript spike: `alert_code:recording.transcript.empty environment:production`
- Upload size mismatch spike: `alert_code:recording.upload.size_mismatch environment:production`
- Dictation latency: `alert_code:dictation.first_token.slow OR alert_code:dictation.total_latency.slow environment:production`
- Realtime session mint failures: `alert_code:realtime.session_mint.failed environment:production`
- Companion/search latency: `alert_code:companion.turn.slow OR alert_code:search.query.slow environment:production`
- Native crash-free sessions below target for macOS, iOS, and Android when those projects are active.

Notification target should be a team channel first. Page only on critical recording ingestion or sustained API errors.

## Uptime Checks

External uptime monitor:

- URL: `https://wai.computer/health/ready`
- Expected status: `200`
- Expected body contains: `"status":"healthy"`
- Check interval: 1 minute
- Alert after: 3 consecutive failures

Do not use the realtime WebSocket route as an uptime probe. It requires an authenticated protocol flow and can look broken to plain HTTP tools.

## Server Logs

Backend logs are JSON lines with these fields:

- `timestamp`
- `level`
- `logger`
- `message`
- `request_id`
- `request_method`
- `request_path`
- `user_id`
- `recording_id`
- `session_id`

Useful commands:

```bash
ssh "$VPS_USER@$VPS_HOST" "cd $REMOTE_ROOT/backend && docker compose --env-file $REMOTE_ENV_FILE logs --tail=200 api"
ssh "$VPS_USER@$VPS_HOST" "cd $REMOTE_ROOT/backend && docker compose --env-file $REMOTE_ENV_FILE ps"
scripts/check-prod-observability.sh
```

## Incident Triage

1. Check public readiness: `curl -fsS https://wai.computer/health/ready`.
2. Check container health on the VPS.
3. Open `/admin?tab=observability` and inspect active alert codes.
4. In Sentry, filter by `environment:production` and the relevant `alert_code`.
5. Correlate Sentry event `request_id` or `recording_id` with Docker JSON logs.
6. For recording issues, inspect client-side backup/sync logs before asking the user to retry.

## References

- Sentry Python options: https://docs.sentry.io/platforms/python/configuration/options/
- Sentry Python logging integration: https://docs.sentry.io/platforms/python/integrations/logging/
- Sentry alerts: https://docs.sentry.io/product/alerts/
