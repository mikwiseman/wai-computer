import type React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { VerifyMagicLinkClient } from "./VerifyMagicLinkClient";

const mockVerifyMagicLink = vi.fn();
const mockReplace = vi.fn();

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
  });

  it("shows missing token state and does not verify", () => {
    render(<VerifyMagicLinkClient token={null} />);
    expect(screen.getByTestId("verify-message")).toHaveTextContent("Missing token.");
    expect(mockVerifyMagicLink).not.toHaveBeenCalled();
  });

  it("verifies token and redirects on success", async () => {
    mockVerifyMagicLink.mockResolvedValue({ access_token: "token", token_type: "bearer" });
    render(<VerifyMagicLinkClient token="token-123" />);

    await waitFor(() => {
      expect(mockVerifyMagicLink).toHaveBeenCalledWith("token-123");
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
});
