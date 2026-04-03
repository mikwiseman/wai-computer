# Wai Computer — Full Product Specification

**Version:** 2.1 | **Updated:** 2026-04-01

---

## 1. Concept

### One Brain, Many Hands

Wai Computer is a **Personal AI Operating System**. Not an assistant. Not a chatbot. An operating system where AI is the kernel.

The core insight: users don't need separate apps for recording meetings, tracking habits, building sites, managing commitments, and searching memories. They need **one brain** that knows everything and can do everything — and multiple ways to talk to it.

```
                      ГОЛОС / ТЕКСТ
                           │
                           ▼
                    ┌──────────────┐
                    │   WAI BRAIN   │
                    │               │
                    │  Intent Route │── RECORD → запись встречи
                    │  Agent Loop   │── CREATE → агент/сайт/приложение
                    │  Tool System  │── SEARCH → поиск по всему
                    │  Memory       │── MANAGE → действия, обещания
                    │               │── CHAT → просто разговор
                    └──────┬───────┘
                           │
                     ┌─────┼─────┐
                     ▼     ▼     ▼
                   macOS  Web  Telegram
```

**Formula:** `Chat (voice/text) + Memory (recordings, collections, telegram) + Agents (cron + tools)`

Three things. Not ten. Not five. Three.

- **Chat** — you speak, Wai does.
- **Memory** — Wai remembers everything.
- **Agents** — Wai works while you sleep.

### What Makes This Different

```
Granola/Otter     = only recordings
Claude Code       = only code, for developers
Lovable.dev       = only sites, isolated data
ChatGPT           = no memory between sessions, no deploy
Notion AI         = tied to Notion, no voice, no agents
────────────────────────────────────────────────────
Wai Computer      = recordings + agents + deploy + memory
                    + voice + all channels
                    + for EVERYONE, not just developers
```

**Unique loop:** Record meeting → extract commitments → auto-create reminder agents → agent checks deadline → notifies in Telegram. From voice to action, fully autonomous.

### Anti-Patterns (What We Don't Do)

1. **No model picker.** User doesn't choose Claude/GPT/Gemini. Wai decides.
2. **No "prompt engineering" UI.** No system prompt fields. Describe in words — done.
3. **No dashboard with statistics.** Chat is the home screen. Want stats? Ask Wai.
4. **No tree-view navigation.** No folders-in-folders-in-folders. Chronological feed + search.
5. **No onboarding wizard.** First screen is an empty chat with suggestion chips.
6. **No "processing" details.** User doesn't see "extracting entities..." Just "Thinking..." → result.

### 1.1 Architecture Refresh (Authoritative Override, April 2026)

This specification now treats **session** as the primary runtime object.

- A **session** is the user's active task thread, whether started by text, voice, or recording.
- A **run** is an execution within a session: plan, tool calls, deploy, retries, approvals.
- An **artifact** is any output produced by Wai: transcript, summary, app, site, deploy, checklist, document.
- A **digital agent** is a persistent worker created from a session or artifact.
- A **user app** is a collection-backed product surface with schema, views, connectors, and optional deployment.

This supersedes the older mental model where recordings were the product center. Recordings remain important, but they are now one artifact type inside the broader Wai runtime.

### 1.2 Realtime Voice Layer

Wai now has two distinct voice modes:

1. **Recording mode** — capture meetings, notes, reflections, then generate artifacts such as transcripts, summaries, commitments, and entities.
2. **Conversation mode** — real-time back-and-forth with a live Wai agent that can execute tools, create apps, deploy sites, and manage approvals entirely by voice.

**Provider strategy:**

- `ElevenLabs` is the primary provider for real-time conversation, turn-taking, TTS, realtime STT, and uploaded-audio transcription.
- ElevenLabs is the single active voice and speech-to-text provider.
- Wai business logic, memory, deployments, agents, and connectors stay in Wai backend. ElevenLabs is the real-time interaction layer, not the source of truth.

### 1.3 Reference Patterns We Intentionally Adopt

Wai should borrow the strongest execution patterns from coding-agent products, but adapt them for non-technical users:

- From `OpenCode`: parallel sessions, desktop-native supervision, shareable session links, and the idea that one user may coordinate multiple long-running agents at once.
- From `Claude Code`: skills/slash-command composition, isolated subagent execution for bounded tasks, dynamic context injection, and persistent memory files.
- Wai adaptation: keep the same power under the hood, but present it as `dialog → progress → preview → approve → publish`, with voice as a first-class control surface and apps/deploy/memory as native outcomes, not advanced features.

