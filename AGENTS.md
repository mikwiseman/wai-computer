# WaiComputer

AI Second Brain - audio recording, transcription, and knowledge organization.

## Server

| | |
|---|---|
| **IP** | 157.180.47.68 |
| **SSH** | `ssh root@157.180.47.68` |
| **Deploy path** | `/opt/waicomputer` |
| **OS** | Ubuntu 24.04 (Hetzner VPS, 4GB RAM, 75GB disk) |
| **Domain** | `wai.computer`, `api.wai.computer` (Caddy auto-TLS) |

## Deployment

**Automatic:** Push to `main` -> GitHub Actions runs lint + tests -> deploys via SSH.

Only triggers on changes to: `backend/**`, `web/**`, `scripts/**`, `.github/workflows/deploy.yml`, `.dockerignore`.

**Manual:** `VPS_USER=root ./scripts/deploy-api.sh`

**What happens on deploy:**
1. `git pull --ff-only origin main` on server
2. `docker compose build api web` (in `backend/`)
3. `docker compose up -d api web`
4. `docker compose restart caddy`
4. Health check: API `:8000/health` and web `:3000/login`

**GitHub Secrets:** `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `POSTGRES_PASSWORD`, `JWT_SECRET`, `DEEPGRAM_API_KEY`, `ANTHROPIC_API_KEY`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION`, `RESEND_API_KEY`, `EMAIL_FROM`, `FRONTEND_URL`, `CORS_ORIGINS`

## Local Development

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install ".[dev]"
docker compose up db -d
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd web
pnpm install
pnpm dev
```

**Full stack (Docker):**
```bash
cd backend
docker compose up --build
```

## Testing

**Backend:**
```bash
cd backend
pytest -x -q
pytest -m integration --no-cov
pytest -m slow --no-cov
```
- Lint: `ruff check .`
- Coverage threshold: 83% (`--cov-fail-under=83`)
- Async mode: auto (`pytest-asyncio`)
- Test DB env var: `TEST_DATABASE_URL`

**Focused websocket/upload repro:**
```bash
cd backend
source .venv/bin/activate
env TEST_DATABASE_URL='postgresql+asyncpg://mikwiseman@localhost:5432/waicomputer_test' \
    DATABASE_URL='postgresql+asyncpg://mikwiseman@localhost:5432/waicomputer_test' \
    pytest -q --no-cov tests/test_websocket.py tests/test_recordings_routes.py -k 'upload or websocket or transcript'
```

**Frontend:**
```bash
cd web
pnpm lint
pnpm test:unit
pnpm test:e2e
pnpm test:e2e:ui
```
- Playwright builds and serves the local app on `:3000`
- Live API tests are opt-in with `E2E_LIVE_API=1`

**Shared Swift package:**
```bash
cd shared/WaiComputerKit
swift test -q
```

## Project Structure

```text
backend/
  app/
    api/
      routes/
      websocket.py      # /api/ws/audio (real-time audio streaming)
    core/
      deepgram.py       # Deepgram streaming + REST transcription
      summarizer.py     # Claude-powered summarization
      chat.py           # RAG chat engine
      storage.py        # S3 storage
    db/
    models/
    main.py             # FastAPI app + /health
  tests/
  docker-compose.yml
  docker-compose.local.yml
  Dockerfile
  Caddyfile
  pyproject.toml

web/
  src/
    app/
    components/
    lib/
    proxy.ts
  tests/e2e/
  Dockerfile
  package.json

ios/
macos/
shared/
  WaiComputerKit/       # Shared Swift package (API client, audio, websocket)

scripts/
  deploy-api.sh
  api-smoke.sh
  qa-loop.sh
