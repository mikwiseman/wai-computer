import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { McpConnectionsList } from "./McpConnectionsList";
import { listMcpConnections, revokeMcpConnection } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  listMcpConnections: vi.fn(),
  revokeMcpConnection: vi.fn(),
}));

const mockedList = vi.mocked(listMcpConnections);
const mockedRevoke = vi.mocked(revokeMcpConnection);

const sample = [
  {
    client_id: "bot-client",
    client_name: "Meeting Bot",
    client_uri: null,
    scopes: ["mcp:read"],
    approved_at: "2026-05-01T10:00:00Z",
    last_active_at: "2026-05-19T08:30:00Z",
  },
];

describe("McpConnectionsList", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("lists connected clients returned by the API", async () => {
    mockedList.mockResolvedValue(sample);
    render(<McpConnectionsList />);
    expect(await screen.findByTestId("mcp-connection-bot-client")).toBeTruthy();
    expect(screen.getByText("Meeting Bot")).toBeTruthy();
    expect(screen.getByTestId("mcp-revoke-bot-client")).toBeTruthy();
  });

  it("shows an empty state when there are no connections", async () => {
    mockedList.mockResolvedValue([]);
    render(<McpConnectionsList />);
    expect(await screen.findByTestId("mcp-connections-empty")).toBeTruthy();
  });

  it("revokes a client and removes it from the list", async () => {
    mockedList.mockResolvedValue(sample);
    mockedRevoke.mockResolvedValue(undefined);
    render(<McpConnectionsList />);

    fireEvent.click(await screen.findByTestId("mcp-revoke-bot-client"));

    await waitFor(() => {
      expect(mockedRevoke).toHaveBeenCalledWith("bot-client");
    });
    await waitFor(() => {
      expect(screen.queryByTestId("mcp-connection-bot-client")).toBeNull();
    });
    expect(screen.getByTestId("mcp-connections-empty")).toBeTruthy();
  });

  it("surfaces an error when loading fails", async () => {
    mockedList.mockRejectedValue(new Error("Your session ended. Please sign in again."));
    render(<McpConnectionsList />);
    const alert = await screen.findByTestId("mcp-connections-error");
    expect(alert.textContent).toContain("session ended");
  });
});
