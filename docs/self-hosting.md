# Self-Hosted WaiComputer

WaiComputer supports two deployment modes:

- `wai_cloud`: Wai runs the service at `https://wai.computer`.
- `self_host`: the user runs WaiComputer on their own server and owns the durable database, uploaded files, generated artifacts, backups, logs, and migration archives on that server.

## User Onboarding

The web setup flow at `/setup` lets a non-technical user choose between Wai Cloud and their own VPS. The same controls are available later in Dashboard -> Settings -> Server & Data.

The self-host form asks for:

- server hostname
- VPS public IP
- SSH username
- SSH public key, or a temporary bootstrap password

SSH key auth is preferred. Password bootstrap is accepted only as a temporary setup path and must end with removing root/password access.

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
