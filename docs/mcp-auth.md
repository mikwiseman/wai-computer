# WaiComputer MCP Auth

As of May 5, 2026, the interoperable path for hosted MCP clients is OAuth over
Streamable HTTP, not a direct redirect from JSON-RPC requests.

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
