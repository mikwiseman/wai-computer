# WaiComputer - Technical Specification

## Overview

WaiComputer is an AI-powered "Second Brain" platform for recording, transcribing, summarizing, and organizing audio. It consists of a Python FastAPI backend, native iOS and macOS SwiftUI apps, and a shared Swift package (WaiComputerKit).

**Core integrations:**
- **Deepgram Nova-2** - Real-time speech-to-text with speaker diarization
- **Claude API (Sonnet)** - Summarization, entity extraction, sentiment analysis
- **PostgreSQL 16 + pgvector** - Hybrid full-text + semantic vector search
- **Hetzner Object Storage (S3)** - Audio file storage
- **Resend** - Transactional email for magic link authentication
- **Caddy** - Reverse proxy with automatic Let's Encrypt TLS

---

## Architecture

```
                                 +-----------+
                                 |  Deepgram |
                                 |  Nova-2   |
                                 +-----^-----+
                                       |
+-----------+    WSS / HTTPS    +------+------+    internal     +----------+
|  iOS App  | ----------------> |   Caddy     | <------------> | Postgres |
|  macOS App|                   |  (TLS/SSL)  |                | pgvector |
+-----------+                   +------+------+                +----------+
                                       |
                                +------v------+
                                |  FastAPI    |
                                |  (Gunicorn) |
                                +------+------+
                                       |
                              +--------+--------+
                              |                 |
                        +-----v-----+    +------v------+
                        |  Claude   |    | Hetzner S3  |
                        |  (Sonnet) |    | (Object)    |
                        +-----------+    +-------------+
```

---

## Project Structure

```
wai-computer/
|-- backend/                     # FastAPI backend
|   |-- app/
|   |   |-- api/
|   |   |   |-- deps.py              # FastAPI dependencies (auth, DB session)
|   |   |   |-- websocket.py         # WebSocket audio streaming endpoint
|   |   |   |-- routes/
|   |   |       |-- auth.py          # Registration, login, magic link
|   |   |       |-- recordings.py    # CRUD + summarization trigger
|   |   |       |-- search.py        # Hybrid, semantic, FTS search
|   |   |       |-- action_items.py  # Task management
|   |   |       |-- entities.py      # Knowledge graph CRUD
|   |   |       |-- settings.py      # Password change
|   |   |-- core/
|   |   |   |-- deepgram.py          # Deepgram streaming + batch transcription
|   |   |   |-- embeddings.py        # sentence-transformers (all-MiniLM-L6-v2)
|   |   |   |-- summarizer.py        # Claude API summarization + entity extraction
|   |   |   |-- security.py          # JWT, bcrypt, magic link tokens
|   |   |   |-- storage.py           # S3 audio upload/download (Hetzner Object Storage)
|   |   |   |-- email.py             # Resend magic link emails
|   |   |-- db/
|   |   |   |-- session.py           # SQLAlchemy async engine + session
|   |   |   |-- migrations/          # Alembic migrations
|   |   |-- models/
|   |   |   |-- base.py              # SQLAlchemy base model
|   |   |   |-- user.py
|   |   |   |-- recording.py
|   |   |   |-- entity.py
|   |   |-- config.py                # Pydantic settings (env vars)
|   |   |-- main.py                  # FastAPI app, lifespan, health check
|   |-- tests/
|   |-- Dockerfile                   # Multi-stage (builder + production)
|   |-- docker-compose.yml           # 3 services: db, api, caddy
|   |-- Caddyfile                    # Reverse proxy config
|   |-- alembic.ini
|   |-- pyproject.toml
|   |-- .dockerignore
|   |-- .env.example
|
|-- ios/WaiComputer/                 # iOS app (SwiftUI, iOS 17+)
|   |-- App/
|   |   |-- WaiComputerApp.swift     # Entry point, AppState
|   |   |-- ContentView.swift        # Auth gate -> MainTabView
|   |-- Features/
|       |-- Recording/               # RecordingView, RecordingViewModel
|       |-- Library/                 # LibraryView, RecordingDetailView
|       |-- Search/                  # SearchView, SearchViewModel
|       |-- Settings/                # SettingsView
|
|-- macos/WaiComputer/              # macOS app (SwiftUI, macOS 14+)
|   |-- App/
|   |   |-- WaiComputerMacApp.swift  # Entry point, MacAppState, menu bar
|   |-- Features/                    # Same as iOS + system audio capture
|
|-- shared/WaiComputerKit/          # Shared Swift package
|   |-- Sources/WaiComputerKit/
|       |-- Models/                  # All data models (Codable)
|       |-- Network/
|       |   |-- APIClient.swift      # REST API client (actor)
|       |   |-- WebSocketManager.swift # WebSocket client (actor)
|       |-- Audio/
|           |-- MicrophoneCapture.swift  # AVAudioEngine capture
|           |-- OpusEncoder.swift        # Audio encoding
|           |-- AudioManager.swift       # Permission + session management
|
|-- scripts/
|   |-- backup-db.sh                # Daily pg_dump with 14-day retention
|
|-- .github/workflows/
    |-- deploy.yml                   # CI/CD: test -> deploy to VPS
```

