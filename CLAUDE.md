# WaiComputer

## Server

- **IP:** <release-host>
- **User:** root
- **Deploy path:** `<remote-root>`
- **OS:** Ubuntu (Hetzner VPS, 4GB RAM, 75GB disk)

## Deployment

**Automatic:** Push to `main` → GitHub Actions runs tests → deploys via SSH.

**Manual:** `VPS_USER=<release-user> ./scripts/deploy-api.sh`

**What happens on deploy:**
1. `git pull --ff-only origin main` on server
2. `docker compose build api web`
3. `docker compose up -d api web caddy`
4. Health checks on api (:8000/health) and web (:3000/login)

## Local Development

**Backend:**
```bash
cd backend
pip install ".[dev]"
docker compose up db -d  # just the database
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

## Project Structure

```
backend/
  app/
    api/          # FastAPI route handlers
    core/         # Auth, security, shared logic
    db/           # Database session, migrations (Alembic)
    models/       # SQLAlchemy models
    main.py       # FastAPI app entry point
    config.py     # Pydantic settings
  docker-compose.yml
  Dockerfile
  Caddyfile       # Reverse proxy config
  alembic.ini
web/
  app/            # Next.js app router pages
  components/     # React components
  lib/            # Utilities, API client
  middleware.ts   # Next.js middleware
scripts/
  deploy-api.sh   # Manual deploy script
.github/
  workflows/
    deploy.yml    # CI/CD pipeline
```

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async), Alembic, Gunicorn + Uvicorn
- **Frontend:** Next.js (App Router), React, TypeScript, pnpm
- **Database:** PostgreSQL 16 with pgvector
- **Reverse Proxy:** Caddy (auto-TLS via Let's Encrypt)
- **Containers:** Docker Compose
- **CI/CD:** GitHub Actions

## Environment Variables (backend/.env)

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (async) |
| `JWT_SECRET` | Secret for JWT token signing (required) |
| `CORS_ORIGINS` | JSON array of allowed origins |
| `DEEPGRAM_API_KEY` | Speech-to-text API |
| `ANTHROPIC_API_KEY` | Claude API |
| `S3_ENDPOINT` | Hetzner Object Storage endpoint |
| `S3_ACCESS_KEY` | S3 access key |
| `S3_SECRET_KEY` | S3 secret key |
| `S3_BUCKET` | S3 bucket name |
| `S3_REGION` | S3 region |
| `RESEND_API_KEY` | Email sending |
| `EMAIL_FROM` | From address for emails |
| `FRONTEND_URL` | Frontend URL for magic links |

## Docker Services

| Service | Container | Port | Network |
|---------|-----------|------|---------|
| db | waicomputer-db | 5432 (internal) | internal |
| api | waicomputer-api | 8000 (internal) | internal, web |
| web | waicomputer-web | 3000 (internal) | web |
| caddy | waicomputer-caddy | 80, 443 | web |
