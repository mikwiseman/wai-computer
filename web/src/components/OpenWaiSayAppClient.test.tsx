import type React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildWaiSayAppUrl, normalizeWaiSayAppClient } from "@/lib/app-client";
import { OpenWaiSayAppClient } from "./OpenWaiSayAppClient";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

describe("OpenWaiSayAppClient", () => {
  it("builds platform-specific app URLs", () => {
    expect(buildWaiSayAppUrl("abc 123", "macos")).toBe("waisay://auth/verify?token=abc+123");
    expect(buildWaiSayAppUrl("abc 123", "ios")).toBe("waisay://auth/verify?token=abc+123");
    expect(buildWaiSayAppUrl("abc 123", "android")).toBe("waisay://magic?token=abc+123");
  });

  it("rejects unknown app clients", () => {
    expect(normalizeWaiSayAppClient("android")).toBe("android");
    expect(normalizeWaiSayAppClient("ios")).toBe("ios");
    expect(normalizeWaiSayAppClient("macos")).toBe("macos");
    expect(normalizeWaiSayAppClient("unknown")).toBeNull();
    expect(normalizeWaiSayAppClient(null)).toBeNull();
  });

  it("renders app-open and browser fallback links", () => {
    render(<OpenWaiSayAppClient token="token-123" client="macos" autoOpen={false} />);

    expect(screen.getByTestId("open-app-message")).toHaveTextContent("Opening WaiSay.");
    expect(screen.getByTestId("open-app-link")).toHaveAttribute(
      "href",
      "waisay://auth/verify?token=token-123",
    );
    expect(screen.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=token-123",
    );
  });

  it("shows missing-token state", () => {
    render(<OpenWaiSayAppClient token={null} client="macos" autoOpen={false} />);

    expect(screen.getByTestId("open-app-message")).toHaveTextContent("Missing token.");
    expect(screen.getByRole("link", { name: "Back to login" })).toHaveAttribute("href", "/login");
  });

  it("shows invalid-client state with browser fallback", () => {
    render(<OpenWaiSayAppClient token="token-123" client={null} autoOpen={false} />);

    expect(screen.getByTestId("open-app-message")).toHaveTextContent("not valid");
    expect(screen.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=token-123",
    );
  });
});
