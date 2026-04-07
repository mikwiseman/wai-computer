# WaiSay

AI Second Brain — audio recording, transcription, and knowledge organization.

## Server

| | |
|---|---|
| **IP** | <release-host> |
| **SSH** | `ssh <release-user>@<release-host>` |
| **Deploy path** | `/opt/waisay` |
| **OS** | Ubuntu 24.04 (Hetzner VPS, 4GB RAM, 75GB disk) |
| **Domain** | `wai.computer` (Caddy auto-TLS) |

## Deployment

**Automatic:** Push to `main` → GitHub Actions runs lint + tests → deploys via SSH.

Only triggers on changes to: `backend/**`, `web/**`, `scripts/**`, `.github/workflows/deploy.yml`, `.dockerignore`.

**Manual:** `VPS_USER=<release-user> ./scripts/deploy-api.sh`

**What happens on deploy:**
1. `git pull --ff-only origin main` on server
2. `docker compose build api web` (in `backend/`)
3. `docker compose up -d api web caddy`
4. Health check: api `:8000/health` and web `:3000/login`

**GitHub Secrets:** `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`

**Note:** Deploy keys are disabled (org setting). Server clones via HTTPS with a stored token.

## Local Development

**Backend:**
```bash
cd backend
python -m venv .venv312 && source .venv312/bin/activate
pip install ".[dev]"
docker compose up db -d          # just postgres
alembic upgrade head
uvicorn app.main:app --reload    # runs on :8000
```

**Frontend:**
```bash
cd web
pnpm install
pnpm dev                         # runs on :3000
```

**Full stack (Docker):**
```bash
cd backend
docker compose up --build        # all services on :80
```

## Testing

**Backend:**
```bash
cd backend
pytest -x -q                     # unit tests (excludes integration + slow)
pytest -m integration --no-cov   # live API tests (needs running server)
pytest -m slow --no-cov          # performance/stress tests
```
- Lint: `ruff check .` (line-length 100, rules: E, F, I, N, W)
- Coverage threshold: 78% (`--cov-fail-under=78`), actual coverage ~99%
- Coverage concurrency: `["greenlet", "thread"]` (required for async SQLAlchemy)
- Async mode: auto (pytest-asyncio)
- Test DB env var: `TEST_DATABASE_URL`

**Frontend:**
```bash
cd web
pnpm lint                        # eslint
pnpm test:unit                   # vitest + coverage
pnpm test:e2e                    # playwright (needs running app)
pnpm test:e2e:ui                 # playwright with UI
```
- Coverage thresholds: 75% lines/functions/statements, 60% branches
- E2E tests need a running backend — not run in CI

## Project Structure

