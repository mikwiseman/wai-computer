import * as Sentry from "@sentry/nextjs";

import { scrubBreadcrumb, scrubEvent } from "./sentry.sanitize";

Sentry.init({
  dsn: "https://ad90f87bdb0757fa0dd53e7740b7b6ed@o4508963132145664.ingest.us.sentry.io/4511421057466368",
  environment: process.env.NODE_ENV === "production" ? "production" : "development",
  sendDefaultPii: false,
  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,
  beforeSend: scrubEvent,
  beforeBreadcrumb: scrubBreadcrumb,
});
