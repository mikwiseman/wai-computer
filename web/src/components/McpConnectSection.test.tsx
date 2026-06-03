import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { McpConnectSection } from "./McpConnectSection";

vi.mock("@/lib/api", () => ({
  listMcpConnections: vi.fn().mockResolvedValue([]),
  revokeMcpConnection: vi.fn(),
}));

let clipboardWriteText: ReturnType<typeof vi.fn>;
const endpointUrl = "https://demo.self.wai.computer/mcp";

function renderSection() {
  render(<McpConnectSection endpointUrl={endpointUrl} />);
}

describe("McpConnectSection", () => {
  beforeEach(() => {
    clipboardWriteText = vi.fn().mockResolvedValue(undefined);
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
    vi.restoreAllMocks();
  });

  it("renders the active MCP endpoint URL", () => {
    renderSection();
    const url = screen.getByTestId("mcp-endpoint-url");
    expect(url.textContent).toBe(endpointUrl);
  });

  it("defaults to the Claude.ai guide and exposes the external link", () => {
    renderSection();
    expect(screen.getByTestId("mcp-guide-claudeai")).toBeTruthy();
    const link = screen.getByRole("link", { name: /Open Connectors in Claude\.ai/i }) as HTMLAnchorElement;
    expect(link.href).toBe("https://claude.ai/customize/connectors");
    expect(link.target).toBe("_blank");
  });

  it("switches to the Cursor guide and shows the JSON snippet", () => {
    renderSection();
    fireEvent.click(screen.getByRole("tab", { name: "Cursor" }));
    expect(screen.getByTestId("mcp-guide-cursor")).toBeTruthy();
    const snippet = screen.getByText(/"mcpServers"/);
    expect(snippet.textContent).toContain(endpointUrl);
  });

  it("copies the endpoint URL to the clipboard and shows confirmation", async () => {
    renderSection();
    fireEvent.click(screen.getByTestId("mcp-copy-endpoint"));
    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenCalledWith(endpointUrl);
    });
    expect(screen.getByTestId("mcp-copy-endpoint").textContent).toBe("Copied");
  });

  it("copies the active client snippet when present", async () => {
    renderSection();
    fireEvent.click(screen.getByRole("tab", { name: "Codex CLI" }));
    fireEvent.click(screen.getByTestId("mcp-copy-snippet"));
    await waitFor(() => {
      const lastCall = clipboardWriteText.mock.calls.at(-1);
      expect(lastCall?.[0]).toContain(`codex mcp add waicomputer --url ${endpointUrl}`);
    });
  });

  it("uses --transport http in the Claude Code CLI snippet so it is treated as HTTP, not stdio", async () => {
    renderSection();
    fireEvent.click(screen.getByRole("tab", { name: "Claude Code" }));
    fireEvent.click(screen.getByTestId("mcp-copy-snippet"));
    await waitFor(() => {
      const lastCall = clipboardWriteText.mock.calls.at(-1);
      expect(lastCall?.[0]).toContain(
        `claude mcp add --transport http waicomputer ${endpointUrl}`,
      );
    });
  });

  it("documents the headless bot recipe: API token via Bearer on REST + MCP", () => {
    renderSection();
    fireEvent.click(screen.getByRole("tab", { name: "Custom / bot" }));
    const guide = screen.getByTestId("mcp-guide-bot");
    expect(guide.textContent).toMatch(/API token/i);
    expect(guide.textContent).toMatch(/Bearer/);
  });
});
