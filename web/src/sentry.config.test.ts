import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const originalDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
const originalEnv = process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT;
const originalNodeEnv = process.env.NODE_ENV;

afterEach(() => {
  if (originalDsn === undefined) {
    delete process.env.NEXT_PUBLIC_SENTRY_DSN;
  } else {
    process.env.NEXT_PUBLIC_SENTRY_DSN = originalDsn;
  }
  if (originalEnv === undefined) {
    delete process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT;
  } else {
    process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT = originalEnv;
  }
  process.env.NODE_ENV = originalNodeEnv;
  vi.resetModules();
  vi.clearAllMocks();
});

describe("sentry.server.config", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("init runs even without a DSN (no-ops gracefully)", async () => {
    delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    const initSpy = vi.fn();
    vi.doMock("@sentry/nextjs", () => ({
      init: initSpy,
      captureRequestError: vi.fn(),
      captureRouterTransitionStart: vi.fn(),
      replayIntegration: vi.fn(() => ({ name: "replay" })),
    }));

    await import("./sentry.server.config");
    expect(initSpy).toHaveBeenCalledTimes(1);
    const cfg = initSpy.mock.calls[0][0] as { dsn: string; environment: string };
    expect(cfg.dsn).toBe("");
    // Without NEXT_PUBLIC_SENTRY_ENVIRONMENT, falls back based on NODE_ENV. In test
    // runs Vitest leaves NODE_ENV === "test", so we just assert it's a non-empty string.
    expect(typeof cfg.environment).toBe("string");
    expect(cfg.environment.length).toBeGreaterThan(0);
  });

  it("forwards an explicit DSN + environment when present", async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = "https://abc@o1.ingest.us.sentry.io/2";
    process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT = "staging";
    const initSpy = vi.fn();
    vi.doMock("@sentry/nextjs", () => ({
      init: initSpy,
      captureRequestError: vi.fn(),
      captureRouterTransitionStart: vi.fn(),
      replayIntegration: vi.fn(() => ({ name: "replay" })),
    }));

    await import("./sentry.server.config");
    const cfg = initSpy.mock.calls[0][0] as { dsn: string; environment: string };
    expect(cfg.dsn).toBe("https://abc@o1.ingest.us.sentry.io/2");
    expect(cfg.environment).toBe("staging");
  });
});

describe("sentry.edge.config", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("init runs even without a DSN", async () => {
    delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    const initSpy = vi.fn();
    vi.doMock("@sentry/nextjs", () => ({
      init: initSpy,
      captureRequestError: vi.fn(),
      captureRouterTransitionStart: vi.fn(),
      replayIntegration: vi.fn(() => ({ name: "replay" })),
    }));

    await import("./sentry.edge.config");
    expect(initSpy).toHaveBeenCalledTimes(1);
    expect((initSpy.mock.calls[0][0] as { dsn: string }).dsn).toBe("");
  });
});
