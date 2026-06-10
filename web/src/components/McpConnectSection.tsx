"use client";

import { useEffect, useMemo, useState } from "react";

import { getSystemInfo } from "@/lib/api";
import { McpConnectionsList } from "./McpConnectionsList";

type Locale = "en" | "ru";

type McpClient =
  | "openclaw"
  | "hermes"
  | "claudeai"
  | "cursor"
  | "chatgpt"
  | "claudecode"
  | "codex"
  | "bot";

type McpClientGuide = {
  id: McpClient;
  label: string;
  steps: string;
  snippet?: { language: string; body: string };
  externalLink?: { label: string; url: string };
};

interface Copy {
  intro: string;
  endpointError: string;
  endpointLoading: string;
  copyUrl: string;
  copied: string;
  copySnippet: string;
  linkClaudeai: string;
  stepsOpenclaw: string;
  stepsHermes: string;
  stepsClaudeai: string;
  stepsCursor: string;
  stepsChatgpt: string;
  stepsClaudecode: string;
  stepsCodex: string;
  stepsBot: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    intro:
      "Give your AI agent a brain. WaiComputer exposes an MCP (Model Context Protocol) server, so any agent — OpenClaw, Hermes, Claude, Cursor, … — can recall everything you've captured (ask your brain a cited question, search recordings, notes, and chats) and, if you allow it, remember new facts back. You approve each agent by name on wai.computer and can revoke any time.",
    endpointError: "Could not load the MCP endpoint for this server.",
    endpointLoading: "Loading MCP endpoint...",
    copyUrl: "Copy URL",
    copied: "Copied",
    copySnippet: "Copy snippet",
    linkClaudeai: "Open Connectors in Claude.ai",
    stepsOpenclaw:
      "Add WaiComputer as a remote MCP server, then approve the OAuth login in your browser — no token to copy. Your OpenClaw agent can now ask and search your whole brain. To let it remember new facts too, create a write-enabled token under “API tokens” below and use the header form.",
    stepsHermes:
      "Add WaiComputer under mcp_servers in ~/.hermes/config.yaml, then run /reload-mcp (or restart). Approve the OAuth login on first connect. For a true memory bank (read + write), create a write-enabled token under “API tokens” below and use the headers form instead.",
    stepsClaudeai:
      "Open Customize → Connectors and click the “+” button. Paste the URL, then approve the request on wai.computer when prompted.",
    stepsCursor:
      "Add this server to .cursor/mcp.json in your project root (or to your global Cursor MCP settings). Cursor starts the OAuth flow on first use.",
    stepsChatgpt:
      "Open ChatGPT → Settings → Connectors. Enable Developer Mode, add an MCP server, and paste the URL.",
    stepsClaudecode:
      "Either run the CLI add command, or drop the snippet into a .mcp.json at your project root.",
    stepsCodex:
      "Add the server, then complete the OAuth login from the browser when prompted.",
    stepsBot:
      "For an unattended bot or cron job (no browser), create a read-only API token under “API tokens” below and send it as a Bearer header. The same token works on the REST API and this MCP endpoint — no OAuth, no refresh to manage.",
  },
  ru: {
    intro:
      "Дайте вашему ИИ-агенту память. WaiComputer предоставляет MCP-сервер (Model Context Protocol), так что любой агент — OpenClaw, Hermes, Claude, Cursor, … — может вспоминать всё, что вы сохранили (задать вопрос мозгу с цитатами, искать по записям, заметкам и чатам) и, если вы разрешите, запоминать новые факты. Каждого агента вы подтверждаете по имени на wai.computer и можете отозвать доступ в любой момент.",
    endpointError: "Не удалось загрузить MCP-адрес для этого сервера.",
    endpointLoading: "Загрузка MCP-адреса...",
    copyUrl: "Скопировать URL",
    copied: "Скопировано",
    copySnippet: "Скопировать фрагмент",
    linkClaudeai: "Открыть «Коннекторы» в Claude.ai",
    stepsOpenclaw:
      "Добавьте WaiComputer как удалённый MCP-сервер и подтвердите вход через OAuth в браузере — токен копировать не нужно. Агент OpenClaw сможет спрашивать и искать по всему вашему мозгу. Чтобы он мог ещё и запоминать факты, создайте токен с правом записи в разделе «API-токены» ниже и используйте форму с заголовком.",
    stepsHermes:
      "Добавьте WaiComputer в mcp_servers в ~/.hermes/config.yaml и выполните /reload-mcp (или перезапустите). Подтвердите вход через OAuth при первом подключении. Для полноценного «банка памяти» (чтение + запись) создайте токен с правом записи в разделе «API-токены» ниже и используйте форму с headers.",
    stepsClaudeai:
      "Откройте «Настроить → Коннекторы» и нажмите «+». Вставьте URL и подтвердите запрос на wai.computer.",
    stepsCursor:
      "Добавьте этот сервер в .cursor/mcp.json в корне проекта (или в глобальные настройки MCP в Cursor). При первом обращении Cursor запустит OAuth.",
    stepsChatgpt:
      "Откройте ChatGPT → Настройки → Коннекторы. Включите режим разработчика, добавьте MCP-сервер и вставьте URL.",
    stepsClaudecode:
      "Выполните команду CLI для добавления или поместите фрагмент в .mcp.json в корне проекта.",
    stepsCodex:
      "Добавьте сервер, затем завершите вход через OAuth в браузере по запросу.",
    stepsBot:
      "Для бота или cron-задачи без браузера создайте токен API только для чтения в разделе «API-токены» ниже и передавайте его в заголовке Bearer. Один и тот же токен работает и в REST API, и в этом MCP-адресе — без OAuth и обновления токенов.",
  },
};

