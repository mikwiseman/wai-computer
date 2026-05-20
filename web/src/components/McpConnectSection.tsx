"use client";

import { useState } from "react";

import { McpConnectionsList } from "./McpConnectionsList";

const MCP_ENDPOINT_URL = "https://wai.computer/mcp";

type McpClient = "claudeai" | "cursor" | "chatgpt" | "claudecode" | "codex" | "bot";

type McpClientGuide = {
  id: McpClient;
  label: string;
  steps: string;
  snippet?: { language: string; body: string };
  externalLink?: { label: string; url: string };
};

const CLIENT_GUIDES: McpClientGuide[] = [
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
      "url": "${MCP_ENDPOINT_URL}"
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
claude mcp add --transport http waicomputer ${MCP_ENDPOINT_URL}

# Or .mcp.json:
{
  "mcpServers": {
    "waicomputer": {
      "type": "http",
      "url": "${MCP_ENDPOINT_URL}"
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
      body: `codex mcp add waicomputer --url ${MCP_ENDPOINT_URL}
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
#       "url": "${MCP_ENDPOINT_URL}",
#       "headers": { "Authorization": "Bearer wc_live_…" }
#     }
#   }
# }`,
    },
  },
];

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

  const guide = CLIENT_GUIDES.find((c) => c.id === selected) ?? CLIENT_GUIDES[0];

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
          {MCP_ENDPOINT_URL}
        </code>
        <button
          type="button"
          className="ghost-button compact-button"
          data-testid="mcp-copy-endpoint"
          onClick={() => void handleCopy("endpoint", MCP_ENDPOINT_URL)}
        >
          {copied === "endpoint" ? "Copied" : "Copy URL"}
        </button>
      </div>

      <div className="tab-strip mcp-client-tabs" role="tablist" aria-label="MCP client">
        {CLIENT_GUIDES.map((client) => (
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

        {guide.snippet ? (
          <div className="mcp-snippet">
            <pre>
              <code className={`language-${guide.snippet.language}`}>{guide.snippet.body}</code>
            </pre>
            <button
              type="button"
              className="ghost-button compact-button"
              data-testid="mcp-copy-snippet"
              onClick={() => void handleCopy("snippet", guide.snippet!.body)}
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
    </div>
  );
}
