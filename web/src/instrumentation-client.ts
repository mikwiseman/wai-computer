import * as Sentry from "@sentry/nextjs";

import { scrubBreadcrumb, scrubEvent } from "./sentry.sanitize";

// DSN is injected at build time via NEXT_PUBLIC_SENTRY_DSN; if absent
// (local dev without a Sentry project) the SDK silently no-ops on init.
const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN || "";
const environment =
  process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ||
  (process.env.NODE_ENV === "production" ? "production" : "development");

Sentry.init({
  dsn,
  environment,
  // Privacy: never attach IP/headers; remaining PII is scrubbed in beforeSend.
  sendDefaultPii: false,
  tracesSampleRate: 0.1,
  // Session Replay — masked. Sampled at 5% baseline, 100% on error.
  replaysSessionSampleRate: 0.05,
  replaysOnErrorSampleRate: 1.0,
  integrations: [
    Sentry.replayIntegration({
      // Privacy: mask all text + media; never capture transcript / recording UI.
      maskAllText: true,
      blockAllMedia: true,
    }),
  ],
  beforeSend: scrubEvent,
  beforeBreadcrumb: scrubBreadcrumb,
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
