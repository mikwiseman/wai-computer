import * as Sentry from "@sentry/nextjs";

import { scrubBreadcrumb, scrubEvent } from "./sentry.sanitize";

Sentry.init({
  dsn: "<SENTRY_DSN>",
  environment: process.env.NODE_ENV === "production" ? "production" : "development",
  // Privacy: never attach IP/headers; remaining PII is scrubbed in beforeSend.
  // No session replay — it would capture DOM/transcript content.
  sendDefaultPii: false,
  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,
  beforeSend: scrubEvent,
  beforeBreadcrumb: scrubBreadcrumb,
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
