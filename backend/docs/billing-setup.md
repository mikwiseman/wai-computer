# Billing setup — sandbox keys + webhooks

How to wire WaiComputer's billing layer (Stripe global rail + T-Bank RU rail)
in **sandbox / test mode** so we can run E2E payments without touching real
money.

## Stripe (test mode)

WaiComputer reuses the **WaiWai, LLC** Stripe account (the same one wai-pay
and WaiConnect live under). Sandbox products were created via the Stripe
MCP on `2026-05-20`:

```
Product   : prod_UXZZuOxIg23AT0  (WaiComputer Pro)
Price/mo  : price_1TYUQ5ERwl8TW9QHsvjvW5IE  ($12.00 / month)
Price/yr  : price_1TYUQ6ERwl8TW9QHdD1OpX7S  ($96.00 / year)
livemode  : false
```

These IDs are already written into the local `billing_plans.pro` row. The
prod deploy needs the same IDs (or live equivalents — TODO at launch).

### 1. Grab the test secret key

1. Open <https://dashboard.stripe.com>.
2. Toggle **Test mode** in the top-right (orange "Test mode" badge appears).
3. Sidebar → **Developers** → **API keys**.
4. Under "Standard keys", click **Reveal test key** next to "Secret key".
5. Copy the value — it starts with `sk_test_`.
6. Copy the "Publishable key" too — starts with `pk_test_`.

Paste both into `backend/.env`:

```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
```

### 2. Create a webhook endpoint and grab its signing secret

#### Option A — testing against the prod URL

Use when you want to receive real webhook deliveries on the live server.

1. Dashboard (Test mode) → **Developers** → **Webhooks** → **Add endpoint**.
2. Endpoint URL: `https://wai.computer/api/webhooks/stripe`
3. Events to send:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`
4. Save. On the endpoint detail page, click **Reveal** under "Signing secret".
5. Copy `whsec_...`. Paste into `backend/.env`:

   ```
   STRIPE_WEBHOOK_SECRET=whsec_...
   ```

#### Option B — local dev via Stripe CLI (recommended for iteration)

1. Install: `brew install stripe/stripe-cli/stripe`
2. Login: `stripe login` (uses browser OAuth — needs Test mode toggle on dashboard).
3. Start the local backend: `cd backend && uvicorn app.main:app --reload`.
4. Forward webhooks: `stripe listen --forward-to localhost:8000/api/webhooks/stripe`.
5. The CLI prints `Your webhook signing secret is whsec_xxx (^C to quit)`.
6. Use **that** secret in `backend/.env`. Restart uvicorn.

### 3. Smoke test

```bash
# Trigger a fake checkout.session.completed against the local backend:
stripe trigger checkout.session.completed

# Or run an actual hosted-checkout flow:
curl -X POST http://localhost:8000/api/billing/checkout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro","period":"month"}'
# → {"provider":"stripe","checkout_url":"https://checkout.stripe.com/c/pay/cs_test_..."}
```

Test card: `4242 4242 4242 4242`, any future expiry, any CVC, any ZIP.

## T-Bank эквайринг (sandbox)

T-Bank's sandbox runs against the same API base (`securepay.tinkoff.ru`)
with a separate **TerminalKey** issued for testing. wai-pay already has
the production terminal for ООО WaiWai (`TINKOFF_WAIWAI_LLC_*` in
`/srv/wai-pay/.env`). The sandbox terminal is a separate row in the
T-Bank merchant cabinet.

### 1. Find or create the sandbox terminal

1. Log in to <https://business.tbank.ru>.
2. Эквайринг → **Терминалы**.
3. Look for a terminal flagged "Тестовый" / "Sandbox". If absent: **Создать
   терминал** → "Тестовый" → entity ООО WaiWai → enable "Рекуррентные
   платежи" (Recurrent) + "Уведомления" (webhook).
4. Open the terminal → copy **TerminalKey** and **Пароль** (Password).

### 2. Configure the NotificationURL

In the sandbox terminal settings:

- **NotificationURL**: `https://wai.computer/api/webhooks/tinkoff`
  - Or, for local dev: route via an `ngrok` / `cloudflared` tunnel.
- **SuccessURL**: `https://wai.computer/billing/success`
- **FailURL**: `https://wai.computer/billing/cancel`

### 3. Drop creds into `backend/.env`

```
TINKOFF_API_URL=https://securepay.tinkoff.ru/v2/
TINKOFF_TERMINAL_KEY=...        # from sandbox terminal
TINKOFF_PASSWORD=...             # from sandbox terminal
```

### 4. Test cards

Sandbox terminal accepts these test PANs:

| Outcome  | PAN                | 3DS  |
| -------- | ------------------ | ---- |
| Success  | 4300 0000 0000 0777 | none |
| Decline  | 5000 0000 0000 1409 | none |
| 3DS pass | 4000 0000 0000 0002 | OTP `12345678` |

Expiry: any future. CVV: any 3 digits.

### 5. Smoke test

```bash
curl -X POST http://localhost:8000/api/billing/checkout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro","period":"month","provider":"tinkoff"}'
# → {"provider":"tinkoff","checkout_url":"https://securepay.tinkoff.ru/.../"}
```

Open the URL, pay with a test card, and watch the backend log for the
incoming `tinkoff_webhook` — `subscription.status` should flip to `active`
after the CONFIRMED notification.

## After both rails are live

Update production env at `<release-user>@<release-host>:<remote-env-file>`
with the **live** (not test) values when ready. Test → Live cutover
checklist:

- [ ] Create live Stripe products + prices, set IDs on the prod
      `billing_plans.pro` row.
- [ ] Register live Stripe webhook at `https://wai.computer/api/webhooks/stripe`.
- [ ] Activate T-Bank prod terminal under ООО WaiWai.
- [ ] Set live keys in `<remote-env-file>`.
- [ ] `scripts/deploy-server.sh` to roll out.
- [ ] Subscribe a known dev account end-to-end on both rails.