---

## Database Schema

**Engine:** PostgreSQL 16 with pgvector extension
**ORM:** SQLAlchemy 2.0 (async via asyncpg)
**Migrations:** Alembic

### Tables

#### `users`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK, server-generated |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL, indexed |
| `password_hash` | VARCHAR(255) | NULLABLE (magic link users have no password) |
| `magic_link_token` | VARCHAR(255) | NULLABLE |
| `magic_link_expires` | TIMESTAMPTZ | NULLABLE |
| `created_at` | TIMESTAMPTZ | server_default=now() |
| `updated_at` | TIMESTAMPTZ | server_default=now(), onupdate=now() |

#### `recordings`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `user_id` | UUID | FK -> users (CASCADE) |
| `title` | VARCHAR(500) | NULLABLE |
| `type` | VARCHAR(50) | NOT NULL (meeting, note, reflection) |
| `audio_url` | VARCHAR(1000) | NULLABLE |
| `duration_seconds` | FLOAT | NULLABLE |
| `language` | VARCHAR(10) | DEFAULT 'en' |
| `created_at` | TIMESTAMPTZ | server_default=now() |
| `updated_at` | TIMESTAMPTZ | server_default=now() |

#### `segments` (transcript chunks)
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `recording_id` | UUID | FK -> recordings (CASCADE) |
| `speaker` | VARCHAR(100) | NULLABLE |
| `content` | TEXT | NOT NULL |
| `start_ms` | INTEGER | NOT NULL |
| `end_ms` | INTEGER | NOT NULL |
| `confidence` | FLOAT | DEFAULT 0.0 |
| `embedding` | VECTOR(384) | NULLABLE, IVFFlat index (lists=100) |
| `created_at` | TIMESTAMPTZ | server_default=now() |

**Indexes:** GIN index on `to_tsvector('english', content)` for full-text search

#### `summaries`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `recording_id` | UUID | FK -> recordings (CASCADE), UNIQUE |
| `summary` | TEXT | NOT NULL |
| `key_points` | JSONB | DEFAULT [] |
| `decisions` | JSONB | DEFAULT [] |
| `topics` | JSONB | DEFAULT [] |
| `people_mentioned` | JSONB | DEFAULT [] |
| `sentiment` | VARCHAR(50) | NULLABLE (positive, neutral, negative, mixed) |
| `created_at` | TIMESTAMPTZ | server_default=now() |

#### `action_items`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `recording_id` | UUID | FK -> recordings (CASCADE) |
| `task` | TEXT | NOT NULL |
| `owner` | VARCHAR(255) | NULLABLE |
| `due_date` | DATE | NULLABLE |
| `priority` | VARCHAR(20) | DEFAULT 'medium' (high, medium, low) |
| `status` | VARCHAR(20) | DEFAULT 'pending' (pending, in_progress, completed, cancelled) |
| `created_at` | TIMESTAMPTZ | server_default=now() |
| `updated_at` | TIMESTAMPTZ | server_default=now() |