---

## 2. Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                              INTERFACES                              │
│                                                                      │
│  macOS App     iOS App     Android App     Web App     Telegram      │
│  SwiftUI       SwiftUI     Compose         Next.js     Bot/Webhook   │
│      │            │            │              │            │          │
│      └────────────┴────────────┴──────────────┴────────────┘          │
│                               │                                      │
├───────────────────────────────┼──────────────────────────────────────┤
│                        REALTIME VOICE LAYER                          │
│                                                                      │
│  ElevenLabs Agents / Chat Mode / Realtime STT + TTS                 │
│  - live conversation                                                 │
│  - interruptions + turn-taking                                       │
│  - voice approvals                                                   │
│  - signed URL client auth                                            │
│                                                                      │
├───────────────────────────────┼──────────────────────────────────────┤
│                              WAI CORE                                │
│                                                                      │
│  Session Router → Run Engine → Tool Bridge → Artifact Pipeline       │
│      │               │               │                │              │
│  text/voice      execution       connectors        transcript        │
│  entrypoint      trace/logs      & deploy          app/site/doc      │
│                                                                      │
├───────────────────────────────┼──────────────────────────────────────┤
│                              DATA                                    │
│                                                                      │
│  PostgreSQL + pgvector                                               │
│  Sessions • Runs • Artifacts • Recordings • Apps • Agents           │
│  Commitments • Entities • Chat History • Deployments • Connectors   │
│                                                                      │
├───────────────────────────────┼──────────────────────────────────────┤
│                        BACKGROUND + DELIVERY                          │
│                                                                      │
│  Celery + Redis                                                      │
│  schedulers • digests • deploy jobs • reminders • notifications     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Agent System

```
POST /api/agent/chat  ← user says something (any platform)
        │
   Intent Router
   (pattern match first, Haiku LLM fallback)
        │
   ┌────┴────┬────────┬────────┬──────────┐
   │         │        │        │          │
 SEARCH    BUILD    EDIT    VOICE     CHAT
   │         │        │    SUMMARY      │
   │         │        │        │        │
   ▼         ▼        ▼        ▼        ▼
 Agent Loop (Claude + tool_use, max 10 turns)
        │
   Tool Dispatch
   ┌────┼────┬─────────┬──────────┬───────────┐
   │    │    │         │          │           │
search track create   deploy   extract     web
record commit app      site    entities   search
ings   ment
```

**Intent types:** search, voice_summary, digest, action, build, edit, coach, chat, live_control, deploy

**Tools (7):**
- `search_recordings` — hybrid FTS + semantic search over transcript segments
- `track_commitment` — store a promise with deadline and direction
- `list_commitments` — query open promises
- `extract_entities` — find people, amounts, dates, decisions
- `search_web` — DuckDuckGo instant answers
- `build_app` — generate full app + deploy
- `build_site` — generate landing page + deploy
- `show_run_status` — inspect in-flight execution state
- `approve_action` — voice/text approval for deploys and destructive actions

### Session Runtime

Every user interaction maps to a session:

```
User input (voice/text)
      ↓
Session created or resumed
      ↓
Run started
      ↓
Tool calls / deploys / approvals / artifact creation
      ↓
Result saved back to session + library + agent memory
```

**Session types:**

- `conversation` — live interactive task execution
- `recording` — capture and process spoken content
- `agent_run` — scheduled or background execution

**Artifact types:**

- transcript
- summary
- action_items
- commitment
- user_app
- deployed_site
- deployed_app
- document
- search_result
- run_log

### Collections (User Apps)

Every user-created "app" is a **named collection** of JSONB items with optional schema.

```
User says: "Create a habit tracker"

Wai creates:
1. Collection { name: "habits", schema: { habit: str, completed: bool, date: date } }
2. (Optional) Deployable web bundle with preview URL
3. (Optional) Agent for daily reminders

Data lives in Wai DB → accessible from ALL channels:
- Chat: "meditation done" → Wai adds item
- Web: Apps tab → click → CRUD
- macOS: Apps in sidebar → collection viewer
- Telegram: "habits" → inline checklist
- Deployed app: Full UI at habits.wai.computer
```

