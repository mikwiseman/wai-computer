import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeleteAccountSection } from "./DeleteAccountSection";

vi.mock("@/lib/api", () => ({ deleteAccount: vi.fn() }));
const { deleteAccount } = await import("@/lib/api");
const mockDeleteAccount = vi.mocked(deleteAccount);

describe("DeleteAccountSection", () => {
  beforeEach(() => mockDeleteAccount.mockReset());

  it("renders the danger zone with no modal initially", () => {
    render(<DeleteAccountSection onDeleted={() => {}} />);
    expect(screen.getByText("Danger zone")).toBeTruthy();
    expect(screen.getByTestId("delete-account")).toBeTruthy();
    expect(screen.queryByTestId("confirm-delete-account")).toBeNull();
  });

  it("opens a confirm modal and deletes on confirm", async () => {
    mockDeleteAccount.mockResolvedValue({ message: "Account deleted" });
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    render(<DeleteAccountSection onDeleted={onDeleted} />);

    await user.click(screen.getByTestId("delete-account"));
    expect(screen.getByTestId("confirm-delete-account")).toBeTruthy();
    await user.click(screen.getByTestId("confirm-delete-account-action"));

    await waitFor(() => expect(mockDeleteAccount).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
  });

  it("cancel closes the modal without deleting", async () => {
    const user = userEvent.setup();
    render(<DeleteAccountSection onDeleted={() => {}} />);
    await user.click(screen.getByTestId("delete-account"));
    await user.click(screen.getByText("Cancel"));
    expect(screen.queryByTestId("confirm-delete-account")).toBeNull();
    expect(mockDeleteAccount).not.toHaveBeenCalled();
  });
});