#### `entities` (knowledge graph nodes)
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `user_id` | UUID | FK -> users (CASCADE) |
| `type` | VARCHAR(50) | NOT NULL (person, topic, project, organization) |
| `name` | VARCHAR(255) | NOT NULL |
| `metadata` | JSONB | DEFAULT {} |
| `embedding` | VECTOR(384) | NULLABLE, IVFFlat index (lists=100) |
| `created_at` | TIMESTAMPTZ | server_default=now() |
| `updated_at` | TIMESTAMPTZ | server_default=now() |

#### `entity_relations` (knowledge graph edges)
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `source_id` | UUID | FK -> entities (CASCADE) |
| `target_id` | UUID | FK -> entities (CASCADE) |
| `relation_type` | VARCHAR(100) | NOT NULL (mentioned_in, works_on, related_to) |
| `recording_id` | UUID | FK -> recordings (SET NULL), NULLABLE |
| `context` | TEXT | NULLABLE |
| `created_at` | TIMESTAMPTZ | server_default=now() |

#### `tags`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `user_id` | UUID | FK -> users (CASCADE) |
| `name` | VARCHAR(100) | NOT NULL |
| `color` | VARCHAR(7) | NULLABLE (hex color) |
| `created_at` | TIMESTAMPTZ | server_default=now() |

#### `recording_tags` (many-to-many)
| Column | Type | Constraints |
|--------|------|-------------|
| `recording_id` | UUID | FK -> recordings (CASCADE), PK |
| `tag_id` | UUID | FK -> tags (CASCADE), PK |

---

## API Endpoints

Base URL: `https://api.wai.computer`

All endpoints except health/root require `Authorization: Bearer <JWT>` header.

### Health & Root

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| GET | `/` | Root | `{"message": "WaiComputer API", "version": "0.1.0"}` |
| GET | `/health` | Health check (verifies DB) | `{"status": "healthy", "database": "connected"}` |

### Auth (`/api/auth`)

| Method | Path | Auth | Request Body | Response |
|--------|------|------|-------------|----------|
| POST | `/register` | No | `{email, password}` | `{access_token, token_type}` |
| POST | `/login` | No | `{email, password}` | `{access_token, token_type}` |
| POST | `/magic-link` | No | `{email}` | `{message}` (sends email via Resend) |
| POST | `/verify-magic` | No | `{token}` | `{access_token, token_type}` |
| POST | `/refresh` | Yes | - | `{access_token, token_type}` |
| GET | `/me` | Yes | - | `{id, email, created_at}` |

### Recordings (`/api/recordings`)

| Method | Path | Auth | Request / Params | Response |
|--------|------|------|-----------------|----------|
| GET | `/` | Yes | `?skip=0&limit=50&type=meeting` | `[{id, title, type, audio_url, duration, ...}]` |
| POST | `/` | Yes | `{title?, type, language?}` | `{id, title, type, ...}` |
| GET | `/{id}` | Yes | - | Full recording with segments, summary, action_items |
| PATCH | `/{id}` | Yes | `{title?, type?}` | Updated recording |
| DELETE | `/{id}` | Yes | - | 204 No Content |
| GET | `/{id}/transcript` | Yes | - | `[{id, speaker, content, start_ms, end_ms, confidence}]` |
| GET | `/{id}/summary` | Yes | - | `{summary, key_points, decisions, ...}` |
| POST | `/{id}/generate-summary` | Yes | - | Triggers Claude summarization, returns summary |

### Search (`/api/search`)

| Method | Path | Auth | Params | Description |
|--------|------|------|--------|-------------|
| GET | `/` | Yes | `q, limit=20, offset=0` | Hybrid search (FTS + semantic via RRF) |
| GET | `/semantic` | Yes | `q, threshold=0.3, limit=20` | Pure vector similarity search |
| GET | `/fts` | Yes | `q, limit=20` | Pure PostgreSQL full-text search |

**Hybrid Search Algorithm (Reciprocal Rank Fusion):**
```
score = 1/(60 + fts_rank) + 1/(60 + semantic_rank)
```

### Action Items (`/api/action-items`)

| Method | Path | Auth | Request / Params | Response |
|--------|------|------|-----------------|----------|
| GET | `/` | Yes | `?status=pending&priority=high&limit=50` | `[{id, task, owner, ...}]` |
| GET | `/{id}` | Yes | - | Single action item |
| PATCH | `/{id}` | Yes | `{status?, priority?, owner?, due_date?}` | Updated action item |
| DELETE | `/{id}` | Yes | - | 204 No Content |

