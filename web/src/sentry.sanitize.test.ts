import type { Breadcrumb, ErrorEvent } from "@sentry/nextjs";
import { describe, expect, it } from "vitest";

import { scrubBreadcrumb, scrubEvent } from "./sentry.sanitize";

describe("scrubBreadcrumb", () => {
  it("strips query + fragment from absolute url/from/to and keeps the origin", () => {
    const result = scrubBreadcrumb({
      category: "navigation",
      data: {
        url: "https://wai.computer/share?token=secret#frag",
        from: "https://wai.computer/login?magic=abc123",
        to: "https://wai.computer/dashboard?q=who+said+x",
      },
    });

    expect(result.data).toEqual({
      url: "https://wai.computer/share",
      from: "https://wai.computer/login",
      to: "https://wai.computer/dashboard",
    });
  });

  it("drops the synthetic http://local origin for relative paths", () => {
    const result = scrubBreadcrumb({
      data: { from: "/recordings/42?token=leak", to: "/settings#mcp" },
    });

    // The http://local sentinel origin must not leak into the stored value.
    expect(result.data?.from).toBe("/recordings/42");
    expect(result.data?.to).toBe("/settings");
    expect(String(result.data?.from)).not.toContain("local");
  });

  it("falls back to a plain query/fragment split when URL parsing throws", () => {
    // A malformed IPv6 literal makes `new URL()` throw, exercising the catch
    // branch that strips everything from the first ? or # without parsing.
    const result = scrubBreadcrumb({
      data: { url: "http://[::1/bad?token=secret#frag" },
    });

    expect(result.data?.url).toBe("http://[::1/bad");
  });

  it("leaves non-string data values untouched", () => {
    const data: Record<string, unknown> = {
      url: 123,
      to: { nested: true },
      from: null,
    };
    const result = scrubBreadcrumb({ data });

    expect(result.data?.url).toBe(123);
    expect(result.data?.to).toEqual({ nested: true });
    expect(result.data?.from).toBeNull();
  });

  it("redacts emails embedded in the breadcrumb message", () => {
    const result = scrubBreadcrumb({
      message: "login failed for Alice@Example.COM and bob@test.io",
    });

    expect(result.message).toBe(
      "login failed for [redacted-email] and [redacted-email]",
    );
  });

  it("leaves a non-string message alone and tolerates a missing data bag", () => {
    const result = scrubBreadcrumb({ message: undefined });

    expect(result.message).toBeUndefined();
    expect(result.data).toBeUndefined();
  });

  it("mutates and returns the same breadcrumb instance", () => {
    const breadcrumb: Breadcrumb = {
      data: { url: "https://wai.computer/x?y=1" },
      message: "user@host.com",
    };
    const result = scrubBreadcrumb(breadcrumb);

    expect(result).toBe(breadcrumb);
    expect(breadcrumb.data?.url).toBe("https://wai.computer/x");
    expect(breadcrumb.message).toBe("[redacted-email]");
  });
});

describe("scrubEvent", () => {
  it("strips the request url and deletes sensitive request fields + headers", () => {
    const event = {
      request: {
        url: "https://wai.computer/api/search?q=secret#frag",
        query_string: "q=secret",
        cookies: { session: "abc" },
        data: { password: "hunter2" },
        headers: {
          Authorization: "Bearer token",
          authorization: "Bearer token-lower",
          Cookie: "session=abc",
          cookie: "session=abc",
          "User-Agent": "vitest",
        },
      },
    } as unknown as ErrorEvent;

    const result = scrubEvent(event);

    expect(result.request?.url).toBe("https://wai.computer/api/search");
    expect(result.request).not.toHaveProperty("query_string");
    expect(result.request).not.toHaveProperty("cookies");
    expect(result.request).not.toHaveProperty("data");
    const headers = result.request?.headers as Record<string, string>;
    expect(headers).not.toHaveProperty("Authorization");
    expect(headers).not.toHaveProperty("authorization");
    expect(headers).not.toHaveProperty("Cookie");
    expect(headers).not.toHaveProperty("cookie");
    // Non-sensitive headers survive so issues still carry useful context.
    expect(headers["User-Agent"]).toBe("vitest");
  });

  it("handles a request that has no url and no headers", () => {
    const event = {
      request: { query_string: "q=x", cookies: { a: "b" }, data: { c: "d" } },
    } as unknown as ErrorEvent;

    const result = scrubEvent(event);

    expect(result.request?.url).toBeUndefined();
    expect(result.request).not.toHaveProperty("query_string");
    expect(result.request).not.toHaveProperty("cookies");
    expect(result.request).not.toHaveProperty("data");
    expect(result.request?.headers).toBeUndefined();
  });

  it("redacts emails in the event message", () => {
    const event = {
      message: "failed to load profile for someone@waiwai.is",
    } as ErrorEvent;

    const result = scrubEvent(event);

    expect(result.message).toBe("failed to load profile for [redacted-email]");
  });

  it("redacts emails in exception values and skips entries without a value", () => {
    const event = {
      exception: {
        values: [
          { type: "Error", value: "contact admin@wai.computer for help" },
          { type: "TypeError" },
        ],
      },
    } as unknown as ErrorEvent;

    const result = scrubEvent(event);

    expect(result.exception?.values?.[0].value).toBe(
      "contact [redacted-email] for help",
    );
    expect(result.exception?.values?.[1].value).toBeUndefined();
  });

  it("tolerates a missing exception block via the nullish fallback", () => {
    const event = { message: "no@exception.here" } as ErrorEvent;

    expect(() => scrubEvent(event)).not.toThrow();
    expect(scrubEvent({ message: "no@exception.here" } as ErrorEvent).message).toBe(
      "[redacted-email]",
    );
  });

  it("runs each breadcrumb through scrubBreadcrumb", () => {
    const event = {
      breadcrumbs: [
        { data: { url: "https://wai.computer/a?secret=1" } },
        { message: "user x@y.com clicked" },
      ],
    } as unknown as ErrorEvent;

    const result = scrubEvent(event);

    expect(result.breadcrumbs?.[0].data?.url).toBe("https://wai.computer/a");
    expect(result.breadcrumbs?.[1].message).toBe("user [redacted-email] clicked");
  });

  it("returns the event unchanged when there is nothing sensitive to scrub", () => {
    const event = {} as ErrorEvent;
    const result = scrubEvent(event);

    expect(result).toBe(event);
    expect(result.request).toBeUndefined();
    expect(result.breadcrumbs).toBeUndefined();
  });
});