```
backend/
  app/
    api/
      routes/           # FastAPI route handlers
        auth.py         # /api/auth/* (register, login, magic links)
        recordings.py   # /api/recordings/* (CRUD, upload)
        search.py       # /api/search/* (hybrid, semantic, fulltext)
        chat.py         # /api/chat/* (RAG chat with transcripts)
        realtime_transcription.py  # /api/transcription/session
        action_items.py # /api/action-items/*
        entities.py     # /api/entities/*
        settings.py     # /api/settings/*
      deps.py           # Dependency injection (get_db, get_current_user)
    core/
      security.py       # JWT, password hashing
      elevenlabs.py     # Voice + speech-to-text
      transcription.py  # Speech-to-text dispatch
      embeddings.py     # sentence-transformers (all-MiniLM-L6-v2, 384d)
      summarizer.py     # Claude-powered summarization
      chat.py           # RAG chat engine
      email.py          # Resend (magic links)
    db/
      session.py        # Async SQLAlchemy session
      migrations/       # Alembic migrations
    models/
      user.py           # User model
      recording.py      # Recording + Segment + Summary
      entity.py         # Entity (people, topics, etc.)
      chat.py           # ChatSession + ChatMessage
    main.py             # FastAPI app + CORS + lifespan
    config.py           # Pydantic settings (reads .env)
  tests/                # pytest (async)
  docker-compose.yml    # Production compose (db, api, web, caddy)
  docker-compose.local.yml
  Dockerfile            # Multi-stage Python build
  Caddyfile             # Reverse proxy config
  alembic.ini
  pyproject.toml        # Dependencies, ruff, pytest config

web/
  src/
    app/                # Next.js App Router pages
      login/page.tsx
      register/page.tsx
      dashboard/page.tsx
      auth/verify/page.tsx
    components/
      AuthForm.tsx      # Login/register form
      DashboardClient.tsx # Main dashboard UI
      ChatPanel.tsx     # Chat with recordings
      VerifyMagicLinkClient.tsx
    lib/
      api.ts            # API client functions
      http.ts           # HTTP client (fetch wrapper)
      types.ts          # TypeScript types
    middleware.ts       # Auth redirect middleware
  tests/e2e/            # Playwright E2E tests
  Dockerfile            # Multi-stage Node build
  package.json          # pnpm 9, Next.js 16, React 19

ios/                    # iOS app (Swift)
macos/                  # macOS app (Swift)
shared/
  WaiSayKit/       # Shared Swift package (API client, models, audio)

scripts/
  deploy-api.sh         # Manual deploy to VPS
  api-smoke.sh          # API smoke tests
  backup-db.sh          # Database backup
  qa-loop*.sh           # QA automation scripts
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy (async), Alembic, Gunicorn + Uvicorn |
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript 5, pnpm 9 |
| **Database** | PostgreSQL 16 + pgvector (vector similarity search) |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2, 384 dimensions) |
| **Speech-to-text** | ElevenLabs (Scribe v2, realtime + upload) |
| **AI** | Claude (Anthropic) for summarization + RAG chat |
| **Email** | Resend (magic link auth) |
| **Deploy** | Cloudflare Pages + Workers |
| **Reverse Proxy** | Caddy 2 (auto-TLS via Let's Encrypt) |
| **Containers** | Docker Compose |
| **CI/CD** | GitHub Actions |

## API Routes

All API routes are prefixed with `/api` in FastAPI. Caddy proxies `/api/*` → `api:8000`.

| Route | Description |
|-------|-------------|
| `POST /api/auth/register` | Register new user |
| `POST /api/auth/login` | Login (email + password) |
| `POST /api/auth/magic-link` | Request magic link email |
| `GET /api/auth/verify` | Verify magic link token |
| `GET /api/auth/me` | Get current user |
| `POST /api/settings/change-password` | Change password |
| `POST /api/auth/logout` | Logout |
| `GET/POST /api/recordings` | List / create recordings |
| `GET/DELETE /api/recordings/:id` | Get / delete recording |
| `POST /api/recordings/:id/summarize` | Generate AI summary |
| `GET /api/search` | Hybrid search (semantic + fulltext) |
| `GET /api/search/semantic` | Semantic search only |
| `GET /api/search/fts` | Fulltext search only |
| `POST /api/chat` | RAG chat with transcripts |
| `GET /api/chat/sessions` | List chat sessions |
| `GET /api/action-items` | List action items |
| `PATCH /api/action-items/:id` | Update action item |
| `GET/POST /api/entities` | List / create entities |
| `DELETE /api/entities/:id` | Delete entity |
| `GET /api/settings` | Get user settings |
| `GET /health` | Health check (not under /api) |
| `POST /api/transcription/session` | Get realtime STT session bootstrap |

## Environment Variables (backend/.env)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL async connection string |
| `JWT_SECRET` | Yes | Secret for JWT signing (`openssl rand -hex 32`) |
| `CORS_ORIGINS` | Yes | JSON array of allowed origins |
| `ELEVENLABS_API_KEY` | No | ElevenLabs voice + speech-to-text |
| `ANTHROPIC_API_KEY` | No | Claude API for summarization + chat |
| `RESEND_API_KEY` | No | Resend email API |
| `EMAIL_FROM` | No | From address for emails |
| `FRONTEND_URL` | Yes | Frontend URL for magic link redirects |

Local dev uses `localhost` URLs. Production `.env` on server uses Docker internal hostnames (e.g., `db:5432`).

## Docker Services

| Service | Container | Internal Port | External Port | Network |
|---------|-----------|--------------|---------------|---------|
| db | waisay-db | 5432 | — | internal |
| api | waisay-api | 8000 | — | internal, web |
| web | waisay-web | 3000 | — | web |
| caddy | waisay-caddy | 80, 443 | 80, 443 | web |

## macOS App

| | |
|---|---|
| **API base URL** | `https://wai.computer` (all builds, no localhost) |
| **Xcode project** | `macos/WaiSay/WaiSay.xcodeproj` |
| **Shared package** | `shared/WaiSayKit/` (SPM, linked by Xcode) |
| **Design system** | `macos/WaiSay/WaiSay/Core/DesignSystem.swift` |
| **Bundle ID** | Check Xcode project for current value |
| **Signing** | "Sign to Run Locally" for debug; needs Apple Developer for release |

**Build:**
```bash
# Debug
xcodebuild -scheme WaiSay -configuration Debug build

# Release archive
xcodebuild -scheme WaiSay -configuration Release archive -archivePath /tmp/WaiSay.xcarchive
```

**Signed DMG (after every build):**
```bash
# Build signed DMG — must run after each macOS build
./scripts/build-macos-dmg.sh
```
- Output: `artifacts/releases/macos/<version>-<build>/WaiSay-<version>-<build>.dmg`
- Signs with Developer ID Application: WaiWai, LLC (<apple-team-id>)
- Universal binary (arm64 + x86_64), hardened runtime enabled
- Set `NOTARY_KEYCHAIN_PROFILE` or `NOTARY_KEY` + `NOTARY_KEY_ID` for notarization
- **Always create a new signed DMG after each macOS build**

**Design tokens:** All colors in `Palette`, all fonts in `Typography`, all spacing in `Spacing` (8pt grid). Accent color is warm amber `(0.82, 0.49, 0.18)`.

## Caddyfile

- `wai.computer` block: auto-TLS, security headers, reverse proxy to api + web
- `:80` block: temporary IP-based access (remove after DNS propagates)
- `/api/*` → `api:8000`, everything else → `web:3000`
- Max request body: 50MB