### Entities (`/api/entities`)

| Method | Path | Auth | Request / Params | Response |
|--------|------|------|-----------------|----------|
| GET | `/` | Yes | `?type=person` | `[{id, type, name, metadata}]` |
| GET | `/{id}` | Yes | - | Entity with relations |
| POST | `/` | Yes | `{type, name, metadata?}` | Created entity |
| DELETE | `/{id}` | Yes | - | 204 No Content |

### Settings (`/api/settings`)

| Method | Path | Auth | Request Body | Response |
|--------|------|------|-------------|----------|
| POST | `/change-password` | Yes | `{current_password, new_password}` | `{message}` |

---

## WebSocket Protocol

**Endpoint:** `WSS /api/ws/audio?token={jwt}&recording_id={uuid}`

### Connection Flow

1. Client connects with JWT token and recording ID as query params
2. Server validates token, verifies recording ownership
3. Server initializes Deepgram streaming session (Nova-2, diarize=true, interim_results=true)
4. Server sends: `{"type": "status", "status": "ready"}`
5. Bidirectional streaming begins

### Client -> Server Messages

**Audio data:**
```json
{
  "type": "audio",
  "data": "<base64-encoded opus/pcm>",
  "timestamp": 1234567890
}
```

**End signal:**
```json
{"type": "end"}
```

### Server -> Client Messages

**Transcript (real-time):**
```json
{
  "type": "transcript",
  "text": "Hello, welcome to the meeting.",
  "speaker": "Speaker 1",
  "is_final": true,
  "start_ms": 0,
  "end_ms": 2500
}
```

**Status updates:**
```json
{
  "type": "status",
  "status": "ready|processing|error",
  "message": "Optional detail"
}
```

### Background Processing

During an active WebSocket session, the server runs concurrent tasks:
1. **Receive loop** - Decode base64 audio, forward to Deepgram
2. **Transcribe loop** - Parse Deepgram responses, forward transcripts to client
3. **Batch save** - Every 5 seconds, flush pending final segments to DB
4. **Embedding generation** - Generate 384-dim embeddings for saved segments

---

## AI Integration

### Deepgram (Real-time Transcription)

**Model:** Nova-2
**Features:** speaker diarization, interim results, VAD, smart formatting
**Audio format:** 16kHz mono, Opus or PCM
**Latency:** <300ms end-to-end

**Streaming config:**
```python
{
    "model": "nova-2",
    "diarize": True,
    "interim_results": True,
    "vad_events": True,
    "utterance_end_ms": 1000,
    "smart_format": True,
    "encoding": "opus",
    "sample_rate": 16000,
    "channels": 1
}
```

### Claude API (Summarization & Extraction)

**Model:** claude-sonnet-4-20250514

**Summarization prompt output:**
```json
{
  "title": "Suggested title",
  "summary": "2-3 paragraph summary",
  "key_points": ["point 1", "point 2"],
  "decisions": [{"decision": "...", "context": "..."}],
  "action_items": [{"task": "...", "owner": "...", "priority": "high|medium|low"}],
  "topics": ["topic 1", "topic 2"],
  "people_mentioned": ["Person A"],
  "sentiment": "positive|neutral|negative|mixed"
}
```

**Entity extraction output:**
```json
[
  {
    "name": "Entity Name",
    "type": "person|topic|project|organization",
    "relations": [
      {"target": "Other Entity", "type": "works_on", "context": "mentioned in Q3 planning"}
    ]
  }
]
```

### Sentence Transformers (Embeddings)

**Model:** all-MiniLM-L6-v2
**Dimensions:** 384
**Normalization:** L2 normalized
**Usage:** Segment embeddings for semantic search, entity embeddings for similarity
**Loading:** Pre-loaded at app startup via lifespan handler
**Index:** IVFFlat (lists=100) on segments.embedding and entities.embedding

---

## Authentication

### Methods

1. **Password auth** - Email + bcrypt-hashed password -> JWT
2. **Magic link** - Email with 15-minute token via Resend -> JWT
3. **JWT** - 7-day expiration, HS256 algorithm, Bearer token in Authorization header