```

## Runtime Architecture Notes

- **Live recording/transcription currently runs through the native iOS/macOS clients**, not the Next.js web dashboard.
- The shared Swift package (`shared/WaiComputerKit`) owns audio capture, websocket transport, and API access for the native apps.
- The backend websocket endpoint is `WS /api/ws/audio`.
- The backend health endpoint is `GET /health`.
- There is **no runtime MCP integration** in the app codebase; MCP appears only in local dev-tool configuration.

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy (async), Alembic, Gunicorn + Uvicorn |
| **Frontend** | Next.js 16, React 19, TypeScript 5, pnpm 9 |
| **Database** | PostgreSQL 16 + pgvector |
| **Speech-to-text** | Deepgram (`/api/ws/audio`, live) |
| **AI** | Claude (Anthropic) for summaries + chat |
| **Storage** | Hetzner Object Storage (S3-compatible) |
| **Reverse Proxy** | Caddy 2 |
| **Containers** | Docker Compose |
| **CI/CD** | GitHub Actions |

## API Routes

All API routes are prefixed with `/api` except `/` and `/health`.

| Route | Description |
|-------|-------------|
| `POST /api/auth/register` | Register new user |
| `POST /api/auth/login` | Login |
| `POST /api/auth/magic-link` | Request magic link |
| `POST /api/auth/verify-magic` | Verify magic link |
| `POST /api/auth/refresh` | Refresh auth token |
| `GET /api/auth/me` | Get current user |
| `POST /api/auth/logout` | Logout |
| `GET/POST /api/recordings` | List / create recordings |
| `GET/PATCH/DELETE /api/recordings/:id` | Get / update / delete recording |
| `POST /api/recordings/:id/upload` | Upload audio file for transcription |
| `GET /api/recordings/:id/transcript` | Get transcript segments |
| `GET /api/recordings/:id/summary` | Get summary |
| `POST /api/recordings/:id/generate-summary` | Generate summary |
| `GET /api/search` | Hybrid search |
| `GET /api/search/semantic` | Semantic search |
| `GET /api/search/fts` | Full-text search |
| `POST /api/chat` | RAG chat |
| `GET /api/chat/sessions` | List chat sessions |
| `GET /api/chat/sessions/:id` | Get chat session |
| `DELETE /api/chat/sessions/:id` | Delete chat session |
| `GET /api/action-items` | List action items |
| `PATCH /api/action-items/:id` | Update action item |
| `GET /api/entities` | List entities |
| `GET /api/entities/:id` | Get entity |
| `POST /api/entities` | Create entity |
| `DELETE /api/entities/:id` | Delete entity |
| `GET /api/settings` | Get user settings |
| `PATCH /api/settings` | Update user settings |
| `POST /api/settings/change-password` | Change password |
| `GET /` | Root status |
| `GET /health` | Health check |
| `WS /api/ws/audio` | Real-time audio streaming |

## Environment Variables (backend/.env)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL async connection string |
| `JWT_SECRET` | Yes | Secret for JWT signing |
| `CORS_ORIGINS` | No | Allowed origins |
| `DEEPGRAM_API_KEY` | No | Deepgram speech-to-text |
| `ANTHROPIC_API_KEY` | No | Claude summaries + chat |
| `S3_ENDPOINT` | No | Object storage endpoint |
| `S3_ACCESS_KEY` | No | S3 access key |
| `S3_SECRET_KEY` | No | S3 secret key |
| `S3_BUCKET` | No | S3 bucket name |
| `S3_REGION` | No | Object storage region |
| `RESEND_API_KEY` | No | Resend email API |
| `EMAIL_FROM` | No | From address |
| `FRONTEND_URL` | No | Frontend URL for auth redirects |
| `AUTH_COOKIE_DOMAIN` | No | Override shared auth-cookie domain; auto-derived from `FRONTEND_URL` for production domains |

## macOS App

| | |
|---|---|
| **API base URL** | `https://wai.computer` |
| **Xcode project** | `macos/WaiComputer/WaiComputer.xcodeproj` |
| **Shared package** | `shared/WaiComputerKit/` |
| **Bundle ID** | Check Xcode project |
| **Signing** | "Sign to Run Locally" for debug |

## Notes For Agents

- Check `CLAUDE.md` if deeper deployment history or legacy notes are needed.
- Prefer fixing the shared Swift + backend websocket path for recording bugs before touching the web dashboard.
- If validating production, use SSH and inspect `docker logs waicomputer-api` plus `/opt/waicomputer/backend/docker compose ps`.
- Browser auth in production relies on the backend cookie being valid for both `wai.computer` and `api.wai.computer`; if login bounces back to `/login`, check the auth-cookie domain first.
