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

Alertable business anomalies must set `alert_code` in Sentry extras. The helper copies it to a Sentry tag.

## Sentry Projects

All WaiComputer surfaces must point at WaiComputer Sentry projects in the `waiwai-diy` organization, not the older `waisay-*` projects.

| Surface | Sentry project | Project ID |
| --- | --- | --- |
| Backend API and worker | `waicomputer-backend` | `4511116051873792` |
| Web | `waicomputer-web` | `4511421057466368` |
| iOS | `waicomputer-ios` | `4511116052070400` |
| macOS | `waicomputer-macos` | `4511116051939328` |
| Android | `waicomputer-android` | `4511455343214592` |
| Windows | `waicomputer-windows` | `4511421057335296` |
| Linux | `waicomputer-linux` | `4511455343738880` |

Production backend env must contain `SENTRY_DSN=<backend DSN ending in /4511116051873792>`. Production builds also require `SENTRY_AUTH_TOKEN` so web source maps and native debug files are uploaded during release.

Current alert codes:

- `recording.processing.stuck`
- `recording.transcript.low_coverage`
- `recording.upload.size_mismatch`

Use Sentry issue or metric alerts on `environment:production` with these tags. Keep alert rules focused on user-visible failure modes, not every debug counter.

## Required Sentry Rules

Create or verify these rules in every production Sentry project:

- Critical errors: `level:error environment:production`
- Recording stuck: `alert_code:recording.processing.stuck environment:production`
- Low transcript coverage: `alert_code:recording.transcript.low_coverage environment:production`
- Upload size mismatch spike: `alert_code:recording.upload.size_mismatch environment:production`
- Native crash-free sessions below target for macOS, iOS, Android, Windows when those projects are active.

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
ssh root@157.180.47.68 'cd /opt/waicomputer/backend && docker compose --env-file /etc/waicomputer/backend.env logs --tail=200 api'
ssh root@157.180.47.68 'cd /opt/waicomputer/backend && docker compose --env-file /etc/waicomputer/backend.env ps'
VPS_USER=root scripts/check-prod-observability.sh
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
