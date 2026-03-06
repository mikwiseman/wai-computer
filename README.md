# WaiComputer - AI Second Brain

An ecosystem for recording, transcribing, summarizing, and organizing information with AI. Native iOS + macOS apps with a Python cloud backend.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    WaiComputer Architecture                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐      ┌──────────────────┐                 │
│  │    iOS App       │      │   macOS App      │                 │
│  │   (SwiftUI)      │      │   (SwiftUI)      │                 │
│  │  • Microphone    │      │ • Mic + System   │                 │
│  │  • Notes/Voice   │      │ • Zoom/Meet      │                 │
│  └────────┬─────────┘      └────────┬─────────┘                 │
│           │         WebSocket        │                          │
│           │      (Opus audio)        │                          │
│           └────────────┬─────────────┘                          │
│                        │                                        │
│  ┌─────────────────────▼─────────────────────┐                  │
│  │         Python FastAPI Backend            │                  │
│  │              (Self-hosted VPS)            │                  │
│  ├───────────────────────────────────────────┤                  │
│  │  ┌─────────────┐  ┌─────────────────────┐ │                  │
│  │  │  Deepgram   │  │   Claude API        │ │                  │
│  │  │  Nova-3     │  │   Summarization     │ │                  │
│  │  │  Real-time  │  │   Action Items      │ │                  │
│  │  │  Diarization│  │   Entity Extract    │ │                  │
│  │  └─────────────┘  └─────────────────────┘ │                  │
│  └───────────────────────────────────────────┘                  │
│                        │                                        │
│  ┌─────────────────────▼─────────────────────┐                  │
│  │              Data Layer                    │                  │
│  ├───────────────────────────────────────────┤                  │
│  │  PostgreSQL    │  pgvector     │  S3      │                  │
│  │  + FTS         │  Embeddings   │  Audio   │                  │
│  └───────────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

## Features

### iOS App
- Microphone recording with real-time transcription
- Speaker diarization (identify who's speaking)
- AI-generated summaries and action items
- Hybrid search (full-text + semantic)
- Offline support with sync

### macOS App
- All iOS features plus:
- System audio capture (Zoom/Meet via BlackHole)
- Menu bar quick access
- Global keyboard shortcuts

### Backend
- Real-time audio streaming via WebSocket
- Deepgram Nova-3 transcription (<300ms latency)
- Claude API for summarization and entity extraction
- PostgreSQL with pgvector for hybrid search
- S3 for audio storage (Hetzner Object Storage)

## Quick Start

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -e .

# Copy environment file and configure
cp .env.example .env
# Edit .env with your API keys

# Start with Docker (recommended)
docker-compose up -d

# Or run locally (requires PostgreSQL with pgvector)
alembic upgrade head
uvicorn app.main:app --reload

# Run remote API smoke checks (default: https://api.wai.computer)
cd ..
./scripts/api-smoke.sh

# Run continuous QA loops for 8+ hours (default 8h)
# Iterates backend tests + shared tests + remote smoke repeatedly
./scripts/qa-loop.sh

# Example with explicit deploy step after green P0/P1 loops
VPS_USER=your-user DEPLOY_CMD="./scripts/deploy-api.sh" ./scripts/qa-loop.sh

# Recommended detached mode (keeps running in tmux/nohup)
./scripts/qa-loop-start.sh
./scripts/qa-loop-status.sh
./scripts/qa-loop-stop.sh
```

### iOS/macOS Development

```bash
# Open the iOS project
cd ios/WaiComputer
open WaiComputer.xcodeproj

# Or macOS project
cd macos/WaiComputer
open WaiComputer.xcodeproj
```

The apps use the shared `WaiComputerKit` Swift package for common code.

For a signed direct-download macOS installer, use `scripts/build-macos-dmg.sh`. The DMG builder generates a Finder-ready install window with drag-to-`Applications` guidance and can also compose a custom background via `MACOS_DMG_BACKGROUND=/absolute/path/background.png`. For a strict production release, add `MACOS_RELEASE_STRICT=1` so the build fails unless Gatekeeper and notarization pass. Distribution details and notarization options are documented in `docs/macos-distribution.md`.

Before running a release smoke on a developer machine, clear old desktop app state with `scripts/reset-macos-app-state.sh` so Debug/UI-test caches do not contaminate the Release app.

### Web Development

```bash
cd web
pnpm install
pnpm dev

# Run unit tests (100% coverage gate on API/web client modules)
pnpm test:unit

# Run browser automation (Chromium + Firefox + WebKit)
pnpm test:e2e
```

Web app default routes:
- `/login`
- `/register`
- `/dashboard`
- `/auth/verify?token=...`

## Environment Variables

```env
# Required
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/waicomputer
JWT_SECRET=your-secure-secret
DEEPGRAM_API_KEY=your-deepgram-key
ANTHROPIC_API_KEY=your-anthropic-key

# Optional - S3 Storage (Hetzner Object Storage)
S3_ENDPOINT=https://hel1.your-objectstorage.com
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
S3_BUCKET=wai-computer

# Optional - Email
SMTP_HOST=smtp.example.com
SMTP_USER=noreply@waicomputer.com
SMTP_PASSWORD=your-password
```

## API Endpoints

### Auth
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login
- `POST /api/auth/magic-link` - Request magic link
- `POST /api/auth/refresh` - Refresh token

### Recordings
- `GET /api/recordings` - List recordings
- `POST /api/recordings` - Create recording
- `GET /api/recordings/{id}` - Get recording details
- `GET /api/recordings/{id}/transcript` - Get transcript
- `POST /api/recordings/{id}/generate-summary` - Generate AI summary

### Search
- `GET /api/search?q=query` - Hybrid search
- `GET /api/search/semantic?q=query` - Semantic search only

### WebSocket
- `WS /api/ws/audio` - Real-time audio streaming

## WebSocket Protocol

```typescript
// Client → Server (audio)
{ "type": "audio", "data": "<base64>", "timestamp": 123 }

// Server → Client (transcript)
{ "type": "transcript", "text": "...", "speaker": "Speaker 1", "is_final": true }

// Server → Client (status)
{ "type": "status", "status": "ready|processing|error" }
```

## Project Structure

```
wai-computer/
├── backend/              # Python FastAPI
│   ├── app/
│   │   ├── api/          # Routes
│   │   ├── core/         # Deepgram, Claude, auth
│   │   ├── models/       # SQLAlchemy models
│   │   └── db/           # Database config
│   └── tests/
├── ios/                  # iOS SwiftUI app
│   └── WaiComputer/
├── macos/                # macOS SwiftUI app
│   └── WaiComputer/
└── shared/               # Shared Swift package
    └── WaiComputerKit/
```

## BlackHole Setup (macOS System Audio)

To capture audio from Zoom/Meet/etc:

1. Install [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole)
2. Open Audio MIDI Setup
3. Create Multi-Output Device with your speakers + BlackHole
4. Set Multi-Output as system output
5. Select BlackHole as input in WaiComputer

## Tech Stack

- **Frontend**: SwiftUI (iOS 17+, macOS 14+)
- **Backend**: Python 3.11+, FastAPI
- **Database**: PostgreSQL 16 + pgvector
- **Transcription**: Deepgram Nova-3 (or faster-whisper fallback)
- **AI**: Claude API (Anthropic)
- **Audio Codec**: Opus (16kHz, mono)
- **Storage**: S3/Hetzner Object Storage

## License

MIT