### JWT Payload

```json
{
  "sub": "user-uuid",
  "exp": 1772650216,
  "iat": 1772045416
}
```

### Token Storage (Client)

- iOS/macOS: `UserDefaults` key `"accessToken"`
- Set on login/register, cleared on logout
- Auto-loaded on app launch to restore session

---

## Audio Pipeline

### Capture (Client)

1. `AVAudioEngine` taps input node at 16kHz mono
2. PCM buffer converted to 16-bit little-endian
3. Base64-encoded and sent over WebSocket

### Transport

- WebSocket (WSS) from client to server
- Server decodes base64, forwards raw bytes to Deepgram
- Deepgram returns JSON transcript events

### Storage

- **Bucket:** Hetzner Object Storage (S3-compatible)
- **Key format:** `{user_id}/{YYYY/MM/DD}/{recording_id}.opus`
- **Access:** Presigned URLs (1-hour expiration)
- **Operations:** upload, get_presigned_url, delete

---

## iOS App

**Target:** iOS 17+
**Framework:** SwiftUI
**Base URL:** `http://localhost:8000` (DEBUG) / `https://api.wai.computer` (RELEASE)

### Screens

1. **AuthView** - Login/Register with email + password
2. **MainTabView** - 4 tabs: Record, Library, Search, Settings
3. **RecordingView** - Type picker, animated waveform, live transcript, duration timer
4. **LibraryView** - List of recordings with type filter (All/Meetings/Notes/Reflections)
5. **RecordingDetailView** - Full transcript, summary, action items
6. **SearchView** - Search bar, mode selector (Hybrid/Semantic/Fulltext), scored results
7. **SettingsView** - User email display, logout

### Recording Flow

1. User selects recording type (note/meeting/reflection)
2. Taps record button
3. App requests microphone permission
4. Creates recording on server (POST /api/recordings)
5. Opens WebSocket connection
6. Starts `MicrophoneCapture` -> `OpusEncoder` -> WebSocket
7. Receives real-time transcripts, displays in scrolling view
8. User taps stop
9. Sends "end" message, disconnects WebSocket
10. Recording appears in library

---

## macOS App

**Target:** macOS 14+
**Framework:** SwiftUI
**Window:** 1200x800 default, hidden title bar

### Differences from iOS

- **Menu bar extra** - Brain icon in menu bar, changes to waveform when recording
- **Window style** - `.hiddenTitleBar`
- **System audio capture** - BlackHole 2ch virtual audio device support (for capturing Zoom/Meet audio)
- Audio session: no `.playAndRecord` category (macOS handles differently)

---

## Shared Package (WaiComputerKit)

**Platforms:** iOS 17+, macOS 14+
**Dependencies:** swift-async-algorithms 1.0+

### APIClient (Actor)

Thread-safe REST client with:
- Configurable base URL
- Bearer token authentication
- JSON encoding/decoding (ISO8601 dates with fractional seconds fallback)
- 30-second request timeout
- All CRUD operations for every resource

### WebSocketManager (Actor)

- Manages `URLSessionWebSocketTask`
- `AsyncStream<WebSocketEvent>` for event consumption
- Events: `.connected`, `.transcript(TranscriptMessage)`, `.status(StatusMessage)`, `.disconnected(Error?)`
- Auto-converts `https://` base URL to `wss://`

### Models (all Codable)

- `User`, `TokenResponse`, auth request types
- `Recording`, `RecordingDetail`, `RecordingType` enum
- `Segment` (with computed `formattedTimestamp`)
- `Summary`, `Decision`, `ActionItem` (with Priority/Status enums)
- `SearchResult`, `SearchResponse`
- `Entity`, `EntityDetail`, `EntityRelation`, `EntityType` enum

### Audio

- `MicrophoneCapture` - AVAudioEngine-based, yields `AsyncStream<AVAudioPCMBuffer>`
- `OpusEncoder` - Currently PCM passthrough (production needs libopus C wrapper)
- `AudioManager` - Singleton, permission management, audio session config

---

## Infrastructure

### Production VPS

- **Provider:** Hetzner
- **OS:** Ubuntu (Hetzner Cloud)
- **IP:** 89.167.125.46
- **Domain:** api.wai.computer
- **Swap:** 2 GB (vm.swappiness=10)

