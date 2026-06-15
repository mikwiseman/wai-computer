# Self-Hosted WaiComputer

WaiComputer supports two deployment modes:

- `wai_cloud`: Wai runs the service at `https://wai.computer`.
- `self_host`: the user runs WaiComputer on their own server and owns the durable database, uploaded files, generated artifacts, backups, logs, and migration archives on that server.

## Quickstart (one command)

On a fresh Ubuntu VPS, SSH or open the provider console as `root`, then paste:

```bash
curl -fsSLo /tmp/waicomputer-self-host-bootstrap.sh https://raw.githubusercontent.com/mikwiseman/wai-computer/main/scripts/self-host-bootstrap.sh && bash /tmp/waicomputer-self-host-bootstrap.sh
```

The bootstrap script installs `curl`, `git`, `openssl`, `ufw`, Docker Engine,
and the Docker Compose plugin from Docker's official apt repository. It opens
only OpenSSH, `80/tcp`, and `443/tcp` in UFW when you confirm, clones
WaiComputer into `$HOME/wai-computer` (override with `WAICOMPUTER_DIR`), and
then runs the server-local setup script below.

If Docker is already installed, or you are running a local install with Docker
Desktop, use the repository script directly:

```bash
git clone https://github.com/mikwiseman/wai-computer.git
cd wai-computer
./scripts/self-host-setup.sh
```

The script asks for:

1. **Your domain** (point its A/AAAA records at the server first — HTTPS is
   then automatic via Let's Encrypt) or `localhost` for a local install.
2. **Three required API keys** — [Deepgram](https://console.deepgram.com)
   (speech-to-text), [OpenAI](https://platform.openai.com) (companion +
   embeddings), [Cerebras](https://cloud.cerebras.ai) (summaries + dictation
   cleanup).
3. **Two optional keys** — ElevenLabs (realtime voice conversations) and
   Resend (magic-link emails). Skipping one keeps that feature off with a
   clear in-app error; nothing degrades silently.

It then generates strong secrets into `backend/.env.selfhost` (mode 600),
writes a Caddyfile for your domain, builds the stack
(`docker compose -f docker-compose.yml -f docker-compose.selfhost.yml`),
and waits for `/health`. When it finishes, open `https://your-domain/register`
to create the first account. Agents connect at `https://your-domain/mcp`
(copy-paste setup lives in Settings → MCP).

Non-interactive (CI / cloud-init):

```bash
WAI_DOMAIN=brain.example.com \
DEEPGRAM_API_KEY=… OPENAI_API_KEY=… CEREBRAS_API_KEY=… \
./scripts/self-host-setup.sh --yes
```

Updating later: `git pull && ./scripts/self-host-setup.sh` (the existing
`.env.selfhost` is kept; the stack rebuilds in place).

## User Onboarding

The web onboarding flow offers an early "Set up my server" path that opens
Dashboard -> Settings -> Server & Data. The public setup flow at `/setup` lets
a non-technical user choose between Wai Cloud and their own VPS before account
creation. The same controls remain available later in Dashboard -> Settings ->
Server & Data.

Before starting the server check, the in-app checklist asks the user to have:

- a fresh Ubuntu VPS with a public IP
- the temporary root password from the VPS provider, or an SSH public key that
  already works on the server
- required provider keys for Deepgram, OpenAI, and Cerebras

The in-app setup command never includes provider keys. The user enters those
keys only in the VPS terminal when `scripts/self-host-setup.sh` prompts for
them, so Wai Cloud never receives the user's Deepgram, OpenAI, or Cerebras keys.

The self-host form asks for:

- VPS public IP
- SSH username
- SSH public key, or a temporary bootstrap password
- optional server hostname

Provider API keys must stay server-side in `backend/.env.selfhost`; they must
not be put into browser or mobile clients. SSH key auth is preferred. Password
bootstrap is accepted only as a temporary setup path and must end with removing
root/password access.

## Provisioning Checklist

Provisioning must stay explicit. Until an executor has hardened secret handling, the API returns `manual_review_required` and does not run SSH commands.

A complete automated executor must:

- validate hostname, IP address, SSH username, and auth material
- create a non-root deploy user
- install Docker Engine and the Compose plugin from Docker's official apt repository
- account for Docker firewall behavior before exposing ports
- allow only SSH, HTTP, and HTTPS at the host firewall
- configure DNS and HTTPS for the hostname
- deploy the API, web, worker, database, reverse proxy, and persistent volumes
- run `/health` and migration checks
- remove temporary root/password bootstrap access
- show each step and failure to the user without silent fallback

## Data Ownership Scope

The backend data map in `app.core.data_ownership` is the source of truth for migration and export coverage. Tests fail if a durable model table is missing from this registry.

Owned/exportable data includes:

- account profile, preferences, settings, folders, recordings, transcripts, summaries, action items, highlights, tags, people, voiceprints, dictation history, dictionary terms, memory, brain entities, comparison workspaces, commitments, chats, agent runs, MCP metadata, Telegram metadata, usage ledgers, billing history, and document uploads

Server-local or regenerated data includes:

- temporary audio staging files deleted after processing
- short-lived OAuth authorization state
- token hashes and server-bound sessions
- local TLS/ACME state
- model caches
- Telegram Bot API cache

Cloud control-plane data that does not move to a private server includes:

- Wai Cloud pricing catalog, promo-code inventory, staff/admin records, and cloud operator audit logs

## Web Deployment Details

In self-host mode, `PUBLIC_BASE_URL` should be the user's hostname. The backend uses it for auth cookie security/domain resolution and MCP issuer/resource URLs. The web app derives the MCP connect URL from the active browser origin, so a self-hosted dashboard points MCP clients to the user's server.

## References

- Ubuntu Server Security: https://ubuntu.com/server/docs/how-to/security/
- Ubuntu UFW firewall docs: https://ubuntu.com/server/docs/how-to/security/firewalls/
- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Caddy Automatic HTTPS: https://caddyserver.com/docs/automatic-https
