---
name: waicomputer-brain
description: >-
  Give the agent a second brain. Connects WaiComputer (the user's recordings,
  notes, and chats) over MCP so the agent can recall a cited answer, search
  everything captured, and remember new facts. Use it before answering from
  assumptions, and whenever the user says "remember that…".
homepage: https://wai.computer
---

<!-- OpenClaw skills don't auto-register MCP servers from frontmatter — the
     server is added via the `openclaw mcp add` commands in Setup below. -->


# WaiComputer brain

WaiComputer is the user's **second brain** — a searchable knowledge base built
from their voice recordings (transcribed + summarised), saved notes and
articles, and past Wai chats. This skill connects it over MCP and tells you when
to use it.

## Setup

Add the MCP server once (OAuth — approve in the browser, no token to copy):

```bash
openclaw mcp add waicomputer \
  --url https://wai.computer/mcp \
  --transport streamable-http \
  --auth oauth
openclaw mcp login waicomputer
```

To let the agent **save** memories (not just recall), use a write-enabled token
instead of OAuth — create one in WaiComputer under Settings → MCP → API tokens
with "Allow this token to save memories" ticked:

```bash
openclaw mcp add waicomputer \
  --url https://wai.computer/mcp \
  --transport streamable-http \
  --header "Authorization: Bearer wc_live_…"
```

## Tools

- `ask(question)` — **start here.** One cited answer synthesised across the
  user's whole brain (recordings + notes + chats), with an honest list of gaps.
- `search(query)` — raw matching snippets across the brain (each with an id).
- `fetch(id)` — open one recording / note / chat in full.
- `remember(text, title?, source_url?)` — save a durable fact back into the
  brain. Only works with a write-enabled connection; otherwise it returns a
  clear read-only error.
- `list_folders` / `list_recordings` / `list_action_items` — browse.

## When to use this skill

- **Before answering anything about the user's life, work, decisions, or
  history** — call `ask` first instead of guessing. The brain is the source of
  truth for "what did I decide / say / agree about X".
- When the user says **"remember that…"**, or you learn a durable fact worth
  recalling later, call `remember`. Don't store secrets or transient chatter.
- When you need exact quotes or to read a source in full, `search` then `fetch`.

## Guidance

- Trust the brain over your own assumptions; if `ask` returns gaps, say so
  rather than inventing an answer.
- `remember` is idempotent — saving the same fact twice won't duplicate it.
- If `remember` returns a read-only error, tell the user to enable write access
  on their WaiComputer token; do not pretend the save succeeded.