### Memory Budget

| Component | RAM |
|-----------|-----|
| OS + Docker | ~350 MB |
| PostgreSQL 16 (shared_buffers=64MB) | ~300 MB |
| FastAPI (1 gunicorn worker + sentence-transformers) | ~560 MB |
| Caddy | ~25 MB |
| **Total** | **~1.24 GB** |
| **Free + swap** | **~700 MB free + 2 GB swap** |

### Docker Compose Services

| Service | Image | Network | Ports | Memory Limit |
|---------|-------|---------|-------|-------------|
| `db` | pgvector/pgvector:pg16 | internal | None (isolated) | 512 MB |
| `api` | backend-api (built) | internal + web | None (internal) | 1.2 GB |
| `caddy` | caddy:2-alpine | web | 80, 443 | 64 MB |

**Network isolation:** DB is only on `internal` network. API bridges `internal` + `web`. Caddy is only on `web`. DB is never reachable from outside Docker.

### PostgreSQL Tuning

```
shared_buffers = 64MB
work_mem = 4MB
effective_cache_size = 256MB
max_connections = 30
```

### Dockerfile (Multi-stage)

- **Stage 1 (builder):** python:3.12-slim, build-essential + libpq-dev, `pip install` with CPU-only PyTorch
- **Stage 2 (production):** python:3.12-slim, libpq5 + curl, non-root `appuser`, copy packages from builder
- **CMD:** gunicorn with 1 UvicornWorker, timeout=120s, keep-alive=65s
- **Image size:** ~2.1 GB (CPU-only PyTorch, no CUDA)

### Caddy (Caddyfile)

```
api.wai.computer {
    reverse_proxy api:8000
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        -Server
    }
    request_body { max_size 50MB }
    log { output file /data/access.log { roll_size 10mb; roll_keep 5 }; format json }
}
```

### Firewall (UFW)

Only ports open: 22 (SSH), 80 (HTTP -> redirect), 443 (HTTPS)

### SSL/TLS

- **Provider:** Let's Encrypt (auto-managed by Caddy)
- **Certificate:** ECDSA via ACME
- **Auto-renewal:** Handled by Caddy before expiration

---

## CI/CD

**File:** `.github/workflows/deploy.yml`
**Trigger:** Push to `main` branch, paths `backend/**`

### Test Job

1. Spin up pgvector:pg16 service container
2. Install Python 3.12 + `.[dev]` dependencies
3. Run `ruff check .` (lint)
4. Run `pytest -x -q` with test DB + JWT_SECRET

### Deploy Job (after test passes)

1. SSH into VPS via `appleboy/ssh-action`
2. `git pull origin main`
3. `docker compose build api`
4. `docker compose up -d api`
5. Verify: `curl -f http://localhost:8000/health`

**Required GitHub Secrets:** `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`

---

## Backups

**Script:** `<remote-root>/scripts/backup-db.sh`
**Schedule:** Daily at 03:00 UTC via cron
**Retention:** 14 days (auto-cleanup of older backups)
**Location:** `<remote-root>/backups/waicomputer_YYYYMMDD_HHMMSS.sql.gz`

**Process:**
1. Read POSTGRES_USER and POSTGRES_DB from .env
2. `docker exec waicomputer-db pg_dump` piped through gzip
3. Verify backup is non-empty
4. Delete backups older than 14 days

---

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (asyncpg) |
| `JWT_SECRET` | Secret for HS256 JWT signing (generate: `openssl rand -hex 32`) |
| `DEEPGRAM_API_KEY` | Deepgram API key for transcription |
| `ANTHROPIC_API_KEY` | Claude API key for summarization |
| `POSTGRES_USER` | Database username (used by docker-compose) |
| `POSTGRES_PASSWORD` | Database password (used by docker-compose) |
| `POSTGRES_DB` | Database name (used by docker-compose) |

### Storage (S3/Hetzner Object Storage)

| Variable | Description | Default |
|----------|-------------|---------|
| `S3_ENDPOINT` | S3-compatible endpoint URL | `""` |
| `S3_ACCESS_KEY` | Access key ID | `""` |
| `S3_SECRET_KEY` | Secret access key | `""` |
| `S3_BUCKET` | Bucket name | `wai-computer` |
| `S3_REGION` | Region | `eu-central` |