**Cross-app intelligence** (the killer feature):
```
User: "Am I more productive on days I meditate?"

Wai:
├→ Habits collection: meditation ✓/✗ per day
├→ Time tracker collection: hours worked per day
├→ Correlation analysis
└→ "In days with meditation you work 29% more (6.2h vs 4.8h)"
```

No other tool can do this. Lovable sites are isolated. Notion AI doesn't know your recordings.

### Digital Agents

Autonomous AI workers on cron schedules:
- Created from natural language: "Check HN for AI news every morning"
- Claude Haiku parses → name, cron, tools, system prompt
- Celery Beat executes on schedule
- Max 5 active per user, auto-disabled after 10 errors
- Results stored in DB, delivered via API or Telegram (Phase 4)

### App Builder (Lovable-Level)

Two modes:
- `build_app(description, app_id, schema)` — full interactive React app connected to Collections API
- `build_site(description, theme)` — static landing page

**Artifact model:** every generated site/app is a deployable bundle, not just a text blob. Preferred format is a small Vite + React + TypeScript project with multiple source files, CSS, and a real build step. Single-file HTML remains only as a fallback for very simple outputs or model degradation.

**Deploy model:** `draft bundle → preview deploy → approval → publish/share`. Wai now supports two Cloudflare edge targets behind one UX:
- `Cloudflare Pages` for simple static sites and compatibility
- `Cloudflare Workers Static Assets` as the preferred target for richer apps/sites and future full-stack expansion

Every generated app/site gets its own Cloudflare resource. Pages uses a dedicated Pages project with preview branch alias + live root URL; Workers uses a dedicated worker name for preview and a stable live worker name for publish. The user still sees the same flow: preview, approve, publish, share, rollback.

**Builder requirements:**
- multi-file source bundle with explicit file map
- real build output (`dist/`) for complex sites
- preview alias for every generated version
- stored bundle metadata so edits, publish, and rollback can target the right artifact
- deployment history persisted per app/site, with rollback to any prior succeeded build

**Multi-turn editing:** User says "change colors" → Wai retrieves the stored bundle from Redis → Claude edits the bundle JSON → preview redeploy.

---

## 3. User Experience

### Three Screens

Instead of 10 pages — **three**. Everything lives inside them.

```
 [💬 Wai]       [📚 Library]     [🤖 Agents]
  Chat            Everything       Autonomous
  with Wai        you've made      workers
  DEFAULT         Browse           Manage
```

Plus a collapsible **📱 Apps** section for user collections.

### Screen: Wai (Chat) — HOME

The primary interface. 90% of time spent here.

Empty state with suggestion chips:
- "Record a meeting"
- "Find what Alex said about pricing"
- "Create a habit tracker"
- "What are my commitments?"

Chips disappear after first message. Then it's pure chat.

**One universal card format** for all results:
```
┌──────────────────────────────────────────┐
│  [icon] Title                   [badge]  │
│                                          │
│  Content (text, list, or preview)        │
│                                          │
│  [Action 1]  [Action 2]                │
└──────────────────────────────────────────┘
```

Recording card, app card, site card, commitment card — same component, different content.

### Screen: Library — BROWSE

Unified chronological feed of everything:
- Recordings (📹)
- Created sites/apps (🌐 / 📱)
- Agent outputs (🤖)
- Telegram messages (💬) [Phase 4]

Filter tabs: All, Recordings, Apps, Sites, Agents

### Screen: Agents — AUTOMATE

List of digital agents with status, schedule, run history. Create via chat or "+" button.

### Screen: Apps — YOUR APP SHELF

This is not a third-party marketplace first. It is the user's own store of things Wai built for them.

- Drafts — started, not yet published
- Live — currently usable apps
- Shared — apps with shareable URL (`unlisted` or `public`)
- Recent — apps the user actually uses

Every app has a simple lifecycle:

`idea in chat → draft app → preview → publish/share → ongoing use → agent automation`

The UX must stay non-technical:

- `Create app`
- `Preview`
- `Publish`
- `Share link`
- `Make private again`

Not:

- `collection schema`
- `deployment target`
- `environment`
- `JSONB item editor`

Under the hood every app still tracks:
- bundle kind
- Cloudflare project name
- preview branch + preview URL
- live URL
- deployment target
- build output metadata

### Interaction Modes

The system should feel simple on the surface but have explicit modes underneath.

