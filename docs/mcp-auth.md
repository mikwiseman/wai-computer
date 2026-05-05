# WaiSay MCP Auth

As of May 5, 2026, the interoperable path for hosted MCP clients is OAuth over
Streamable HTTP, not a direct redirect from JSON-RPC requests.

## Public Endpoints

- MCP endpoint: `https://say.waiwai.is/mcp`
- Protected resource metadata: `https://say.waiwai.is/.well-known/oauth-protected-resource/mcp`
- Authorization server metadata: `https://say.waiwai.is/.well-known/oauth-authorization-server`
- Authorization endpoint: `https://say.waiwai.is/authorize`
- Token endpoint: `https://say.waiwai.is/token`
- Dynamic client registration: `POST https://say.waiwai.is/register`
- Token revocation: `POST https://say.waiwai.is/revoke`

`GET /register` remains a web route. Only `POST` and `OPTIONS` on `/register`
are routed to the API for MCP dynamic client registration.

## User Authorization Flow

1. A client such as ChatGPT, Claude Code, Claude.ai, Cursor, or Codex calls
   `/mcp` without a token.
2. WaiSay returns `401` with a `WWW-Authenticate: Bearer` challenge pointing to
   protected resource metadata and scope `mcp:read`.
3. The client discovers OAuth metadata, dynamically registers itself if needed,
   then starts an authorization-code + PKCE flow with `resource=https://say.waiwai.is/mcp`.
4. WaiSay creates a pending authorization request and redirects the browser to
   `/api/mcp/oauth/consent?request=...`.
5. If the browser is not signed in, WaiSay redirects to
   `/login?returnTo=/api/mcp/oauth/consent?...`.
6. After login, the user approves read-only MCP access. WaiSay redirects back to
   the client callback with an authorization code.
7. The client exchanges the code and PKCE verifier at `/token`.
8. Subsequent MCP calls use `Authorization: Bearer <access-token>`.

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
- Normal WaiSay browser JWTs are only used to authenticate the consent page.
  They are not accepted as MCP bearer tokens.
- OAuth authorization codes are one-use and PKCE-bound.
- Access tokens must arrive in the `Authorization` header, never query strings.
- Tool outputs must stay privacy-safe: no server logs containing transcript
  text, search queries, filenames, raw emails, or tokens.
- Redirect URIs must use HTTPS, except localhost loopback callbacks used by
  local clients such as Claude Code.

## Client Notes

- ChatGPT Apps/connectors require an HTTPS `/mcp` endpoint and follow MCP OAuth.
- Claude Code supports HTTP/SSE MCP OAuth, dynamic client registration, local
  callback ports, and browser login from `/mcp`.
- Cursor supports stdio for local single-user servers and OAuth for remote
  Streamable HTTP/SSE servers.
- Codex CLI uses `codex mcp add <name> --url https://say.waiwai.is/mcp` followed
  by `codex mcp login <name>` for OAuth-backed servers.

## References

- MCP Authorization, latest spec: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- MCP security best practices: https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
- OpenAI Apps SDK authentication: https://developers.openai.com/apps-sdk/build/auth
- OpenAI ChatGPT connector setup: https://developers.openai.com/apps-sdk/deploy/connect-chatgpt
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Cursor MCP: https://docs.cursor.com/en/context/mcp
