import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createAdminPromoCode } from "@/lib/admin";
import { AdminPromoCodesClient } from "./AdminPromoCodesClient";

vi.mock("@/lib/admin", () => ({
  createAdminPromoCode: vi.fn(),
}));

const mockedCreateAdminPromoCode = vi.mocked(createAdminPromoCode);

describe("AdminPromoCodesClient", () => {
  beforeEach(() => {
    mockedCreateAdminPromoCode.mockReset();
  });

  it("creates promo codes through the admin API and shows plaintext once", async () => {
    mockedCreateAdminPromoCode.mockResolvedValue({
      code: "WAI-TEST-30",
      normalized_code: "WAITEST30",
      plan: "pro",
      billing_period: "month",
      duration_days: 30,
      max_redemptions: 10,
      redeemed_count: 0,
      active: true,
      expires_at: "2026-06-05T00:00:00Z",
      note: "test note",
    });

    render(<AdminPromoCodesClient />);

    await userEvent.type(screen.getByLabelText("Админ-пароль"), "secret");
    await userEvent.clear(screen.getByLabelText("Срок Pro, дней"));
    await userEvent.type(screen.getByLabelText("Срок Pro, дней"), "30");
    await userEvent.clear(screen.getByLabelText("Лимит активаций"));
    await userEvent.type(screen.getByLabelText("Лимит активаций"), "10");
    await userEvent.type(screen.getByLabelText("Заметка"), "test note");
    await userEvent.click(screen.getByRole("button", { name: "Сгенерировать" }));

    await waitFor(() =>
      expect(mockedCreateAdminPromoCode).toHaveBeenCalledWith({
        adminPassword: "secret",
        code: null,
        prefix: "WAI",
        plan: "pro",
        billing_period: "month",
        duration_days: 30,
        max_redemptions: 10,
        expires_days: 30,
        note: "test note",
      }),
    );
    expect(await screen.findByText("WAI-TEST-30")).toBeInTheDocument();
    expect(screen.getByText("Показывается один раз. В базе хранится только хэш.")).toBeInTheDocument();
  });

  it("surfaces admin API errors without clearing the form", async () => {
    mockedCreateAdminPromoCode.mockRejectedValue(new Error("Incorrect admin password"));

    render(<AdminPromoCodesClient />);

    await userEvent.type(screen.getByLabelText("Админ-пароль"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Сгенерировать" }));

    expect(await screen.findByText("Incorrect admin password")).toBeInTheDocument();
    expect(screen.getByLabelText("Админ-пароль")).toHaveValue("wrong");
  });
});