### Email (Resend)

| Variable | Description | Default |
|----------|-------------|---------|
| `RESEND_API_KEY` | Resend API key | `""` |
| `EMAIL_FROM` | Sender address | `WaiComputer <noreply@mail.waiwai.is>` |

### Application

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `false` |
| `CORS_ORIGINS` | JSON array of allowed origins | `["http://localhost:3000", "http://localhost:8080"]` |
| `FRONTEND_URL` | Base URL for magic link emails | `http://localhost:3000` |

---

## Security

- **Authentication:** JWT (HS256, 7-day expiry) + bcrypt password hashing (bcrypt<5.0.0)
- **Transport:** TLS 1.3 via Caddy (Let's Encrypt, auto-renewed)
- **Headers:** HSTS (1 year, includeSubDomains, preload), X-Content-Type-Options: nosniff, X-Frame-Options: DENY
- **Database:** Not exposed to host or external network (Docker internal network only)
- **SSH:** Root login disabled, password auth disabled, key-only
- **Firewall:** UFW allowing only 22, 80, 443
- **Secrets:** .env file with 600 permissions, never committed to git
- **Non-root container:** API runs as `appuser` inside Docker
- **Token storage:** Magic link tokens expire in 15 minutes

---

## Scaling Path

When traffic exceeds ~20-30 active users:

1. Resize Hetzner server (upgrade plan)
2. Increase API memory limit to 3 GB, set `--workers 2` in gunicorn
3. Increase PostgreSQL `shared_buffers` to 256 MB
4. `docker compose up -d` - done

---

## Dependencies

### Backend (Python)

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | >=0.109.0 | Web framework |
| uvicorn[standard] | >=0.27.0 | ASGI server |
| gunicorn | >=22.0.0 | Process manager |
| websockets | >=12.0 | WebSocket support |
| pydantic[email] | >=2.0.0 | Data validation |
| pydantic-settings | >=2.0.0 | Environment config |
| sqlalchemy[asyncio] | >=2.0.0 | ORM |
| asyncpg | >=0.29.0 | PostgreSQL async driver |
| alembic | >=1.13.0 | Database migrations |
| pgvector | >=0.2.0 | Vector similarity in PostgreSQL |
| deepgram-sdk | >=3.11.0 | Speech-to-text |
| anthropic | >=0.40.0 | Claude API |
| sentence-transformers | >=2.3.0 | Embedding generation |
| boto3 | >=1.34.0 | S3 storage (Hetzner) |
| python-jose[cryptography] | >=3.3.0 | JWT handling |
| passlib[bcrypt] | >=1.7.0 | Password hashing |
| bcrypt | <5.0.0 | Pinned for passlib compatibility |
| python-multipart | >=0.0.6 | Form data parsing |
| httpx | >=0.26.0 | HTTP client |
| resend | >=2.0.0 | Email sending |

### Dev Dependencies

| Package | Purpose |
|---------|---------|
| pytest | Testing |
| pytest-asyncio | Async test support |
| black | Code formatting |
| ruff | Linting |

### Swift (WaiComputerKit)

| Package | Version | Purpose |
|---------|---------|---------|
| swift-async-algorithms | 1.0+ | Async sequence utilities |

---

## Known Limitations & Notes

1. **Opus encoding** - Client currently sends PCM passthrough; production should integrate libopus via C wrapper for bandwidth efficiency
2. **Embedding model** - Downloads from HuggingFace on first startup; subsequent starts use cache
3. **Single worker** - 1 gunicorn worker because each loads the ~500 MB embedding model; sufficient for async FastAPI with 5 users
4. **Magic link frontend** - `FRONTEND_URL/auth/verify?token=xxx` route must exist in a web frontend or be handled by the native app's deep link handler
5. **Batch segment save** - Segments are flushed to DB every 5 seconds during recording to balance performance vs. durability
6. **BlackHole (macOS)** - System audio capture requires manual setup of BlackHole 2ch virtual audio device
7. **No fallback behavior** - Per project convention, operations fail explicitly with clear errors rather than degrading silently