- `Talk` — default. User asks, Wai responds and executes.
- `Record` — capture first, process after.
- `Build` — create/edit/publish an app, site, or document.
- `Observe` — watch an agent run, trace, or deployment.

Borrowed from Claude Code / OpenCode, but adapted for non-technical users:

- **Plan before act** for risky work
- **Approvals** before publish, external send, or destructive change
- **Subagents/workers** for parallel tasks, hidden behind simple progress UI
- **Project/session instructions** so apps and agents stay consistent over time
- **Power drawer** for logs, tool calls, files, deploy trace, and connector state

### Cross-Platform Consistency

| | macOS | Web | Telegram |
|---|---|---|---|
| **Chat** | Sidebar → Chat | Wai tab | Chat with bot |
| **Record** | ⏺ button + Option key | ⏺ button | Voice message |
| **Create app** | "create a tracker" | "create a tracker" | "create a tracker" |
| **Search** | Chat / Cmd+K | Chat / Library | "find..." |
| **Notifications** | macOS push [Phase 5] | — | Telegram message |

---

## 4. Platform Specifications

### 4.1 Backend API

**Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL 16 + pgvector, Redis, Celery
**Server:** Hetzner VPS (157.180.47.68), 4GB RAM, 75GB disk
**Domain:** wai.computer
**Proxy:** Caddy 2 (auto-TLS)

**Docker services:** db (pgvector:pg16), redis (7-alpine), api (FastAPI), celery-worker, web (Next.js), caddy

**All endpoints:** See section 6 (API Reference).

**Key metrics:**
- 846 backend tests, 97.7% coverage
- 199 web tests
- CI: GitHub Actions (lint + test + deploy on push to main)

### 4.2 Web Frontend

**Stack:** Next.js 16, React 19, TypeScript 5, custom CSS with CSS variables
**Design:** Warm beige background, teal accent, Space Grotesk font

**Dashboard tabs:**
- Wai (default): chat, realtime voice, approvals, previews, run status
- Library: recordings, searches, docs, sites, app outputs
- Agents: create/list/run/delete digital agents
- Apps: drafts, live apps, shared apps, item CRUD, publish/share controls
- Settings: account, connectors, voice preferences

### 4.3 macOS App

**Stack:** SwiftUI, WaiComputerKit (shared SPM package), ElevenLabs Swift SDK
**Min OS:** macOS 14.2+
**Bundle ID:** is.waiwai.waicomputer
**Signing:** Developer ID Application: WaiWai, LLC

**Architecture:**
- Three-column NavigationSplitView (sidebar + list + detail)
- MenuBarExtra (system tray with status + quick actions)
- Global hotkey dictation (Option key push-to-talk)

**Sidebar structure (target):**
```
Library
  All Recordings, Meetings, Notes, Trash
Folders
  [User-created]
Wai
  Chat (agent-powered)     ← NEW
  Agents (digital workers) ← NEW
  Apps (collections)       ← NEW
Tools
  Search, Settings
```

**Audio capabilities:**
- Microphone capture (AVAudioEngine, 16kHz mono)
- System audio capture (macOS 14.2+, for Zoom/Meet)
- Dual capture (mic + system, mono-mix for diarization)
- Realtime voice conversation via ElevenLabs
- Realtime transcription bootstrap via `/api/transcription/session`
- Uploaded recording transcription via ElevenLabs speech-to-text
- Local WAV backup to Application Support

**New features (Phase 3, in progress):**
- MacAgentChatView: agent chat with tool calling
- MacAgentsView: create, list, run, delete agents
- MacAppsView: browse collections, view/add/delete items
- API methods in WaiComputerKit for all new endpoints

### 4.4 iOS App

**Stack:** SwiftUI, WaiComputerKit (shared SPM package), ElevenLabs Swift SDK
**Min OS:** iOS 17+

**Tab bar:** Wai (chat), Library, Agents, Apps

**Status:** Code exists, project packaging still needs to be finalized in-repo

**P0 features:** Auth, recording, live transcription, agent chat, realtime voice session
**P1 features:** Push notifications, digital agents, user apps
**P2 features:** Offline recording + sync, WidgetKit

Uses same WaiComputerKit → same API methods, same models. WebView for deployed apps.

### 4.5 Android App

**Stack:** Kotlin, Jetpack Compose, ElevenLabs Kotlin SDK
**Status:** New platform line to be created in this repo

P0: Auth, Wai chat, realtime voice session, recording list.
P1: Recording, agents, apps.
P2: Push, offline sync.

