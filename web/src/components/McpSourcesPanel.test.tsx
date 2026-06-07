import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { McpSourcesPanel } from "./McpSourcesPanel";

const mockCatalog = vi.fn();
const mockList = vi.fn();
const mockCreate = vi.fn();
const mockUpdate = vi.fn();
const mockSync = vi.fn();
const mockDelete = vi.fn();

vi.mock("@/lib/api", () => ({
  getSourceCatalog: (...a: unknown[]) => mockCatalog(...a),
  listMcpIngestionConnections: (...a: unknown[]) => mockList(...a),
  createMcpIngestionConnection: (...a: unknown[]) => mockCreate(...a),
  updateMcpIngestionConnection: (...a: unknown[]) => mockUpdate(...a),
  syncMcpIngestionConnection: (...a: unknown[]) => mockSync(...a),
  deleteMcpIngestionConnection: (...a: unknown[]) => mockDelete(...a),
}));

function catalog() {
  return {
    version: 1,
    custom_supported: true,
    backfill_depths: ["recent_90d", "everything"],
    default_backfill_depth: "recent_90d",
    categories: [{ id: "notes", name_en: "Notes & docs", name_ru: "Заметки" }],
    entries: [
      {
        id: "notion", name: "Notion", category: "notes", icon: "notion",
        tagline_en: "Pages", tagline_ru: "Страницы", syncs_en: "", syncs_ru: "",
        auth_type: "none", server_url: "https://mcp.notion.com/mcp",
        transport: "streamable_http", default_sync_interval_minutes: 120,
        setup_hint_en: null, setup_hint_ru: null, status: "available",
      },
      {
        id: "gmail", name: "Gmail", category: "notes", icon: "gmail",
        tagline_en: "Email", tagline_ru: "Почта", syncs_en: "", syncs_ru: "",
        auth_type: "oauth", server_url: "https://x/mcp", transport: "streamable_http",
        default_sync_interval_minutes: 60, setup_hint_en: null, setup_hint_ru: null,
        status: "coming_soon",
      },
    ],
  };
}

function source(overrides = {}) {
  return {
    id: "s1", server_label: "My Server", server_url: "https://srv/mcp",
    transport: "streamable_http", auth_type: "pat", has_token: true,
    allowed_tools: null, capabilities: null, privacy_level: "internal",
    sync_interval_minutes: 60, status: "active", enabled: true,
    last_sync_at: "2026-06-07T00:00:00Z", last_error: null,
    created_at: "2026-06-02T00:00:00Z", catalog_id: null, source_type: null,
    backfill_depth: null, item_count: 12, ...overrides,
  };
}

describe("McpSourcesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCatalog.mockResolvedValue(catalog());
    mockList.mockResolvedValue([]);
    mockCreate.mockResolvedValue(source());
    mockUpdate.mockResolvedValue(source({ enabled: false }));
    mockSync.mockResolvedValue({ status: "queued" });
    mockDelete.mockResolvedValue(undefined);
  });

  it("renders the catalog with available and coming-soon tiles", async () => {
    render(<McpSourcesPanel />);
    expect(await screen.findByTestId("mcp-tile-notion")).toBeInTheDocument();
    const gmail = screen.getByTestId("mcp-tile-gmail");
    expect(within(gmail).getByText("Soon")).toBeInTheDocument();
  });

  it("connects an available tile by catalog_id", async () => {
    render(<McpSourcesPanel />);
    const tile = await screen.findByTestId("mcp-tile-notion");
    fireEvent.click(within(tile).getByRole("button", { name: /Connect/ }));
    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        catalog_id: "notion",
        auth_token: null,
        backfill_depth: "recent_90d",
      }),
    );
    await waitFor(() => expect(mockSync).toHaveBeenCalledWith("s1"));
  });

  it("connects a custom source with pat auth (not the old invalid 'bearer')", async () => {
    render(<McpSourcesPanel />);
    fireEvent.click(await screen.findByTestId("mcp-custom-toggle"));
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "Mine" } });
    fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: "https://srv/mcp" } });
    fireEvent.change(screen.getByLabelText("Auth token (optional)"), { target: { value: "tok" } });
    fireEvent.click(screen.getByTestId("mcp-custom-submit"));
    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        server_label: "Mine",
        server_url: "https://srv/mcp",
        auth_type: "pat",
        auth_token: "tok",
        backfill_depth: "recent_90d",
      }),
    );
  });

  it("lists a connected source and pauses it", async () => {
    mockList.mockResolvedValue([source({ id: "s1", server_label: "My Server" })]);
    render(<McpSourcesPanel />);
    const row = await screen.findByTestId("mcp-source-s1");
    expect(within(row).getByText(/Synced 12/)).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith("s1", { enabled: false }));
  });

  it("surfaces a load error", async () => {
    mockList.mockRejectedValue(new Error("nope"));
    render(<McpSourcesPanel />);
    expect(await screen.findByTestId("mcp-sources-error")).toHaveTextContent("nope");
  });
});
