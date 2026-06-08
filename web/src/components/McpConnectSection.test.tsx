import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { McpConnectSection } from "./McpConnectSection";

const mockGetSystemInfo = vi.fn();

vi.mock("@/lib/api", () => ({
  getSystemInfo: (...args: unknown[]) => mockGetSystemInfo(...args),
  listMcpConnections: vi.fn().mockResolvedValue([]),
  revokeMcpConnection: vi.fn(),
}));

let clipboardWriteText: ReturnType<typeof vi.fn<(data: string) => Promise<void>>>;
const cloudSystemInfo = {
  app_name: "WaiComputer",
  deployment_mode: "wai_cloud",
  public_base_url: "https://wai.computer",
  cloud_base_url: "https://wai.computer",
  mcp_url: "https://wai.computer/mcp",
  git_sha: null,
  git_dirty: false,
  audio_retention_policy: "delete_after_processing",
  self_hosting_available: true,
  billing_mode: "cloud",
};

describe("McpConnectSection", () => {
  beforeEach(() => {
    mockGetSystemInfo.mockResolvedValue(cloudSystemInfo);
    clipboardWriteText = vi.fn<(data: string) => Promise<void>>().mockResolvedValue(undefined);
    if (!navigator.clipboard) {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText: clipboardWriteText },
      });
    } else {
      vi.spyOn(navigator.clipboard, "writeText").mockImplementation(clipboardWriteText);
    }
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("renders the canonical production MCP endpoint URL", async () => {
    render(<McpConnectSection />);
    const url = screen.getByTestId("mcp-endpoint-url");
    await waitFor(() => expect(url.textContent).toBe("https://wai.computer/mcp"));
  });

  it("renders the MCP endpoint returned by this server", async () => {
    mockGetSystemInfo.mockResolvedValue({
      ...cloudSystemInfo,
      deployment_mode: "self_host",
      public_base_url: "https://demo.self.example",
      mcp_url: "https://demo.self.example/mcp",
      billing_mode: "self_host",
    });

    render(<McpConnectSection />);

    await waitFor(() => {
      expect(screen.getByTestId("mcp-endpoint-url").textContent).toBe(
        "https://demo.self.example/mcp",
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: "Cursor" }));
    const snippet = screen.getByText(/"mcpServers"/);
    expect(snippet.textContent).toContain("https://demo.self.example/mcp");
  });

  it("defaults to the OpenClaw guide with the connect command", async () => {
    render(<McpConnectSection />);
    await screen.findByText("https://wai.computer/mcp");
    expect(screen.getByTestId("mcp-guide-openclaw")).toBeTruthy();
    const snippet = screen.getByText(/openclaw mcp add waicomputer/);
    expect(snippet.textContent).toContain("https://wai.computer/mcp");
    expect(snippet.textContent).toContain("--auth oauth");
  });

  it("offers a Hermes config snippet for the memory bank", async () => {
    render(<McpConnectSection />);
    await screen.findByText("https://wai.computer/mcp");
    fireEvent.click(screen.getByRole("tab", { name: "Hermes" }));
    expect(screen.getByTestId("mcp-guide-hermes")).toBeTruthy();
    const snippet = screen.getByText(/mcp_servers:/);
    expect(snippet.textContent).toContain("https://wai.computer/mcp");
  });

  it("still exposes the Claude.ai connector link", async () => {
    render(<McpConnectSection />);
    await screen.findByText("https://wai.computer/mcp");
    fireEvent.click(screen.getByRole("tab", { name: "Claude.ai" }));
    expect(screen.getByTestId("mcp-guide-claudeai")).toBeTruthy();
    const link = screen.getByRole("link", { name: /Open Connectors in Claude\.ai/i }) as HTMLAnchorElement;
    expect(link.href).toBe("https://claude.ai/customize/connectors");
    expect(link.target).toBe("_blank");
  });

  it("switches to the Cursor guide and shows the JSON snippet", async () => {
    render(<McpConnectSection />);
    await screen.findByText("https://wai.computer/mcp");
    fireEvent.click(screen.getByRole("tab", { name: "Cursor" }));
    expect(screen.getByTestId("mcp-guide-cursor")).toBeTruthy();
    const snippet = screen.getByText(/"mcpServers"/);
    expect(snippet.textContent).toContain("https://wai.computer/mcp");
  });

  it("copies the endpoint URL to the clipboard and shows confirmation", async () => {
    render(<McpConnectSection />);
    await screen.findByText("https://wai.computer/mcp");
    fireEvent.click(screen.getByTestId("mcp-copy-endpoint"));
    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenCalledWith("https://wai.computer/mcp");
    });
    expect(screen.getByTestId("mcp-copy-endpoint").textContent).toBe("Copied");
  });

  it("copies the active client snippet when present", async () => {
    render(<McpConnectSection />);
    await screen.findByText("https://wai.computer/mcp");
    fireEvent.click(screen.getByRole("tab", { name: "Codex CLI" }));
    fireEvent.click(screen.getByTestId("mcp-copy-snippet"));
    await waitFor(() => {
      const lastCall = clipboardWriteText.mock.calls.at(-1);
      expect(lastCall?.[0]).toContain("codex mcp add waicomputer --url https://wai.computer/mcp");
    });
  });

  it("uses --transport http in the Claude Code CLI snippet so it is treated as HTTP, not stdio", async () => {
    render(<McpConnectSection />);
    await screen.findByText("https://wai.computer/mcp");
    fireEvent.click(screen.getByRole("tab", { name: "Claude Code" }));
    fireEvent.click(screen.getByTestId("mcp-copy-snippet"));
    await waitFor(() => {
      const lastCall = clipboardWriteText.mock.calls.at(-1);
      expect(lastCall?.[0]).toContain("claude mcp add --transport http waicomputer https://wai.computer/mcp");
    });
  });

  it("documents the headless bot recipe: API token via Bearer on REST + MCP", () => {
    render(<McpConnectSection />);
    fireEvent.click(screen.getByRole("tab", { name: "Custom / bot" }));
    const guide = screen.getByTestId("mcp-guide-bot");
    expect(guide.textContent).toMatch(/API token/i);
    expect(guide.textContent).toMatch(/Bearer/);
  });
});
