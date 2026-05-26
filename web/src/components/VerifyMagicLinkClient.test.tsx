import type React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { VerifyMagicLinkClient } from "./VerifyMagicLinkClient";

const mockVerifyMagicLink = vi.fn();
const mockReplace = vi.fn();
let localStorageValues: Record<string, string>;

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

vi.mock("@/lib/api", () => ({
  verifyMagicLink: (...args: unknown[]) => mockVerifyMagicLink(...args),
}));

describe("VerifyMagicLinkClient", () => {
  beforeEach(() => {
    mockVerifyMagicLink.mockReset();
    mockReplace.mockReset();
    setNavigatorLanguages(["en-US"]);
    localStorageValues = {};
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => localStorageValues[key] ?? null),
        setItem: vi.fn((key: string, value: string) => {
          localStorageValues[key] = value;
        }),
        clear: vi.fn(() => {
          localStorageValues = {};
        }),
      },
    });
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

  it("shows missing token state and does not verify", () => {
    render(<VerifyMagicLinkClient token={null} />);
    expect(screen.getByTestId("verify-message")).toHaveTextContent("Missing token.");
    expect(mockVerifyMagicLink).not.toHaveBeenCalled();
  });

  it("verifies token and redirects new users to onboarding", async () => {
    mockVerifyMagicLink.mockResolvedValue({ access_token: "token", token_type: "bearer" });
    render(<VerifyMagicLinkClient token="token-123" />);

    await waitFor(() => {
      expect(mockVerifyMagicLink).toHaveBeenCalledWith("token-123", { locale: "en" });
      expect(mockReplace).toHaveBeenCalledWith("/onboarding");
    });

    expect(screen.getByTestId("verify-message")).toHaveTextContent("Magic link verified. Redirecting...");
  });

  it("redirects onboarded users to dashboard", async () => {
    window.localStorage.setItem("voice_onboarding_complete", "true");
    mockVerifyMagicLink.mockResolvedValue({ access_token: "token", token_type: "bearer" });
    render(<VerifyMagicLinkClient token="token-123" />);

    await waitFor(() => {
      expect(mockVerifyMagicLink).toHaveBeenCalledWith("token-123", { locale: "en" });
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });

    expect(screen.getByTestId("verify-message")).toHaveTextContent("Magic link verified. Redirecting...");
  });

  it("renders ApiError failure state", async () => {
    mockVerifyMagicLink.mockRejectedValueOnce(new ApiError(401, "Token expired"));
    render(<VerifyMagicLinkClient token="token-err-1" />);

    await waitFor(() => {
      expect(screen.getByTestId("verify-message")).toHaveTextContent("Token expired");
    });
  });

  it("renders generic failure state", async () => {
    mockVerifyMagicLink.mockRejectedValueOnce(new Error("Other failure"));
    render(<VerifyMagicLinkClient token="token-err-2" />);

    await waitFor(() => {
      expect(screen.getByTestId("verify-message")).toHaveTextContent("Verification failed.");
    });
  });

  it("shows verifying message while token verification is in progress", () => {
    mockVerifyMagicLink.mockImplementation(
      () => new Promise(() => {}),
    );

    render(<VerifyMagicLinkClient token="pending-token" />);

    expect(screen.getByTestId("verify-message")).toHaveTextContent("Verifying token...");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Verifying sign-in link");
  });

  it("passes Russian locale and renders Russian chrome", async () => {
    mockVerifyMagicLink.mockRejectedValueOnce(new ApiError(401, "Недействительная ссылка для входа"));
    render(<VerifyMagicLinkClient token="ru-token" locale="ru" />);

    await waitFor(() => {
      expect(mockVerifyMagicLink).toHaveBeenCalledWith("ru-token", { locale: "ru" });
      expect(screen.getByTestId("verify-message")).toHaveTextContent("Недействительная ссылка для входа");
    });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Проверка ссылки для входа");
    expect(screen.getByRole("link", { name: "Вернуться ко входу" })).toHaveAttribute("href", "/login");
  });

  it("falls back to browser Russian locale when link locale is absent", async () => {
    setNavigatorLanguages(["ru-RU", "en-US"]);
    mockVerifyMagicLink.mockRejectedValueOnce(new ApiError(401, "Недействительная ссылка для входа"));

    render(<VerifyMagicLinkClient token="ru-browser-token" />);

    await waitFor(() => {
      expect(mockVerifyMagicLink).toHaveBeenCalledWith("ru-browser-token", { locale: "ru" });
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Проверка ссылки для входа");
    });
  });

  it("shows error message from ApiError and does not redirect", async () => {
    mockVerifyMagicLink.mockRejectedValue(new ApiError(400, "Invalid or expired link"));
    render(<VerifyMagicLinkClient token="bad-token" />);

    await waitFor(() => {
      expect(screen.getByTestId("verify-message")).toHaveTextContent("Invalid or expired link");
    });
    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Back to login" })).toHaveAttribute("href", "/login");
  });
});
