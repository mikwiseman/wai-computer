"use client";

import { useEffect, useMemo, useState } from "react";

import { getSystemInfo } from "@/lib/api";
import { McpConnectionsList } from "./McpConnectionsList";
import { McpSourcesPanel } from "./McpSourcesPanel";

type McpClient = "claudeai" | "cursor" | "chatgpt" | "claudecode" | "codex" | "bot";

type McpClientGuide = {
  id: McpClient;
  label: string;
  steps: string;
  snippet?: { language: string; body: string };
  externalLink?: { label: string; url: string };
};

function clientGuides(mcpEndpointUrl: string): McpClientGuide[] {
  return [
  {
    id: "claudeai",
    label: "Claude.ai",
    steps:
      "Open Customize → Connectors and click the “+” button. Paste the URL, then approve the request on wai.computer when prompted.",
    externalLink: { label: "Open Connectors in Claude.ai", url: "https://claude.ai/customize/connectors" },
  },
  {
    id: "cursor",
    label: "Cursor",
    steps:
      "Add this server to .cursor/mcp.json in your project root (or to your global Cursor MCP settings). Cursor starts the OAuth flow on first use.",
    snippet: {
      language: "json",
      body: `{
  "mcpServers": {
    "waicomputer": {
      "url": "${mcpEndpointUrl}"
    }
  }
}`,
    },
  },
  {
    id: "chatgpt",
    label: "ChatGPT",
    steps:
      "Open ChatGPT → Settings → Connectors. Enable Developer Mode, add an MCP server, and paste the URL.",
  },
  {
    id: "claudecode",
    label: "Claude Code",
    steps:
      "Either run the CLI add command, or drop the snippet into a .mcp.json at your project root.",
    snippet: {
      language: "json",
      body: `# CLI
claude mcp add --transport http waicomputer ${mcpEndpointUrl}

# Or .mcp.json:
{
  "mcpServers": {
    "waicomputer": {
      "type": "http",
      "url": "${mcpEndpointUrl}"
    }
  }
}`,
    },
  },
  {
    id: "codex",
    label: "Codex CLI",
    steps:
      "Add the server, then complete the OAuth login from the browser when prompted.",
    snippet: {
      language: "bash",
      body: `codex mcp add waicomputer --url ${mcpEndpointUrl}
codex mcp login waicomputer`,
    },
  },
  {
    id: "bot",
    label: "Custom / bot",
    steps:
      "For an unattended bot or cron job (no browser), create a read-only API token under “API tokens” below and send it as a Bearer header. The same token works on the REST API and this MCP endpoint — no OAuth, no refresh to manage.",
    snippet: {
      language: "bash",
      body: `# Create a token under "API tokens" below (copy it once), then:

# REST — incremental pull of recordings:
curl -H "Authorization: Bearer wc_live_…" \\
  "https://wai.computer/api/recordings?updated_after=2026-05-01T00:00:00Z"

# MCP — same token, the read tools:
# {
#   "mcpServers": {
#     "waicomputer": {
#       "url": "${mcpEndpointUrl}",
#       "headers": { "Authorization": "Bearer wc_live_…" }
#     }
#   }
# }`,
    },
  },
  ];
}

async function copyText(value: string): Promise<boolean> {
  if (!navigator.clipboard?.writeText) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

export function McpConnectSection() {
  const [selected, setSelected] = useState<McpClient>("claudeai");
  const [copied, setCopied] = useState<"endpoint" | "snippet" | null>(null);
  const [endpointUrl, setEndpointUrl] = useState<string | null>(null);
  const [endpointError, setEndpointError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getSystemInfo()
      .then((info) => {
        if (!cancelled) {
          setEndpointUrl(info.mcp_url);
          setEndpointError(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setEndpointUrl(null);
          setEndpointError("Could not load the MCP endpoint for this server.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const guides = useMemo(
    () => (endpointUrl ? clientGuides(endpointUrl) : clientGuides("")),
    [endpointUrl],
  );
  const guide = guides.find((c) => c.id === selected) ?? guides[0];
  const snippet = endpointUrl ? guide.snippet : undefined;

  async function handleCopy(field: "endpoint" | "snippet", value: string) {
    const ok = await copyText(value);
    if (ok) {
      setCopied(field);
      setTimeout(() => setCopied((current) => (current === field ? null : current)), 1500);
    }
  }

  return (
    <div className="settings-form mcp-connect-form">
      <h3>MCP</h3>
      <p className="settings-note">
        WaiComputer exposes an MCP (Model Context Protocol) server. Connect any MCP-compatible AI assistant to give
        it read-only access to your recordings, transcripts, summaries, action items, and metadata. You approve each
        client by name on wai.computer and can revoke any time from the client itself.
      </p>

      <div className="mcp-endpoint-row">
        <code className="mcp-endpoint-url" data-testid="mcp-endpoint-url">
          {endpointUrl ?? endpointError ?? "Loading MCP endpoint..."}
        </code>
        <button
          type="button"
          className="ghost-button compact-button"
          data-testid="mcp-copy-endpoint"
          disabled={!endpointUrl}
          onClick={() => (endpointUrl ? void handleCopy("endpoint", endpointUrl) : undefined)}
        >
          {copied === "endpoint" ? "Copied" : "Copy URL"}
        </button>
      </div>

      <div className="tab-strip mcp-client-tabs" role="tablist" aria-label="MCP client">
        {guides.map((client) => (
          <button
            key={client.id}
            type="button"
            role="tab"
            aria-selected={client.id === selected}
            className="tab-button"
            onClick={() => setSelected(client.id)}
          >
            {client.label}
          </button>
        ))}
      </div>

      <div className="mcp-client-guide" data-testid={`mcp-guide-${guide.id}`}>
        <p>{guide.steps}</p>

        {snippet ? (
          <div className="mcp-snippet">
            <pre>
              <code className={`language-${snippet.language}`}>{snippet.body}</code>
            </pre>
            <button
              type="button"
              className="ghost-button compact-button"
              data-testid="mcp-copy-snippet"
              onClick={() => void handleCopy("snippet", snippet.body)}
            >
              {copied === "snippet" ? "Copied" : "Copy snippet"}
            </button>
          </div>
        ) : null}

        {guide.externalLink ? (
          <a
            href={guide.externalLink.url}
            target="_blank"
            rel="noreferrer"
            className="ghost-button compact-button mcp-external-link"
          >
            {guide.externalLink.label}
          </a>
        ) : null}
      </div>

      <McpConnectionsList />
      <McpSourcesPanel />
    </div>
  );
}