### 4.6 Telegram Bot (Planned — Phase 4)

**Status:** Code exists in wai-telegram repo, pending migration

**Architecture:** Webhook handler → intent router → agent loop → response

**Features to migrate:**
- Bot webhook (26+ commands)
- Voice message transcription (provider abstraction, target ElevenLabs)
- Agent chat (same loop as web/macOS)
- Message sync (Telethon client)
- Inline search (@waicomputer_bot in any chat)
- Forward processing ("second brain")
- Site/app building from chat
- Digital agent delivery to Telegram

---

## 5. Data Model

### Database Tables (18 total)

| Table | Key Fields | Status |
|-------|------------|--------|
| `users` | email, password_hash, magic_link_token, default_language | Done |
| `recordings` | user_id, title, type, audio_url, status, duration_seconds, language, folder_id, deleted_at, starred_at | Done |
| `segments` | recording_id, speaker, content, start_ms, end_ms, confidence, embedding(384d) | Done |
| `summaries` | recording_id, summary, key_points(JSONB), decisions(JSONB), topics(JSONB), sentiment | Done |
| `action_items` | recording_id, task, owner, due_date, priority, status, source | Done |
| `highlights` | recording_id, category, title, description, speaker, importance | Done |
| `folders` | user_id, name | Done |
| `entities` | user_id, type, name, metadata(JSONB), embedding(384d) | Done |
| `entity_relations` | source_id, target_id, relation_type, recording_id, context | Done |
| `tags` | user_id, name, color | Done |
| `recording_tags` | recording_id, tag_id | Done |
| `chat_sessions` | user_id, title, recording_ids(JSONB), pinned_at | Done |
| `chat_messages` | session_id, role, content, source_segment_ids(JSONB) | Done |
| `refresh_tokens` | user_id, token_hash, expires_at, device_name | Done |
| `commitments` | user_id, who, what, direction, deadline, status, source_context, completed_at | Done |
| `digital_agents` | user_id, name, description, system_prompt, tools, schedule_type, cron_expression, status, delivery_channel, delivery_target, last_run_at, next_run_at, run_count, last_result | Done |
| `user_apps` | user_id, name, display_name, description, icon, template, schema_def(JSONB), app_url, settings(JSONB), status, visibility, published_at, last_used_at, sort_order | In Progress |
| `app_items` | app_id, data(JSONB), embedding(1536d) | Done |

### Authentication

- Access tokens: JWT HS256, 30-minute expiry
- Refresh tokens: 180-day, SHA-256 hashed in DB, rotated on use
- Cookies: HTTP-only, secure, SameSite=Lax, domain-scoped (.wai.computer)
- Magic links: 15-minute expiry, email via Resend
- Deep links: `waicomputer://auth/verify?token=...` for native apps
- Keychain storage on macOS/iOS (wai_access_token, wai_refresh_token)

---

## 6. API Reference

### Auth (`/api/auth`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/register` | Register with email + password → tokens |
| POST | `/login` | Login → tokens |
| POST | `/magic-link` | Request magic link email |
| POST | `/verify-magic` | Verify magic link → tokens |
| POST | `/refresh` | Refresh access token (body or cookie) |
| POST | `/logout` | Clear cookies + revoke refresh token |
| GET | `/me` | Get current user info |

### Recordings (`/api/recordings`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Create recording (pending upload) |
| GET | `/` | List recordings (limit, offset, type, trashed) |
| GET | `/{id}` | Get detail (segments, summary, actions, highlights) |
| PATCH | `/{id}` | Update title/type/folder |
| DELETE | `/{id}` | Soft delete |
| POST | `/{id}/upload` | Stream audio to S3 |
| POST | `/{id}/finalize` | Trigger transcription |
| POST | `/{id}/transcript` | Ingest segments from client |
| POST | `/{id}/summarize` | Generate AI summary |
| GET | `/{id}/speaker-stats` | Per-speaker analytics |
| GET | `/{id}/related` | Semantically similar recordings |
| GET | `/{id}/keywords` | Top keywords |
| POST/DELETE | `/{id}/star` | Star/unstar |
| GET | `/analytics` | Weekly counts |
| GET | `/digest/weekly` | Aggregated weekly digest |
| POST | `/bulk` | Bulk delete/restore/move |

