# WaiComputer

AI Second Brain - audio recording, transcription, and knowledge organization.

## Server

| | |
|---|---|
| **IP** | <release-host> |
| **SSH** | `ssh <release-user>@<release-host>` |
| **Deploy path** | `<remote-root>` |
| **OS** | Ubuntu 24.04 (Hetzner VPS, 4GB RAM, 75GB disk) |
| **Domain** | `wai.computer`, `api.wai.computer` (Caddy auto-TLS) |

## Deployment

**Automatic:** Push to `main` -> GitHub Actions runs lint + tests -> deploys via SSH.

Only triggers on changes to: `backend/**`, `web/**`, `shared/**`, `ios/**`, `macos/**`, `android/**`, `scripts/**`, `.github/workflows/deploy.yml`, `.dockerignore`.

**Manual:** `VPS_USER=<release-user> ./scripts/deploy-api.sh`

**What happens on deploy:**
1. `git pull --ff-only origin main` on server
2. CI gates `backend`, `web`, `shared/WaiComputerKit`, `ios`, `macos`, and `android`
3. `docker compose build api web celery-worker` (in `backend/`)
4. `docker compose up -d api web celery-worker caddy`
5. Health checks: API `:8000/health`, web `:3000/login`, celery container health

**GitHub Secrets:** `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `POSTGRES_PASSWORD`, `JWT_SECRET`, `ELEVENLABS_API_KEY`, `ELEVENLABS_CONVERSATION_AGENT_ID`, `ELEVENLABS_RECORDING_AGENT_ID`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`, `FRONTEND_URL`, `CORS_ORIGINS`, `REDIS_URL`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `SENTRY_DSN`, `AUTH_COOKIE_DOMAIN`

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

**Apple apps:**
```bash
xcodebuild -project macos/WaiComputer/WaiComputer.xcodeproj -scheme WaiComputer -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build
xcodebuild -project ios/WaiComputer/WaiComputeriOS.xcodeproj -scheme WaiComputer -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

**Android:**
```bash
cd android
./gradlew --no-daemon testDebugUnitTest assembleDebug
```

## Project Structure

```text
backend/
  app/
    api/
      routes/
      websocket.py      # /api/ws/audio (real-time audio streaming)
    core/
      elevenlabs.py     # ElevenLabs realtime voice + speech-to-text
      transcription.py  # Speech-to-text dispatch
      summarizer.py     # Claude-powered summarization
      chat.py           # RAG chat engine
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
- The backend issues provider-backed realtime transcription sessions via `POST /api/transcription/session` and voice sessions via `POST /api/voice/session`.
- The backend health endpoint is `GET /health`.
- There is **no runtime MCP integration** in the app codebase; MCP appears only in local dev-tool configuration.

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy (async), Alembic, Gunicorn + Uvicorn |
| **Frontend** | Next.js 16, React 19, TypeScript 5, pnpm 9 |
| **Database** | PostgreSQL 16 + pgvector |
| **Speech-to-text** | ElevenLabs (`/api/transcription/session`, live + upload) |
| **AI** | Claude (Anthropic) for summaries + chat |
| **Runtime coordination** | Redis 7 |
| **Deploy** | Cloudflare Pages + Workers |
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
| `POST /api/transcription/session` | Create realtime STT session |
| `POST /api/voice/session` | Create realtime voice conversation session |
| `GET /` | Root status |
| `GET /health` | Health check |

## Environment Variables (backend/.env)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL async connection string |
| `JWT_SECRET` | Yes | Secret for JWT signing |
| `CORS_ORIGINS` | No | Allowed origins |
| `REDIS_URL` | No | Redis runtime coordination |
| `ELEVENLABS_API_KEY` | No | ElevenLabs voice + speech-to-text |
| `ELEVENLABS_CONVERSATION_AGENT_ID` | No | ElevenLabs conversation agent |
| `ELEVENLABS_RECORDING_AGENT_ID` | No | ElevenLabs recording agent |
| `ANTHROPIC_API_KEY` | No | Claude summaries + chat |
| `RESEND_API_KEY` | No | Resend email API |
| `EMAIL_FROM` | No | From address |
| `FRONTEND_URL` | No | Frontend URL for auth redirects |
| `AUTH_COOKIE_DOMAIN` | No | Override shared auth-cookie domain; auto-derived from `FRONTEND_URL` for production domains |
| `CLOUDFLARE_API_TOKEN` | No | Cloudflare deploy automation |
| `CLOUDFLARE_ACCOUNT_ID` | No | Cloudflare account for Pages/Workers deploys |

## macOS App

| | |
|---|---|
| **API base URL** | `https://wai.computer` |
| **Xcode project** | `macos/WaiComputer/WaiComputer.xcodeproj` |
| **Shared package** | `shared/WaiComputerKit/` |
| **Bundle ID** | Check Xcode project |
| **Signing** | "Sign to Run Locally" for debug |

## Notes For Agents

- Check `CLAUDE.md` if deeper deployment history is needed.
- Prefer fixing the shared Swift + backend websocket path for recording bugs before touching the web dashboard.
- If validating production, use SSH and inspect `docker logs waicomputer-api` plus `<remote-root>/backend/docker compose ps`.
- Browser auth in production relies on the backend cookie being valid for both `wai.computer` and `api.wai.computer`; if login bounces back to `/login`, check the auth-cookie domain first.
- Secrets access should be narrow and explicit: avoid broad Keychain enumeration, prefer exact item lookups only when necessary, and use 1Password as the first choice when credentials are available there.
- Apple release versioning is strict: `MARKETING_VERSION` must stay human-readable `major.minor.patch` (for example `1.0.0`, `1.0.1`, `1.1.0`), while `CURRENT_PROJECT_VERSION` must be a plain integer build number (`1`, `2`, `3`, ...), never a timestamp.
- For normal releases, bump the patch version; for larger releases, bump the minor version; major bumps are rare and should be reserved for unusually large changes.
- `CURRENT_PROJECT_VERSION` is globally monotonic for Apple releases and does not reset when `MARKETING_VERSION` changes; for example `1.0.0 (41)` is followed by `1.0.1 (42)`.
- If a bad upload used a timestamp or other wrong numbering scheme, do not adopt it as the new baseline; continue from the last intended sequential integer build number.
