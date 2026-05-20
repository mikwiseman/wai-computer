import * as Sentry from "@sentry/nextjs";

import { scrubBreadcrumb, scrubEvent } from "./sentry.sanitize";

Sentry.init({
  dsn: "<SENTRY_DSN>",
  environment: process.env.NODE_ENV === "production" ? "production" : "development",
  sendDefaultPii: false,
  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,
  beforeSend: scrubEvent,
  beforeBreadcrumb: scrubBreadcrumb,
});