### Agent Chat (`/api/agent`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | `{message, session_id?, voice_transcript?}` → `{response, intent, model_used, session_id, tool_calls, tokens}` |

### Digital Agents (`/api/agents`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Create from natural language description |
| GET | `/` | List user's agents |
| GET | `/{id}` | Get agent + last result |
| POST | `/{id}/run` | Manual trigger → Celery dispatch |
| PATCH | `/{id}` | Update status (active/paused) |
| DELETE | `/{id}` | Soft-delete |

### User Apps (`/api/apps`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Create app draft (collection-backed) |
| GET | `/` | List apps with item counts, status/visibility filters |
| GET | `/{id}` | Get app details |
| PATCH | `/{id}` | Update schema/settings/URL |
| POST | `/{id}/publish` | Promote preview bundle to live URL and mark app shareable |
| DELETE | `/{id}` | Delete + cascade items |
| GET | `/{id}/items` | List items (paginated) |
| POST | `/{id}/items` | Create item (JSONB data) |
| PATCH | `/{id}/items/{itemId}` | Update item |
| DELETE | `/{id}/items/{itemId}` | Delete item |
| GET | `/{id}/stats` | Aggregated stats |

### Other
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/search` | Hybrid search (FTS + semantic RRF) |
| POST | `/api/chat` | RAG chat with recording context |
| GET/POST/PATCH/DELETE | `/api/chat/sessions/*` | Chat session management |
| GET/PATCH/DELETE | `/api/action-items/*` | Action items |
| GET/POST/DELETE | `/api/entities/*` | Knowledge graph |
| GET/POST/PATCH/DELETE | `/api/folders/*` | Folders |
| POST | `/api/dictation/cleanup` | AI text cleanup |
| POST | `/api/transcription/session` | Provider-backed realtime transcription bootstrap |
| POST | `/api/voice/session` | Provider-backed realtime voice session bootstrap |
| GET/PATCH | `/api/settings` | User settings |
| POST | `/api/settings/change-password` | Password change |
| GET | `/health` | Health check |

---

## 7. Scenarios

### Scenario 1: Record Meeting → Auto-Create Agents

1. User clicks Record (macOS) → mic + system audio
2. Real-time transcript with speaker diarization
3. Meeting ends → Wai generates: summary, key decisions, action items, commitments
4. Wai suggests: "Alex promised proposal by Friday. Create reminder?"
5. One click → agent created (cron: Friday 10:00, tool: search + notify)
6. Friday → agent runs → checks for proposal → sends reminder to Telegram

### Scenario 2: Voice → App

macOS (hold Option) or Web (🎙) or Telegram (voice):
"Create a habit tracker with meditation, exercise, reading"

Wai: creates collection → generates React UI → deploys → returns live URL.

### Scenario 3: Cross-Channel Data

- Morning: macOS dictation "spent 500 on lunch"
- Daytime: web → view expense tracker stats
- Evening: Telegram → agent sends daily report "spent 1740 today, 58% of budget"

### Scenario 4: Search Everything

"What did Alex say about pricing?"

Wai searches:
- Recording transcripts (speakers, timestamps)
- Telegram messages [Phase 4]
- App data (collections)
- Chat history

Returns unified results with source links.

### Scenario 5: Build → Publish → Share

User:
"Create a simple client portal and give me a link I can send"

Wai:
1. creates a draft app
2. generates UI bundle + data model
3. creates a dedicated Cloudflare deploy target for that app/site
4. builds and deploys a preview URL
5. shows preview
6. asks for approval to publish
7. promotes the same bundle to the live URL for that resource
8. marks app `live`
9. returns shareable URL with `private / unlisted / public` visibility

---

## 8. Roadmap

| Phase | What | Status |
|-------|------|--------|
| **1. Unified Brain** | Agent system, Collections API, app builder, Celery/Redis, 17 endpoints, 4 tables | Done |
| **2. Smart UI** | Web: agent chat, agents view, apps view. 73 + 23 new tests | Done |
| **3. Session Runtime** | Sessions, runs, artifacts, approvals, deploy trace | In Progress |
| **4. Realtime Voice** | ElevenLabs voice sessions, signed URLs, voice approvals, provider abstraction | In Progress |
| **5. Apple Clients** | macOS realtime integration, iOS project finalization, shared voice SDK layer | In Progress |
| **6. Android + Channels** | Android app, Telegram migration, app shelf/share flows, MCP/connectors | Planned |
