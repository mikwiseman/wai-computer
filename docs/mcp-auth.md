# WaiComputer MCP Auth

As of May 5, 2026, the interoperable path for hosted MCP clients is OAuth over
Streamable HTTP, not a direct redirect from JSON-RPC requests.

## Quick Connect

End-users get the same instructions in-app at **Settings → MCP** on every
WaiComputer client (Web, macOS, iOS, Android). The canonical URL is always
`https://wai.computer/mcp` regardless of which client you copy from.

- **Claude.ai**: <https://claude.ai/customize/connectors> → click the "+" button → paste URL → approve on `wai.computer`.
- **Cursor**: drop into `.cursor/mcp.json` (project) or global Cursor MCP settings:
  ```json
  { "mcpServers": { "waicomputer": { "url": "https://wai.computer/mcp" } } }
  ```
- **ChatGPT Apps & Connectors**: Settings → Connectors → Developer mode → Add MCP server → paste URL.
- **Claude Code**: `claude mcp add waicomputer https://wai.computer/mcp` or `.mcp.json` with `"type": "http"`.
- **Codex CLI**: `codex mcp add waicomputer --url https://wai.computer/mcp` then `codex mcp login waicomputer`.

## Implementation Audit (2026-05-18)

Spec compliance verified against May 2026 best practices and live prod responses:
- SDK: `mcp` 1.27.0 on disk (pin `>=1.27.0,<2`); ships RFC 8707 + STDIO CVE patches.
- Transport: Streamable HTTP only (`mcp_server.py:66`); no deprecated HTTP+SSE.
- `/mcp` 401 returns `WWW-Authenticate: Bearer` with `resource_metadata=` discovery pointer ✓
- `/.well-known/oauth-protected-resource/mcp` advertises `bearer_methods_supported: ["header"]` (no query-param tokens) ✓
- `/.well-known/oauth-authorization-server` advertises `code_challenge_methods_supported: ["S256"]` only (plaintext PKCE rejected) ✓
- RFC 8707 resource indicators enforced in `core/mcp_oauth.py:136-150` (called at lines 333, 391, 576).
- DCR redirect URIs restricted to HTTPS or loopback at `mcp_oauth.py:177-188`.
- Tokens SHA-256-hashed at rest, audience-bound, one-use codes, refresh rotation, revocation endpoint exposed.
- Strict security headers: HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff.
- `tests/test_mcp_oauth.py` — 3/3 passing; ruff clean.

Operational notes: `stateless_http=True` + `json_response=True` (`mcp_server.py:67-68`) disable SSE
streaming and session resumability. Acceptable for current small read-only tool payloads;
revisit if streaming tools are added.

## Public Endpoints

- MCP endpoint: `https://wai.computer/mcp`
- Protected resource metadata: `https://wai.computer/.well-known/oauth-protected-resource/mcp`
- Authorization server metadata: `https://wai.computer/.well-known/oauth-authorization-server`
- Authorization endpoint: `https://wai.computer/authorize`
- Token endpoint: `https://wai.computer/token`
- Dynamic client registration: `POST https://wai.computer/register`
- Token revocation: `POST https://wai.computer/revoke`

`GET /register` remains a web route. Only `POST` and `OPTIONS` on `/register`
are routed to the API for MCP dynamic client registration.

## User Authorization Flow

1. A client such as ChatGPT, Claude Code, Claude.ai, Cursor, or Codex calls
   `/mcp` without a token.
2. WaiComputer returns `401` with a `WWW-Authenticate: Bearer` challenge pointing to
   protected resource metadata and scope `mcp:read`.
3. The client discovers OAuth metadata, dynamically registers itself if needed,
   then starts an authorization-code + PKCE flow with `resource=https://wai.computer/mcp`.
4. WaiComputer creates a pending authorization request and redirects the browser to
   `/api/mcp/oauth/consent?request=...`.
5. The browser is redirected to WaiComputer web. If the browser is not signed in,
   WaiComputer redirects to
   `/login?returnTo=/api/mcp/oauth/consent?...`.
6. After login, the user sees the requesting client name, requested scope, and
   redirect URI, then approves read-only MCP access. WaiComputer redirects back to
   the client callback with an authorization code.
7. The client exchanges the code and PKCE verifier at `/token`.
8. Subsequent MCP calls use `Authorization: Bearer <access-token>`.

This is the intended authorization UX. Do not ask users to paste WaiComputer tokens,
API keys, or Keychain values into MCP clients.

## Scope And Data Surface

Initial scope is intentionally narrow:

- `mcp:read`: search and fetch the authenticated user's non-deleted recordings,
  transcripts, summaries, metadata, and action items.

The server currently exposes two read-only tools:

- `search(query, limit=10)` returns citation-friendly recording search results.
- `fetch(id)` returns one recording document by id.

Write tools must use separate scopes and explicit user consent. Do not extend
`mcp:read` to include mutations.

## Security Rules

- MCP tokens are opaque, hashed at rest, audience-bound to the canonical
  `/mcp` resource, scoped, expiring, refreshable, and revocable.
- Normal WaiComputer browser JWTs are only used to authenticate the consent page.
  They are not accepted as MCP bearer tokens.
- OAuth authorization codes are one-use and PKCE-bound.
- Access tokens must arrive in the `Authorization` header, never query strings.
- The consent page must clearly show the client name, requested scopes, and
  redirect URI before issuing a code.
- Tool outputs must stay privacy-safe: no server logs containing transcript
  text, search queries, filenames, raw emails, or tokens.
- Redirect URIs must use HTTPS, except localhost loopback callbacks used by
  local clients such as Claude Code.

## Client Notes

- ChatGPT Apps/connectors require a public HTTPS `/mcp` endpoint. Configure
  `https://wai.computer/mcp` in ChatGPT Apps/Connectors developer mode, then
  let ChatGPT start the OAuth flow.
- Claude.ai custom connectors use the same `https://wai.computer/mcp` URL.
  Users connect from Claude settings and approve access in WaiComputer web.
- Claude Code can use the committed project `.mcp.json`. Users approve the
  project-scoped server, run `/mcp`, and complete browser login when prompted.
- Cursor can use the committed `.cursor/mcp.json`. Cursor starts OAuth when the
  server is enabled.
- Codex CLI uses `codex mcp add waicomputer --url https://wai.computer/mcp`
  followed by `codex mcp login waicomputer` for OAuth-backed servers.

## References

- MCP Authorization, latest spec: https://modelcontextprotocol.io/specification/latest/basic/authorization
- MCP security best practices: https://modelcontextprotocol.io/specification/latest/basic/security_best_practices
- OpenAI MCP servers for ChatGPT and API integrations: https://platform.openai.com/docs/mcp
- OpenAI Apps SDK authentication: https://developers.openai.com/apps-sdk/build/auth
- Claude.ai remote MCP connectors: https://claude.com/docs/connectors/custom/remote-mcp
- Claude connector authentication: https://claude.com/docs/connectors/building/authentication
- Cursor MCP: https://cursor.com/docs/mcp
