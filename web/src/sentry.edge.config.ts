import * as Sentry from "@sentry/nextjs";

import { scrubBreadcrumb, scrubEvent } from "./sentry.sanitize";

// DSN is read from NEXT_PUBLIC_SENTRY_DSN at runtime; falls back to empty (no-op).
const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN || "";
const environment =
  process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ||
  (process.env.NODE_ENV === "production" ? "production" : "development");

Sentry.init({
  dsn,
  environment,
  sendDefaultPii: false,
  tracesSampleRate: 0.1,
  beforeSend: scrubEvent,
  beforeBreadcrumb: scrubBreadcrumb,
});
