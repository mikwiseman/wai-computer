import type React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildWaiComputerAppUrl, normalizeWaiComputerAppClient } from "@/lib/app-client";
import { OpenWaiComputerAppClient } from "./OpenWaiComputerAppClient";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

describe("OpenWaiComputerAppClient", () => {
  it("builds platform-specific app URLs", () => {
    expect(buildWaiComputerAppUrl("abc 123", "macos")).toBe("waicomputer://auth/verify?token=abc+123");
    expect(buildWaiComputerAppUrl("abc 123", "ios")).toBe("waicomputer://auth/verify?token=abc+123");
    expect(buildWaiComputerAppUrl("abc 123", "android")).toBe("waicomputer://magic?token=abc+123");
  });

  it("rejects unknown app clients", () => {
    expect(normalizeWaiComputerAppClient("android")).toBe("android");
    expect(normalizeWaiComputerAppClient("ios")).toBe("ios");
    expect(normalizeWaiComputerAppClient("macos")).toBe("macos");
    expect(normalizeWaiComputerAppClient("unknown")).toBeNull();
    expect(normalizeWaiComputerAppClient(null)).toBeNull();
  });

  it("renders app-open and browser fallback links", () => {
    render(<OpenWaiComputerAppClient token="token-123" client="macos" autoOpen={false} />);

    expect(screen.getByTestId("open-app-message")).toHaveTextContent("Opening WaiComputer.");
    expect(screen.getByTestId("open-app-link")).toHaveAttribute(
      "href",
      "waicomputer://auth/verify?token=token-123",
    );
    expect(screen.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=token-123",
    );
  });

  it("shows missing-token state", () => {
    render(<OpenWaiComputerAppClient token={null} client="macos" autoOpen={false} />);

    expect(screen.getByTestId("open-app-message")).toHaveTextContent("Missing token.");
    expect(screen.getByRole("link", { name: "Back to login" })).toHaveAttribute("href", "/login");
  });

  it("shows invalid-client state with browser fallback", () => {
    render(<OpenWaiComputerAppClient token="token-123" client={null} autoOpen={false} />);

    expect(screen.getByTestId("open-app-message")).toHaveTextContent("not valid");
    expect(screen.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=token-123",
    );
  });
});
