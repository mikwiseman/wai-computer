import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { McpSourcesPanel } from "./McpSourcesPanel";

const mockList = vi.fn();
const mockCreate = vi.fn();
const mockUpdate = vi.fn();
const mockSync = vi.fn();

vi.mock("@/lib/api", () => ({
  listMcpIngestionConnections: (...a: unknown[]) => mockList(...a),
  createMcpIngestionConnection: (...a: unknown[]) => mockCreate(...a),
  updateMcpIngestionConnection: (...a: unknown[]) => mockUpdate(...a),
  syncMcpIngestionConnection: (...a: unknown[]) => mockSync(...a),
}));

function source(overrides = {}) {
  return {
    id: "s1",
    server_label: "Notion",
    server_url: "https://notion/mcp",
    transport: "http",
    auth_type: "bearer",
    has_token: true,
    allowed_tools: null,
    capabilities: null,
    privacy_level: "private",
    sync_interval_minutes: 60,
    status: "idle",
    enabled: true,
    last_sync_at: null,
    last_error: null,
    created_at: "2026-06-02T00:00:00Z",
    ...overrides,
  };
}

describe("McpSourcesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue([]);
    mockCreate.mockResolvedValue(source());
    mockUpdate.mockResolvedValue(source({ enabled: false }));
    mockSync.mockResolvedValue({ status: "queued" });
  });

  it("shows the empty state when no sources are connected", async () => {
    render(<McpSourcesPanel />);
    expect(await screen.findByTestId("mcp-sources-empty")).toBeInTheDocument();
  });

  it("connects a source from the form (derives bearer auth from a token)", async () => {
    render(<McpSourcesPanel />);
    await screen.findByTestId("mcp-sources-empty");
    fireEvent.change(screen.getByLabelText("Source name"), {
      target: { value: "Notion" },
    });
    fireEvent.change(screen.getByLabelText("Server URL"), {
      target: { value: "https://notion/mcp" },
    });
    fireEvent.change(screen.getByLabelText("Auth token (optional)"), {
      target: { value: "tok" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Connect/ }));
    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        server_label: "Notion",
        server_url: "https://notion/mcp",
        auth_token: "tok",
        auth_type: "bearer",
      }),
    );
  });

  it("lists sources and pauses one", async () => {
    mockList.mockResolvedValue([source()]);
    render(<McpSourcesPanel />);
    await waitFor(() => expect(screen.getByText("Notion")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("s1", { enabled: false }),
    );
  });

  it("triggers a manual sync", async () => {
    mockList.mockResolvedValue([source()]);
    render(<McpSourcesPanel />);
    await waitFor(() => expect(screen.getByText("Notion")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Sync" }));
    await waitFor(() => expect(mockSync).toHaveBeenCalledWith("s1"));
  });

  it("surfaces a load error", async () => {
    mockList.mockRejectedValue(new Error("nope"));
    render(<McpSourcesPanel />);
    expect(await screen.findByTestId("mcp-sources-error")).toHaveTextContent("nope");
  });
});
