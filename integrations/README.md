# WaiComputer as your agent's brain

WaiComputer is a **second brain** — your recordings, notes, and chats, linked
into one searchable knowledge base. This directory makes it the long-term memory
for autonomous agents, with **OpenClaw** and **Hermes** as first-class targets.

It's a **two-sided connection over one link** (`https://wai.computer/mcp`):

```
                WaiComputer  =  the brain / memory bank
                       ▲   (one MCP connection)
   RECALL ─────────────┤   ask · search · fetch · list_*     ← read your brain
   (agent reads brain)  │
                        │   OpenClaw / Hermes / any MCP agent
                        ▼
   STORE ──────────────┘   remember(text, …)                 ← write back
   (agent saves memories)  → flows into entities / dossiers / search
```

- **Recall** is read-only by default and works with OAuth (approve in a browser)
  or a `wc_live_…` API token.
- **Store** (`remember`) is opt-in: it only works when the connection was granted
  the `mcp:write` scope — an OAuth grant or a token created with **"Allow this
  token to save memories"** (Settings → MCP → API tokens). The REST API stays
  read-only regardless.

The MCP tool surface (9): `wake_up`, `ask`, `search`, `fetch`, `remember`,
`forget`, `list_folders`, `list_recordings`, `list_action_items`.

### Point an agent at a folder

`ask` and `search` accept `folder_ids` (from `list_folders`), so any folder
becomes a scoped knowledge base for an agent: a "Falcone" project folder, a
"Standups" folder, an "Investors" folder. The agent answers from that folder's
recordings + saved materials alone — optimal context, no cross-project noise:

```jsonc
// "What's the latest decision in my Falcone folder?"
{ "name": "ask", "arguments": {
    "question": "what did we decide about pricing?",
    "folder_ids": ["<folder-uuid-from-list_folders>"] } }
```

## Quick connect

**OpenClaw** (`~/.openclaw/openclaw.json` or the CLI):

```bash
openclaw mcp add waicomputer --url https://wai.computer/mcp \
  --transport streamable-http --auth oauth
openclaw mcp login waicomputer
# memory bank (read + write): use a write-enabled token instead of --auth oauth
#   --header "Authorization: Bearer wc_live_…"
```

**Hermes** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  waicomputer:
    url: "https://wai.computer/mcp"
    auth: oauth          # or: headers: { Authorization: "Bearer wc_live_…" } for read+write
```

Both also have a copy-paste recipe inside the apps: **Settings → MCP** on web,
Mac, and iOS leads with OpenClaw and Hermes.

## Going deeper (drafts in this repo)

These package WaiComputer for each ecosystem's native distribution. They live
here and are **submitted upstream by PR** (we can't merge into their repos):

| Path | What it is | Upstream target |
| --- | --- | --- |
| [`hermes/optional-mcps/waicomputer/`](./hermes/optional-mcps/waicomputer/manifest.yaml) | Hermes catalog manifest → **one-click install** | PR to `NousResearch/hermes-agent` `optional-mcps/` |
| [`hermes/memory-provider/waicomputer/`](./hermes/memory-provider/waicomputer/) | Native **Hermes memory provider** — auto-recall every turn + ask/search/remember + MEMORY.md mirroring | PR to `NousResearch/hermes-agent` `plugins/memory/` |
| [`openclaw/waicomputer-brain/`](./openclaw/waicomputer-brain/) | OpenClaw **skill** (MCP config + when-to-recall/remember guidance) | ClawHub / `openclaw` skills |

The memory provider is the deepest: it makes WaiComputer Hermes's 9th memory
backend, so **every turn auto-recalls** from your brain — no tool call needed.

## Verifying

The MCP endpoint is live. To smoke-test recall + the write gate with a token:

```bash
TOKEN=wc_live_…   # read-only is fine for ask/search; write-enabled for remember
curl -s https://wai.computer/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"ask","arguments":{"question":"what did I decide about the launch"}}}'
```
