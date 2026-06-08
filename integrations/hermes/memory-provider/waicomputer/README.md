# WaiComputer memory provider for Hermes Agent

Use your [WaiComputer](https://wai.computer) second brain as Hermes's long-term
memory. Every turn, Hermes auto-recalls relevant memories from your recordings,
notes, and past chats; the agent can also ask, search, and (with write access)
remember new facts. It's backed entirely by WaiComputer's remote MCP endpoint —
**nothing runs locally**.

> Status: **draft** maintained in the WaiComputer repo. To use it, copy this
> directory into `plugins/memory/waicomputer/` in your hermes-agent checkout.

## What it does

| Hermes hook | WaiComputer behaviour |
| --- | --- |
| `prefetch` (before each turn) | `search` your brain for the user's message → inject the top hits as context |
| `waicomputer_ask` tool | one cited answer synthesised across the whole brain |
| `waicomputer_search` tool | raw matching snippets with source ids |
| `waicomputer_remember` tool | save a new memory (write tokens only) |
| `on_memory_write` | mirror Hermes's `MEMORY.md`/`USER.md` writes into the brain (write tokens only) |

## Requirements

- A WaiComputer account and an **API token** (`wc_live_…`). Create one in any
  WaiComputer client under **Settings → MCP → API tokens**.
  - Read-only is enough for recall (`prefetch`, `ask`, `search`).
  - Tick **"Allow this token to save memories"** to also enable `remember` and
    memory mirroring. The REST API stays read-only either way.

## Setup

```bash
# 1. Drop this dir into your hermes-agent checkout:
cp -r waicomputer ~/.hermes/hermes-agent/plugins/memory/waicomputer

# 2. Run the wizard and pick WaiComputer (it prompts for the token):
hermes memory setup
```

Or configure manually:

```bash
# ~/.hermes/.env
WAICOMPUTER_API_TOKEN=wc_live_…
# optional, for self-hosters:
# WAICOMPUTER_BASE_URL=https://your-host
```

```yaml
# ~/.hermes/config.yaml
memory:
  provider: waicomputer
```

Then start Hermes and ask it something you've captured before — the answer comes
from your brain, with citations.

## Notes

- `prefetch` uses `search` (cheap retrieval), not `ask` (LLM synthesis), so
  auto-recall stays fast and low-cost. Use the `waicomputer_ask` tool when you
  want a synthesised answer.
- Recall is best-effort: if WaiComputer is unreachable, the turn proceeds
  without injected memories rather than failing.
- Only one external memory provider can be active at a time (Hermes rule); the
  built-in `MEMORY.md`/`USER.md` stays active alongside it.
