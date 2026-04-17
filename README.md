# WaiSay - AI Second Brain

An ecosystem for task-centric dialogue, realtime voice, transcription, app generation, and deployment with AI. Native iOS + macOS apps with a Python cloud backend.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    WaiSay Architecture                      │
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
│  │  │ ElevenLabs  │  │   Claude API        │ │                  │
│  │  │ Realtime    │  │   Summarization     │ │                  │
│  │  │ Voice + STT │  │   App Generation    │ │                  │
│  │  │             │  │   Tool Execution    │ │                  │
│  │  └─────────────┘  └─────────────────────┘ │                  │
│  └───────────────────────────────────────────┘                  │
│                        │                                        │
│  ┌─────────────────────▼─────────────────────┐                  │
│  │              Data Layer                    │                  │
│  ├───────────────────────────────────────────┤                  │
│  │  PostgreSQL    │  pgvector     │  Redis   │                  │
│  │  + FTS         │  Embeddings   │  Agents  │                  │
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
- ElevenLabs realtime voice + speech-to-text
- Claude API for summarization and entity extraction
- PostgreSQL with pgvector for hybrid search
- Redis for agent scheduling and deploy/runtime coordination

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

# Run remote API smoke checks (default: https://say.waiwai.is)
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
cd ios/WaiSay
open WaiSay.xcodeproj

# Or macOS project
cd macos/WaiSay
open WaiSay.xcodeproj
```

The apps use the shared `WaiSayKit` Swift package for common code.

For a signed direct-download macOS installer, use `scripts/build-macos-dmg.sh`. The DMG builder generates a Finder-ready install window with drag-to-`Applications` guidance and can also compose a custom background via `MACOS_DMG_BACKGROUND=/absolute/path/background.png`. For a strict production release, add `MACOS_RELEASE_STRICT=1` so the build fails unless Gatekeeper and notarization pass. Distribution details and notarization options are documented in `docs/macos-distribution.md`.

Before running a release smoke on a developer machine, clear old desktop app state with `scripts/reset-macos-app-state.sh` so Debug/UI-test caches do not contaminate the Release app.

### Android Development

```bash
cd android

# Run the Android unit suite
./gradlew testDebugUnitTest

# Build local debug and release artifacts
./gradlew assembleDebug assembleRelease

# Run lint
./gradlew lint
```

Android app highlights in the parity release:
- onboarding with email auth, magic-link sign-in, and guest mode
- one-tap local-first recording with foreground service protection
- guest recording migration after sign-in via background sync
- library/detail/settings flows aligned with iOS terminology and status handling

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
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/waisay
JWT_SECRET=your-secure-secret
ELEVENLABS_API_KEY=your-elevenlabs-key
ANTHROPIC_API_KEY=your-anthropic-key

# Optional - Email (magic links)
RESEND_API_KEY=your-resend-api-key
EMAIL_FROM=WaiSay <noreply@mail.waiwai.is>
FRONTEND_URL=https://say.waiwai.is
AUTH_COOKIE_DOMAIN=say.waiwai.is
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
wai-say/
├── backend/              # Python FastAPI
│   ├── app/
│   │   ├── api/          # Routes
│   │   ├── core/         # ElevenLabs, Claude, auth
│   │   ├── models/       # SQLAlchemy models
│   │   └── db/           # Database config
│   └── tests/
├── ios/                  # iOS SwiftUI app
│   └── WaiSay/
├── macos/                # macOS SwiftUI app
│   └── WaiSay/
└── shared/               # Shared Swift package
    └── WaiSayKit/
```

## BlackHole Setup (macOS System Audio)

To capture audio from Zoom/Meet/etc:

1. Install [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole)
2. Open Audio MIDI Setup
3. Create Multi-Output Device with your speakers + BlackHole
4. Set Multi-Output as system output
5. Select BlackHole as input in WaiSay

## Tech Stack

- **Frontend**: SwiftUI (iOS 17+, macOS 14+)
- **Backend**: Python 3.11+, FastAPI
- **Database**: PostgreSQL 16 + pgvector
- **Transcription**: ElevenLabs realtime + upload speech-to-text
- **AI**: Claude API (Anthropic)
- **Audio Codec**: Opus (16kHz, mono)
- **Deploy**: Cloudflare Pages + Workers

## License

MIT