function clientGuides(mcpEndpointUrl: string, copy: Copy): McpClientGuide[] {
  return [
  {
    id: "openclaw",
    label: "OpenClaw",
    steps: copy.stepsOpenclaw,
    snippet: {
      language: "bash",
      body: `# Recall your brain (OAuth — approve in your browser, no token to copy):
openclaw mcp add waicomputer \\
  --url ${mcpEndpointUrl} \\
  --transport streamable-http \\
  --auth oauth
openclaw mcp login waicomputer

# Memory bank (read + write) — use a write-enabled token instead:
openclaw mcp add waicomputer \\
  --url ${mcpEndpointUrl} \\
  --transport streamable-http \\
  --header "Authorization: Bearer wc_live_…"`,
    },
    externalLink: { label: "OpenClaw MCP docs", url: "https://docs.openclaw.ai/cli/mcp" },
  },
  {
    id: "hermes",
    label: "Hermes",
    steps: copy.stepsHermes,
    snippet: {
      language: "yaml",
      body: `# ~/.hermes/config.yaml — recall your brain (OAuth, approve in browser):
mcp_servers:
  waicomputer:
    url: "${mcpEndpointUrl}"
    auth: oauth

# Memory bank (read + write) — use a write-enabled token instead:
mcp_servers:
  waicomputer:
    url: "${mcpEndpointUrl}"
    headers:
      Authorization: "Bearer wc_live_…"

# then in Hermes:  /reload-mcp`,
    },
    externalLink: {
      label: "Hermes MCP docs",
      url: "https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp",
    },
  },
  {
    id: "claudeai",
    label: "Claude.ai",
    steps: copy.stepsClaudeai,
    externalLink: { label: copy.linkClaudeai, url: "https://claude.ai/customize/connectors" },
  },
  {
    id: "cursor",
    label: "Cursor",
    steps: copy.stepsCursor,
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
    steps: copy.stepsChatgpt,
  },
  {
    id: "claudecode",
    label: "Claude Code",
    steps: copy.stepsClaudecode,
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
    steps: copy.stepsCodex,
    snippet: {
      language: "bash",
      body: `codex mcp add waicomputer --url ${mcpEndpointUrl}
codex mcp login waicomputer`,
    },
  },
  {
    id: "bot",
    label: "Custom / bot",
    steps: copy.stepsBot,
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

interface McpConnectSectionProps {
  locale?: Locale;
}

export function McpConnectSection({ locale = "en" }: McpConnectSectionProps) {
  const copy = COPY[locale];
  const [selected, setSelected] = useState<McpClient>("openclaw");
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
          setEndpointError(copy.endpointError);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [copy.endpointError]);

  const guides = useMemo(
    () => (endpointUrl ? clientGuides(endpointUrl, copy) : clientGuides("", copy)),
    [endpointUrl, copy],
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
      <p className="settings-note">{copy.intro}</p>

      <div className="mcp-endpoint-row">
        <code className="mcp-endpoint-url" data-testid="mcp-endpoint-url">
          {endpointUrl ?? endpointError ?? copy.endpointLoading}
        </code>
        <button
          type="button"
          className="ghost-button compact-button"
          data-testid="mcp-copy-endpoint"
          disabled={!endpointUrl}
          onClick={() => (endpointUrl ? void handleCopy("endpoint", endpointUrl) : undefined)}
        >
          {copied === "endpoint" ? copy.copied : copy.copyUrl}
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
              {copied === "snippet" ? copy.copied : copy.copySnippet}
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

      <McpConnectionsList locale={locale} />
    </div>
  );
}
