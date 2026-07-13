import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ApiKeysSection } from "./ApiKeysSection";
import { createApiKey, listApiKeys, revokeApiKey } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  listApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}));

const mockedList = vi.mocked(listApiKeys);
const mockedCreate = vi.mocked(createApiKey);
const mockedRevoke = vi.mocked(revokeApiKey);

const sampleKey = {
  id: "key-1",
  name: "meeting-collector",
  prefix: "wc_live_ab12",
  last4: "wxyz",
  scopes: ["read"],
  last_used_at: null,
  expires_at: null,
  created_at: "2026-05-20T10:00:00Z",
};

describe("ApiKeysSection", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("lists existing tokens without the secret", async () => {
    mockedList.mockResolvedValue([sampleKey]);
    render(<ApiKeysSection />);
    expect(await screen.findByTestId("api-key-key-1")).toBeTruthy();
    expect(screen.getByText("meeting-collector")).toBeTruthy();
  });

  it("shows an empty state when there are no tokens", async () => {
    mockedList.mockResolvedValue([]);
    render(<ApiKeysSection />);
    expect(await screen.findByTestId("api-keys-empty")).toBeTruthy();
  });

  it("creates a token and reveals the plaintext once", async () => {
    mockedList.mockResolvedValue([]);
    mockedCreate.mockResolvedValue({ ...sampleKey, token: "wc_live_secret-value" });
    render(<ApiKeysSection />);
    await screen.findByTestId("api-keys-empty");

    fireEvent.change(screen.getByTestId("api-key-name-input"), {
      target: { value: "meeting-collector" },
    });
    fireEvent.click(screen.getByTestId("api-key-create"));

    await waitFor(() => {
      expect(mockedCreate).toHaveBeenCalledWith("meeting-collector", { allowMemoryWrite: false });
    });
    const reveal = await screen.findByTestId("api-key-created-token");
    expect(reveal.textContent).toContain("wc_live_secret-value");
    expect(screen.getByTestId("api-key-key-1")).toBeTruthy();
  });

  it("opts into memory write when the toggle is checked", async () => {
    mockedList.mockResolvedValue([]);
    mockedCreate.mockResolvedValue({
      ...sampleKey,
      scopes: ["read", "memory:write"],
      token: "wc_live_secret-value",
    });
    render(<ApiKeysSection />);
    await screen.findByTestId("api-keys-empty");

    fireEvent.change(screen.getByTestId("api-key-name-input"), {
      target: { value: "openclaw-agent" },
    });
    fireEvent.click(screen.getByTestId("api-key-allow-write").querySelector("input")!);
    fireEvent.click(screen.getByTestId("api-key-create"));

    await waitFor(() => {
      expect(mockedCreate).toHaveBeenCalledWith("openclaw-agent", { allowMemoryWrite: true });
    });
    expect(screen.getByTestId("api-key-write-badge-key-1")).toBeTruthy();
  });

  it("revokes a token and removes it from the list", async () => {
    mockedList.mockResolvedValue([sampleKey]);
    mockedRevoke.mockResolvedValue(undefined);
    render(<ApiKeysSection />);
    fireEvent.click(await screen.findByTestId("api-key-revoke-key-1"));
    // Revoking is destructive for live integrations — it now takes a confirm.
    fireEvent.click(await screen.findByTestId("api-key-revoke-confirm-key-1"));
    await waitFor(() => {
      expect(mockedRevoke).toHaveBeenCalledWith("key-1");
    });
    await waitFor(() => {
      expect(screen.queryByTestId("api-key-key-1")).toBeNull();
    });
  });

  it("surfaces an error when loading fails", async () => {
    mockedList.mockRejectedValue(new Error("Your session ended. Please sign in again."));
    render(<ApiKeysSection />);
    const alert = await screen.findByTestId("api-keys-error");
    expect(alert.textContent).toContain("session ended");
  });
});
