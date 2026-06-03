# Billing v1.0 — launch checklist

## Status snapshot — 2026-05-18

All ten implementation phases of the billing sprint are merged on `main`:

| Phase | Status | Where |
| ----- | ------ | ----- |
| 1. Backend skeleton + word quota | ✅ | `backend/app/billing/`, migration `20260520_120000` |
| 2. Stripe rail (Subscriptions + webhook) | ✅ | `backend/app/billing/providers/stripe_provider.py` |
| 3. T-Bank rail + 54-ФЗ receipts | ✅ | `backend/app/billing/providers/tinkoff_provider.py` |
| 4. Region-aware checkout routing | ✅ | `backend/app/billing/router.py` |
| 5. Mac one-binary-two-DMG build | ✅ | `scripts/build-macos-dmg.sh` accepts `MACOS_VARIANT` |
| 6. Mac localization infra | ✅ | `WaiComputerKit/Localization/LanguageManager`, `Localizable.xcstrings` |
| 7. Mac Billing UI + usage gauge | ✅ | `Features/Billing/BillingSection`, `Settings/AppLanguagePicker` |
| 8. Web pricing + billing pages | ✅ | `/pricing`, `/ru/pricing`, `/billing`, `/ru/billing` |
| 9. Marketing landing variants | ✅ | `/` (EN) and `/ru` (RU) with paired DMG links |
| 10. Prod env + launch QA | 🟡 sandbox green | This doc |

Tests: 33 backend billing tests pass; full backend test suite green; macOS app
builds clean; Next.js production build emits all routes.

## Sandbox configuration (live now)

- Stripe Test account: WaiWai (`acct_1RKJo1ENNsR4WtAW`).
  - Product: `prod_UXZjvYKzivF4G8` (WaiComputer Pro).
  - Prices: `price_1TYUaVENNsR4WtAWrMI4kLWf` ($12/mo),
    `price_1TYUaWENNsR4WtAWRuIYlp7t` ($96/yr).
  - Webhook endpoint: `we_1TYUaAENNsR4WtAW3Y33JQtX` →
    `https://wai.computer/api/webhooks/stripe` (6 events).
- T-Bank sandbox terminal: `1779952891293DEMO` (rub billing rail).
  54-ФЗ tax mode currently `usn_income` with
  `vat22` rate — adjust if the prod merchant entity uses a different
  taxation regime.
- Local `backend/.env` carries all four secrets (gitignored).

Smoke checks done:

- `client.v1.checkout.sessions.create_async` against sandbox Stripe → returns
  hosted Checkout URL.
- Signature verifier round-trips a fake T-Bank notification body.
- `/api/billing/usage` returns 0/3000 for a new Free user, increments after
  a dictation entry is persisted, 402s when the cap would be exceeded.
- Sparkle keys / Developer ID identity unchanged — DMG builds use the
  existing `is.waiwai.computer` bundle id for both variants.

## Cutover to prod

When ready to flip the live switch:

1. **Live Stripe credentials** — toggle off Test mode in Dashboard, repeat
   the steps in `billing-setup.md` to issue `sk_live_…`, `pk_live_…`, and
   a webhook signing secret pointing at `https://wai.computer/api/webhooks/stripe`.
   Create a live `WaiComputer Pro` product + monthly/yearly prices.
2. **Live Stripe Tax** — set a head-office address under Settings → Tax,
   then flip `STRIPE_AUTOMATIC_TAX=1` in prod env.
3. **Live T-Bank terminal** — activate the production terminal under
   ООО WaiWai (or the chosen merchant entity) and confirm the
   NotificationURL points at `https://wai.computer/api/webhooks/tinkoff`.
4. **Prod backend env** — SSH to `root@157.180.47.68` and edit
   `/etc/waicomputer/backend.env` to add:
   ```
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_PUBLISHABLE_KEY=pk_live_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   STRIPE_AUTOMATIC_TAX=true
   TINKOFF_API_URL=https://securepay.tinkoff.ru/v2/
   TINKOFF_TERMINAL_KEY=...        # live terminal
   TINKOFF_PASSWORD=...
   BILLING_TRIAL_DAYS=0
   BILLING_REFUND_WINDOW_DAYS=7
   BILLING_DEFAULT_REGION=global
   ```
5. **Run migrations + deploy**:
   ```bash
   VPS_USER=root ./scripts/deploy-server.sh
   # On the server, in /opt/waicomputer/backend:
   docker compose --env-file /etc/waicomputer/backend.env exec api alembic upgrade head
   docker compose --env-file /etc/waicomputer/backend.env exec api \
     python -c "from sqlalchemy import create_engine, text; \
       e=create_engine('postgresql+psycopg2://...'); \
       e.execute(text(\"UPDATE billing_plans SET stripe_price_id_monthly='price_live_…', stripe_price_id_yearly='price_live_…' WHERE code='pro';\"))"
   ```
   (or just `psql` directly.)
6. **Build + publish RU and Global DMGs**:
   ```bash
   VPS_USER=root scripts/release-macos.sh stable
   # Builds both variants, uploads WaiComputer-1.0.x-N.dmg and
   # WaiComputer-ru-1.0.x-N.dmg, merges the appcast.
   ```
7. **Smoke the live flow** end-to-end:
   - Visit `https://wai.computer/pricing` and `https://wai.computer/ru/pricing` —
     verify currency display + hreflang in HTML source.
   - Visit `/billing` signed in, click Upgrade → Stripe Checkout in browser,
     pay with `4242 4242 4242 4242` → webhook fires → Mac app shows Pro
     after `GET /api/billing/subscription`.
   - Repeat with `/ru/billing` against a Russian-region user — should land
     on T-Bank hosted form (sandbox card `4300 0000 0000 0777`).

## Risks tracked

- **Stripe Tax in EU/UK/AU** — not auto-collecting yet because the head
  office address isn't set on the live account. Action: configure before
  the first paid EU customer signs up.
- **54-ФЗ taxation mode** — the receipt builder hardcodes `usn_income`.
  If the prod merchant entity uses ОСН or another mode, change
  `build_receipt()` in `tinkoff_provider.py` before live cutover.
- **User.region** — currently we have the column on the User model but
  the signup flow doesn't yet write it from `WAIDownloadRegion`. The Mac
  app uses the build-time stamp as a UI fallback; full server-side
  routing comes from the auth flow once the signup payload includes
  region. Tracked as a follow-up after launch.
- **Memory retention enforcement** — the `memory_retention_days` plan
  column is stored but the nightly Celery sweep that flips `indexed=false`
  on stale documents isn't wired yet. Free users can still see >30d
  recordings until the sweeper ships in the next sprint.
