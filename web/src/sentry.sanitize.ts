import type { Breadcrumb, ErrorEvent, EventHint } from "@sentry/nextjs";

const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;

function redactEmails(value: string): string {
  return value.replace(EMAIL_RE, "[redacted-email]");
}

/**
 * Drop the query string and fragment from a URL. They can carry magic-link
 * tokens, share secrets, or search queries — none of which may reach Sentry.
 * The path is kept so issues still group sensibly.
 */
function stripQuery(url: string): string {
  try {
    const parsed = new URL(url, "http://local");
    const base = parsed.origin === "http://local" ? "" : parsed.origin;
    return base + parsed.pathname;
  } catch {
    return url.split(/[?#]/)[0];
  }
}

export function scrubBreadcrumb(breadcrumb: Breadcrumb): Breadcrumb {
  if (breadcrumb.data) {
    for (const key of ["url", "from", "to"] as const) {
      const value = breadcrumb.data[key];
      if (typeof value === "string") {
        breadcrumb.data[key] = stripQuery(value);
      }
    }
  }
  if (typeof breadcrumb.message === "string") {
    breadcrumb.message = redactEmails(breadcrumb.message);
  }
  return breadcrumb;
}

export function scrubEvent(event: ErrorEvent, _hint: EventHint): ErrorEvent {
  if (event.request) {
    if (event.request.url) {
      event.request.url = stripQuery(event.request.url);
    }
    delete event.request.query_string;
    delete event.request.cookies;
    delete event.request.data;
    const headers = event.request.headers;
    if (headers) {
      delete headers.Authorization;
      delete headers.authorization;
      delete headers.Cookie;
      delete headers.cookie;
    }
  }
  if (event.message) {
    event.message = redactEmails(event.message);
  }
  for (const value of event.exception?.values ?? []) {
    if (value.value) {
      value.value = redactEmails(value.value);
    }
  }
  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs.map(scrubBreadcrumb);
  }
  return event;
}
