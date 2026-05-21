import type React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ResetPasswordClient } from "./ResetPasswordClient";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

describe("ResetPasswordClient", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("posts reset token and localized password to the API", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ message: "ok" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ResetPasswordClient token="reset-token" locale="ru" />);

    await user.type(screen.getByTestId("reset-password"), "password123");
    await user.type(screen.getByTestId("reset-password-confirm"), "password123");
    await user.click(screen.getByTestId("reset-password-submit"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        cache: "no-store",
        body: JSON.stringify({
          token: "reset-token",
          password: "password123",
          locale: "ru",
        }),
      });
    });
    expect(screen.getByTestId("reset-password-message")).toHaveTextContent(
      "Пароль успешно сброшен",
    );
  });

  it("shows specific validation and API errors", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Password reset link expired" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ResetPasswordClient token="reset-token" />);

    await user.type(screen.getByTestId("reset-password"), "password123");
    await user.type(screen.getByTestId("reset-password-confirm"), "different123");
    await user.click(screen.getByTestId("reset-password-submit"));
    expect(screen.getByTestId("reset-password-message")).toHaveTextContent(
      "Passwords do not match.",
    );
    expect(fetchMock).not.toHaveBeenCalled();

    await user.clear(screen.getByTestId("reset-password-confirm"));
    await user.type(screen.getByTestId("reset-password-confirm"), "password123");
    await user.click(screen.getByTestId("reset-password-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("reset-password-message")).toHaveTextContent(
        "Password reset link expired",
      );
    });
  });
});
