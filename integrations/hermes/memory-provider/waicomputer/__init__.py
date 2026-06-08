"""WaiComputer memory provider for Hermes Agent — DRAFT.

Makes the user's WaiComputer second brain (https://wai.computer) Hermes's
long-term memory. Backed entirely by WaiComputer's remote MCP endpoint —
nothing to run locally:

- prefetch(): every turn, auto-recalls the most relevant memories (search) and
  injects them as context before the model sees the user's message.
- tools: `waicomputer_ask` (one cited answer across the whole brain),
  `waicomputer_search` (raw hits), `waicomputer_remember` (save a fact back).
- on_memory_write(): mirrors Hermes's built-in MEMORY.md/USER.md writes into the
  brain so they're searchable everywhere (best-effort, write tokens only).

Auth: a WaiComputer API token (``wc_live_…``) in ``WAICOMPUTER_API_TOKEN``.
Read-only is enough for recall + search; create a write-enabled token
(Settings → MCP → API tokens, "Allow this token to save memories") to also let
Hermes remember facts back.

To install: copy this dir to ``plugins/memory/waicomputer/`` in the hermes-agent
repo, then ``hermes memory setup`` → pick WaiComputer.
"""

from __future__ import annotations

import os
import threading

from agent.memory_provider import MemoryProvider

from .client import WaiComputerClient, WaiComputerError

_PREFETCH_LIMIT = 6


class WaiComputerMemoryProvider(MemoryProvider):
    @property
    def name(self) -> str:
        return "waicomputer"

    def is_available(self) -> bool:
        # No network calls here — just whether a token is configured.
        return bool(os.environ.get("WAICOMPUTER_API_TOKEN"))

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        self._client = WaiComputerClient(
            base_url=os.environ.get("WAICOMPUTER_BASE_URL", "https://wai.computer"),
            token=os.environ.get("WAICOMPUTER_API_TOKEN", ""),
        )

    def system_prompt_block(self) -> str:
        return (
            "You have a WaiComputer second brain as long-term memory (the user's "
            "recordings, notes, and past chats). Relevant memories are recalled "
            "automatically before each turn. Call `waicomputer_ask` for a "
            "synthesised, cited answer, `waicomputer_search` to look something "
            "up, and `waicomputer_remember` to save a durable fact (only works if "
            "the connection has write access). Prefer recalling from the brain "
            "over guessing."
        )

    # --- automatic recall before each turn -----------------------------------

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        query = (query or "").strip()
        if not query:
            return ""
        try:
            hits = self._client.search(query, limit=_PREFETCH_LIMIT).get("results", [])
        except Exception:
            return ""  # recall is best-effort — never block or fail a turn
        if not hits:
            return ""
        lines = ["Relevant memories from your WaiComputer brain:"]
        for hit in hits:
            kind = (hit.get("metadata") or {}).get("source_kind", "memory")
            title = hit.get("title") or "Untitled"
            text = (hit.get("text") or "").strip()
            lines.append(f"- [{kind}] {title}: {text}")
        return "\n".join(lines)

    # --- explicit tools -------------------------------------------------------

    def get_tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "waicomputer_ask",
                    "description": (
                        "Ask the user's WaiComputer second brain a question and get ONE "
                        "cited answer synthesised across their recordings, notes, and chats, "
                        "with an honest list of gaps. Use this to recall what the user has "
                        "captured before answering from assumptions."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"question": {"type": "string"}},
                        "required": ["question"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "waicomputer_search",
                    "description": (
                        "Search the user's whole WaiComputer brain (recordings, notes, "
                        "chats) and get raw matching snippets with source ids."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "default": 10},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "waicomputer_remember",
                    "description": (
                        "Save a new memory into the user's WaiComputer brain — a fact, "
                        "decision, or note worth recalling later. Only works if the "
                        "connection has write access; otherwise returns a clear error. "
                        "Do not store secrets or transient chatter."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "title": {"type": "string"},
                            "source_url": {"type": "string"},
                        },
                        "required": ["text"],
                    },
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        import json

        try:
            if tool_name == "waicomputer_ask":
                return json.dumps(self._client.ask(args["question"]), ensure_ascii=False)
            if tool_name == "waicomputer_search":
                return json.dumps(
                    self._client.search(args["query"], int(args.get("limit", 10))),
                    ensure_ascii=False,
                )
            if tool_name == "waicomputer_remember":
                return json.dumps(
                    self._client.remember(
                        args["text"], args.get("title"), args.get("source_url")
                    ),
                    ensure_ascii=False,
                )
        except WaiComputerError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the agent
            return json.dumps({"error": f"WaiComputer call failed: {exc}"}, ensure_ascii=False)
        return json.dumps({"error": f"unknown tool {tool_name}"}, ensure_ascii=False)

    # --- mirror built-in memory writes into the brain (write tokens only) -----

    def on_memory_write(self, action: str, target: str, content: str, metadata=None) -> None:
        # Signature matches Hermes's MemoryProvider ABC, which passes a 4th
        # `metadata` arg; omitting it raises TypeError on every built-in write.
        if action not in ("add", "update") or not (content or "").strip():
            return

        def _save() -> None:
            try:
                self._client.remember(content, title=f"Hermes {target}")
            except Exception:
                pass  # read-only token or transient failure — silent, non-fatal

        threading.Thread(target=_save, daemon=True).start()

    # --- config wizard --------------------------------------------------------

    def get_config_schema(self) -> list[dict]:
        return [
            {
                "key": "api_token",
                "description": (
                    "WaiComputer API token (wc_live_…). Create one in Settings → MCP → "
                    "API tokens; tick 'Allow this token to save memories' for write access."
                ),
                "secret": True,
                "required": True,
                "env_var": "WAICOMPUTER_API_TOKEN",
                "url": "https://wai.computer",
            },
            {
                "key": "base_url",
                "description": "WaiComputer base URL (self-hosters can change this).",
                "default": "https://wai.computer",
                "env_var": "WAICOMPUTER_BASE_URL",
            },
        ]

    def save_config(self, values: dict, hermes_home: str) -> None:
        # Both fields are env-var-backed (secrets → .env); nothing else to persist.
        return None

    def shutdown(self) -> None:
        client = getattr(self, "_client", None)
        if client is not None:
            client.close()


def register(ctx) -> None:
    """Entry point called by Hermes's memory plugin discovery."""
    ctx.register_memory_provider(WaiComputerMemoryProvider())
