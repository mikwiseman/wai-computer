import type React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { AuthForm } from "./AuthForm";

const mockLogin = vi.fn();
const mockRequestMagicLink = vi.fn();
const mockRequestPasswordReset = vi.fn();
const mockStartTelegramAuth = vi.fn();
const mockGetTelegramAuthStatus = vi.fn();

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  login: (...args: unknown[]) => mockLogin(...args),
  requestMagicLink: (...args: unknown[]) => mockRequestMagicLink(...args),
  requestPasswordReset: (...args: unknown[]) => mockRequestPasswordReset(...args),
  startTelegramAuth: (...args: unknown[]) => mockStartTelegramAuth(...args),
  getTelegramAuthStatus: (...args: unknown[]) => mockGetTelegramAuthStatus(...args),
}));

describe("AuthForm", () => {
  beforeEach(() => {
    mockLogin.mockReset();
    mockRequestMagicLink.mockReset();
    mockRequestPasswordReset.mockReset();
    mockStartTelegramAuth.mockReset();
    mockGetTelegramAuthStatus.mockReset();
    setNavigatorLanguages(["en-US"]);
    vi.stubGlobal("open", vi.fn());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function setNavigatorLanguages(languages: string[], language = languages[0] ?? "en-US") {
    Object.defineProperty(window.navigator, "languages", {
      configurable: true,
      value: languages,
    });
    Object.defineProperty(window.navigator, "language", {
      configurable: true,
      value: language,
    });
  }

  it("shows one account gateway instead of login and register modes", () => {
    render(<AuthForm mode="login" onSuccess={vi.fn()} />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Start anywhere. Continue everywhere.",
    );
    expect(
      screen.getByText(
        "One account. Web, Mac, Telegram. Sign in or sign up automatically.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Your second brain")).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Already have an account? We’ll sign you in. New here? We’ll create one.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("One account. Web, Mac and Telegram.")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Sign in$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Create account$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByTestId("legal-consent-checkbox")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Get the Mac app" })).toHaveAttribute(
      "href",
      "/releases/macos/WaiComputer-latest.dmg",
    );
    expect(screen.queryByRole("link", { name: "Start in Telegram" })).not.toBeInTheDocument();
  });

  it("uses one legal, passwordless email flow for returning and new users", async () => {
    const user = userEvent.setup();
    mockRequestMagicLink.mockResolvedValue({ message: "Magic link sent" });

    render(<AuthForm mode="register" onSuccess={vi.fn()} />);

    await user.type(screen.getByTestId("auth-email"), "person@example.com");
    await user.click(screen.getByTestId("magic-link-button"));
    expect(await screen.findByTestId("auth-message")).toHaveTextContent(
      "Accept the Terms of Service",
    );
    expect(mockRequestMagicLink).not.toHaveBeenCalled();
    await user.click(screen.getByTestId("legal-consent-checkbox"));
    await user.click(screen.getByTestId("magic-link-button"));

    await waitFor(() => {
      expect(mockRequestMagicLink).toHaveBeenCalledWith("person@example.com", {
        locale: "en",
        region: "global",
        acceptedLegalTerms: true,
      });
    });
    expect(await screen.findByTestId("magic-link-sent")).toHaveTextContent(
      "person@example.com",
    );
  });

  it("keeps password sign-in as a quiet secondary recovery path", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    mockLogin.mockResolvedValue({ access_token: "token", token_type: "bearer" });

    render(<AuthForm mode="login" onSuccess={onSuccess} />);

    await user.type(screen.getByTestId("auth-email"), "person@example.com");
    await user.click(screen.getByTestId("password-mode-button"));
    await user.type(screen.getByTestId("auth-password"), "password123");
    await user.click(screen.getByTestId("auth-submit"));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("person@example.com", "password123", {
        locale: "en",
        region: "global",
      });
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("opens Telegram and finishes when the approved ticket is polled", async () => {
    vi.useFakeTimers();
    const onSuccess = vi.fn();
    mockStartTelegramAuth.mockResolvedValue({
      status: "pending",
      bot_username: "waicomputer_bot",
      deep_link: "tg://resolve?domain=waicomputer_bot&start=auth_start",
      web_link: "https://t.me/waicomputer_bot?start=auth_start",
      ticket: "poll-secret",
      expires_at: "2026-07-15T12:10:00Z",
    });
    mockGetTelegramAuthStatus
      .mockResolvedValueOnce({ status: "pending" })
      .mockResolvedValueOnce({
        status: "approved",
        access_token: "access",
        refresh_token: "refresh",
        token_type: "bearer",
    });

    render(<AuthForm mode="login" onSuccess={onSuccess} />);
    await act(async () => {
      screen.getByTestId("telegram-auth-button").click();
      await Promise.resolve();
    });
    expect(mockStartTelegramAuth).toHaveBeenCalledWith({ client: "web", locale: "en" });
    expect(window.open).toHaveBeenCalledWith(
      "https://t.me/waicomputer_bot?start=auth_start",
      "_blank",
      "noopener,noreferrer",
    );
    expect(screen.getByTestId("telegram-auth-status")).toHaveTextContent(
      "Press Start in Telegram",
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(mockGetTelegramAuthStatus).toHaveBeenCalledWith("poll-secret");
    expect(onSuccess).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("uses concise Russian copy and locale", async () => {
    const user = userEvent.setup();
    mockRequestMagicLink.mockResolvedValue({ message: "Отправлено" });
    render(<AuthForm mode="login" initialLocale="ru" onSuccess={vi.fn()} />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Начни где удобно. Продолжай везде.",
    );
    expect(screen.getByTestId("telegram-auth-button")).toHaveTextContent(
      "Продолжить через Telegram",
    );

    await user.type(screen.getByTestId("auth-email"), "ru@example.com");
    await user.click(screen.getByTestId("legal-consent-checkbox"));
    await user.click(screen.getByTestId("magic-link-button"));
    await waitFor(() => {
      expect(mockRequestMagicLink).toHaveBeenCalledWith("ru@example.com", {
        locale: "ru",
        region: "ru",
        acceptedLegalTerms: true,
      });
    });
  });

  it("surfaces email and Telegram errors without silent degradation", async () => {
    const user = userEvent.setup();
    mockRequestMagicLink.mockRejectedValue(new ApiError(502, "Email unavailable"));
    mockStartTelegramAuth.mockRejectedValue(new Error("Telegram unavailable"));

    render(<AuthForm mode="login" onSuccess={vi.fn()} />);
    await user.type(screen.getByTestId("auth-email"), "error@example.com");
    await user.click(screen.getByTestId("legal-consent-checkbox"));
    await user.click(screen.getByTestId("magic-link-button"));
    expect(await screen.findByTestId("auth-message")).toHaveTextContent("Email unavailable");

    await user.click(screen.getByTestId("telegram-auth-button"));
    expect(await screen.findByTestId("auth-message")).toHaveTextContent(
      "Telegram unavailable",
    );
  });
});
