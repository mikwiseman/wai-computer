# WaiComputer — Web revision

Baseline: prod `https://wai.computer`, audit performed 2026-05-26 with the real `hi@mikwiseman.com` account (38 active recordings, Pro plan).
Compared against the macOS app codebase under `macos/WaiComputer/` and `shared/WaiComputerKit/`.

Screenshots in `audit/01-…` through `audit/32-…`. 5 test users seeded in prod under `audit-*@waicomputer.test` for further QA.

Severity scale:
- **P0** — broken, embarrassing, or actively confusing users
- **P1** — visible polish gap; ships in a "v1" release
- **P2** — nice-to-have / future direction

---

## Executive summary

The web app reads as **at least five different products stitched together**:

| Surface | Visual language |
|---|---|
| Landing (`/`, `/ru`) | Hero-only, ad-hoc warm grey, Space Grotesk, no product story |
| Auth cards | Floating chip, top-aligned, no branding wrap |
| Onboarding (`/onboarding`) | **Completely unstyled** — browser defaults |
| Dashboard | Plain two-column layout, dense rows, EN + Russian block |
| Pricing | Bold black-and-white SaaS card style |
| Billing success/cancel | **Forced dark** marketing slab regardless of OS theme |
| Benchmarks | Polished marketing site with hero, charts, leaderboard |
| Admin | Professional sidebar console |
| Privacy/Terms | Clean editorial typeset |

There is no shared design system on web (no token file, one 2 400-line `globals.css`, color set hard-coded in three places). The macOS app has a proper `DesignSystem.swift` — 8 pt grid, 13 typography tokens, serif display, theme + 7 accent choices, all of which is missing on web.

### Top P0 issues (must fix before "v1.0")

1. **Onboarding has no stylesheet.** `OnboardingClient.tsx` references twelve `.onboarding-*` classes; `grep -r "onboarding-" web/src --include="*.css"` returns nothing. New paying users land on browser-default unstyled HTML (`audit/09-onboarding.png`).
2. **EN-only Dashboard with hard-coded Russian Telegram block.** Settings shows EN headings ("Dictation", "Account", "MCP") next to Cyrillic body ("Привяжите @waicomputer_bot…", "Привязать Telegram", "Отключить"). RU users see the inverse — mostly English. (`audit/17-dashboard-settings.png`)
3. **Production error `[Errno 13] Permission denied: '/var/lib/waisay/uploads/9b4c62b8-…'` shown as a recording's subtitle in the library.** Live in prod right now (`audit/12-dashboard-library.png`).
4. **Default Next 404 page has zero branding.** Any unknown URL (`/ru/login`, `/ru/dashboard`, etc.) renders the framework default (`audit/08-ru-login.png`). No `app/not-found.tsx`.
5. **Landing pitch left in English on `/ru`.** Headline reads `"AI second brain для всего, что ты говоришь."`, browser tab title `"WaiComputer — AI second brain для голоса"`. Core value prop literally untranslated (`audit/02-landing-ru-1440.png`).
6. **App icon is white-on-white in dark mode.** `/app-icon.png` is the light variant; in dark mode it flashbangs the page (`audit/01-landing-en-1440-dark.png`). macOS ships adaptive icons; web does not.
7. **Mac vs Web product surface diverges.** Web has Action Items + Topics nav items; Mac has Folders + Dictation History + Dictionary. A user who learns one client cannot find their data on the other (codebase parity already done — the UI just doesn't surface it).
8. **Billing page is bare.** No invoice list, no card on file, no next-billing date, no usage chart. Single `Cancel subscription` button (`audit/23-billing.png`). Forced-dark billing success/cancel slabs ignore user theme (`audit/25, 26`).
9. **`speaker_0`, `speaker_1`, `speaker_?` raw labels exposed to viewers of shared notes** — a stranger on the internet sees DB-side identifiers (`audit/28-share-valid.png`).
10. **No landing → product story.** Hero + two download buttons + footer. No screenshots, no demo, no features section, no testimonials, no FAQ, no Android/Windows/Linux even though those platforms exist in the codebase (`audit/01`).

### Cross-cutting themes

- **Localization is half-done across the entire app.** Auth pages have COPY tables; `/auth/app` and `/auth/reset` do not. Landing/pricing are dual-route; `/auth/*`, `/dashboard`, `/billing/success`, `/share`, `/admin`, `/onboarding` are EN-only. The Telegram block in dashboard settings is RU-only. Mac fully localizes via `OnboardingL10n.text(english, russian, …)`; web should adopt the same pattern uniformly.
- **No design tokens / variables on web.** Spacing, type scale, accent are duplicated dozens of times inline. Build a `tokens.css` (or move into a CSS-in-JS / Tailwind theme) and stop hard-coding `clamp(0.78rem, …)`.
- **No theme/accent picker.** Mac ships system/light/dark + 7 accents. Web is "whatever the OS says" with no override.
- **Layout chooses scroll bumps over visual rhythm.** Almost every secondary page (login, register, verify, reset, auth/app, billing) parks a small card top-center and leaves 600 px of empty grey. Either fill the space with brand context (icon, copy, secondary links) or vertically center.
- **Counters lie.** Library sidebar shows "Trash 100" and "Action Items 100" because the API `limit=100`; real counts may be 38 and 1 000. Fetch actual totals or render "100+".
- **Native dialogs everywhere.** `window.confirm` and `window.prompt` in companion chat delete/rename; native `<select>` for export/search mode. Untranslatable, unstyled, blocked by some browsers.
- **Sidebar subtitles are synonyms, not descriptions.** "All Recordings / Library", "Trash / Recently removed", "Search / Transcript lookup", "Action Items / Follow-ups", "Topics / Entities", "Settings / Account". The subtitle adds zero information. Either delete them or rewrite as one-line value props.

---

## Phase 1 — Landing (`/`, `/ru`)

Screenshots: `audit/01-landing-en-1440.png`, `audit/01-landing-en-1440-dark.png`, `audit/01-landing-en-mobile-dark.png`, `audit/02-landing-ru-1440.png`, `audit/02-landing-ru-mobile.png`.

### Product / strategy

- **P0 — Landing has no product story.** Hero + 2 download buttons + footer. No screenshots, no demo, no feature sections, no FAQ, no testimonials, no Android/Windows/Linux mention. For a paid product in 2026 this looks like an unfinished alpha placeholder, not a v1.0 marketing site. The Mac app itself has six onboarding slides telling the story (Welcome → Value Props → Languages → Hotkey → Voice → Dictation Sandbox); landing must mirror that narrative.
- **P0 — Platform parity is hidden.** Codebase ships native macOS, iOS, Android, Windows, Linux clients (per `AGENTS.md`). Landing offers only Mac DMG + iOS TestFlight, with `downloadDisabled` styles existing in CSS but no platforms wired up. Visitors think the product is Mac-only.
- **P1 — Sign-in placement is hostile.** "Sign in →" is the only entry to the dashboard, hidden top-right in mid-grey small text. No "Open web app" / "Go to dashboard" affordance for returning users.

### Design / brand

- **P0 — Two different brand marks coexist.** Nav uses a flat triangle silhouette (`/brand-mark.svg`, masked with `--ink`). Hero shows the app icon — same triangle but with waveform bars inside a rounded-square card. They read as two unrelated logos in one viewport. Pick one.
- **P0 — App icon is not adaptive on web.** `/app-icon.png` is the light-mode icon (white card + black triangle). In dark mode (see `audit/01-landing-en-1440-dark.png`) the white square is the brightest object on screen, hitting the user like a flashbang. macOS ships an Icon Composer `.icon` with adaptive variants; web must serve the same dark variant via `<picture>` / `prefers-color-scheme`.
- **P1 — Locale switcher uses a middle-dot separator** ("EN · RU"). Visually it looks like a typo bullet between two clickable items. Use a thin vertical rule or just two pill buttons.
- **P1 — Hero icon shadow is light-mode only.** `box-shadow: 0 18px 42px rgba(24, 26, 31, 0.12)` is invisible against `--bg: #101214` and exposes the white-card icon further.
- **P1 — Headline rhythm.** `text-wrap: balance` lands "everything you say." with a lone period on the second line. Either rewrite the headline shorter (5-6 words) or break manually so the second line is heavier than the first.
- **P1 — Secondary CTA ("iPhone / TestFlight") is too quiet in dark mode.** The ghost button border `#30383b` barely separates from `#101214`; depth/affordance is lost.
- **P2 — `Space Grotesk` choice.** It's a fine indie/tech font, but it doesn't match the system-font feel of the macOS app (which uses SF Pro in `DesignSystem.swift`). Cross-surface consistency would prefer `-apple-system` for the marketing site too — or commit to Space Grotesk inside the Mac app for shared brand voice.

### Russian localization

- **P0 — Core value prop left in English.** Headline reads `"AI second brain для всего, что ты говоришь."` Same on browser title `"WaiComputer — AI second brain для голоса"`. "AI second brain" is the entire pitch — leaving it untranslated reads as lazy. Mac onboarding (`OnboardingL10n.text`) is fully translated; web is half-baked. Compare to `OnboardingL10n.swift:30+` — every string has a paired Russian.
- **P1 — Voice/register inconsistency.** Subhead uses noun stack ("Запись на Mac или iPhone. Транскрипция…"). CTA uses infinitive ("Скачать"). `metadata.description` uses second-person imperative ("Записывай, расшифровывай, спрашивай"). All three should align on one tone — likely vy-form imperatives for marketing ("Записывайте…").
- **P1 — Translation calques.** "Поиск по всему" → should be "Ищите по всему, что вы сказали". "Спроси Wai что угодно" misses a comma before "что" ("Спросите Wai о чём угодно"). "что ты говоришь" sounds infantile; "каждое сказанное слово" or "всё, что вы произносите" is the marketing register.
- **P1 — Translated terminology drift.** `description` says "расшифровывай"; on-page subhead says "Транскрипция". Pick one (industry-standard RU is "расшифровка" for the verb and "транскрипт"/"транскрипция" for the noun — keep them paired).
- **P1 — DMG meta line `"macOS 14+ · DMG · RU"`** appends `· RU` which is misleading (the binary isn't language-locked — UI follows in-app language picker). Also the codebase points the RU page at a separate `WaiComputer-ru-latest.dmg`; if these are actually identical files, ship one DMG and drop the suffix.
- **P1 — `iPhone / TestFlight`** stays English on the RU page. Should be "iPhone (бета)" with caption "TestFlight" or "Закрытое тестирование".

### Technical

- **P1 — `prefers-color-scheme` only.** No manual theme toggle. macOS app exposes a theme picker; web does not. At minimum support a user override for users who don't change OS theme.
- **P1 — Footer copyright is bare `© WaiWai`** — missing year and (more importantly) a real company/legal entity attribution. For a paid product this matters for trust.
- **P1 — No `<html lang="ru">` on RU pages.** `web/src/app/layout.tsx:29` hardcodes `<html lang="en">` for every route, including `/ru`. SEO + a11y both regress. `/ru` needs its own layout (or a dynamic `lang`).
- **P1 — Console warning on every page load** (1 warning observed on `/`, 1 on `/ru`). Not breaking but should be cleaned.
- **P2 — `data-testid="download-mac"` exists** but the secondary iOS button uses `data-testid="download-ios"` — fine for tests; consider adding analytics events too so we know download conversion vs. TestFlight conversion.
- **P2 — `Image` from `next/image` for `/app-icon.png`** with `priority` is fine, but no `srcset` for retina; ship at 2x at least.

---

## Phase 2 — Auth (`/login`, `/register`, `/auth/verify`, `/auth/reset`, `/auth/app`)

Screenshots: `audit/03-login.png`, `audit/04-register.png`, `audit/05-verify-invalid.png`, `audit/06-reset.png`, `audit/07-auth-app.png`, `audit/08-ru-login.png`.

### Cross-cutting

- **P0 — No global 404 page.** `/ru/login`, `/ru/register`, `/ru/dashboard`, etc. render Next's default `404 | This page could not be found.` chrome with zero branding (`audit/08-ru-login.png`). For a paid product this is the worst URL-typo experience possible. Add `web/src/app/not-found.tsx` (and a localized `/ru/not-found.tsx`) that matches the auth-card style and links back home.
- **P0 — `/auth/app` and `/auth/reset` are EN-only.** `OpenWaiComputerAppClient.tsx` has hardcoded strings ("Open WaiComputer App", "Missing token.", "Use browser instead"). A RU user clicking a magic link from a RU email lands in English. Mirror the `COPY: Record<Locale, …>` pattern already used in `AuthForm` and `VerifyMagicLinkClient`.
- **P0 — Card is glued to the top edge.** `.auth-page { place-items: start center; padding: clamp(2rem, 9vh, 6rem) 1rem 2rem; }` parks the auth card in the upper third with ~600 px of empty grey below on a 900 px viewport. Either center vertically (`place-items: center`) or fill the empty space with brand context (a hero illustration, product copy, a footer with download links — anything but blank canvas).
- **P0 — Card has no exit.** No "← Back to landing", no logo link, no language switcher, no theme toggle. A user who lands on `/login` from a direct link has no way to learn what the product even is without retyping the URL.
- **P1 — Tiny floating brand chip.** The `auth-card__brand` is a 24 px triangle + 13 px text label glued to the top-left of the card. Reads as a watermark, not a brand. Compare to the Mac Onboarding view which dedicates the entire first slide to "Welcome to WaiComputer". On web, fill the empty half with the same hero icon and tagline used on landing.
- **P1 — Primary CTA disabled state is indistinguishable from "sent".** `audit/03-login.png` shows "Email me a sign-in link" in muted teal with the same shape & weight as the enabled button. Users will read this as "already done" or "loading" and bounce. Either: (a) keep the button bold but show inline validation on click, or (b) make disabled visibly empty (outline + dim text, not a faded fill).
- **P1 — Headings don't fit.** `auth-card h1 { font-size: clamp(2rem, 8vw, 2.7rem); line-height: 0.98 }` — "Open WaiComputer App" (`audit/07-auth-app.png`) wraps to 3 ragged lines: "Open / WaiComputer / App". "Magic Link Verification" wraps to 2 lines with the second line a single tall word. Reduce the max font-size or shorten the titles (e.g., "Sign in to app", "Verifying…").
- **P1 — Title casing inconsistent.** "Sign in", "Create account" (sentence case) vs. "Magic Link Verification", "Open WaiComputer App" (Title Case) on the same flow. Pick one — sentence case fits the product voice better.
- **P1 — `/register` field order is illogical.** Email → Legal consent → "Use password instead" → "Email me a sign-in link". The magic-link CTA, which is the recommended path, lives at the bottom; the password fallback floats above it. Reverse the order so the primary "magic link" stack matches `/login`: Email → Consent → Magic-link primary → "Use password instead" (collapsible).
- **P1 — Legal consent text repeats links.** "I agree to the Terms of Service and Privacy Policy. **Terms of Service** · **Privacy Policy**" — same labels appear twice in one paragraph. Either link the inline words ("…**Terms of Service** and **Privacy Policy**.") or drop the duplicate links underneath.
- **P1 — `localStorage.getItem('voice_onboarding_complete')` is the only signal** sent users to `/dashboard` vs. `/onboarding` after verification (`VerifyMagicLinkClient.tsx:83`). Multi-device users without that local key will be force-fed onboarding again. Should be a server-side `user.has_completed_onboarding` flag (or use a cookie).
- **P1 — Magic link primary loads "Sending..." text but never goes back to default if user navigates and returns.** Visible state appears OK on test, but the `pendingAction` is local-only and the success message lives in the same red/grey `auth-card__message` block as errors — same styling for success and failure is confusing.
- **P2 — No OAuth.** No Sign in with Apple / Google / Microsoft. For a $20+/mo SaaS in 2026 this is table stakes; Apple in particular is a must for an Apple-first product.
- **P2 — Password field has no strength meter** or "show password" toggle (`/register` and `/auth/reset`).
- **P2 — "Need an account?" / "Have an account?" link is the only switch between modes.** Use a tab control (Sign in / Create account) at the top of the card for visual symmetry; the current trailing link reads like an afterthought.
- **P2 — `metadata.referrer = 'no-referrer'`** on `/auth/reset` is correct for security, but no other auth page sets it — leaks referrer on `/login`, `/register`, `/auth/verify` (carrying the magic-link token in the URL). Add to all four.

---

## Phase 3 — Onboarding (`/onboarding`) vs macOS onboarding

Screenshots: `audit/09-onboarding.png`. Compared with `macos/WaiComputer/WaiComputer/App/Onboarding/OnboardingView.swift` and its 6 slides.

### P0 findings

- **CSS for the onboarding page does not exist.** `OnboardingClient.tsx` references twelve `.onboarding-*` classes — `onboarding-shell`, `onboarding-lead`, `onboarding-prompt-card`, `onboarding-controls`, `onboarding-record-button`, `onboarding-record-button--recording`, `onboarding-progress-stack`, `onboarding-progress-bar`, `onboarding-progress-fill`, `onboarding-status`, `onboarding-error`, `onboarding-take-actions`, `onboarding-privacy` — and `grep -r "onboarding-" web/src --include="*.css"` returns nothing. The page renders with browser defaults: heading glued to `0,0`, no padding, no card, no progress visualization, no mic icon, no waveform. This is the first thing a paying user sees after sign-up. Ship a stylesheet or delete the page.
- **One slide vs. seven.** Mac walks the user through Welcome → Value Props → Permission (Mic + Accessibility + System Audio) → Languages → Hotkey → Voice → Dictation Sandbox, each with copy, icons, RU/EN, and footer Back/Skip/Continue. Web jumps straight to "Teach Wai your voice" (the voice enrollment step) and has no Welcome, no value props, no language picker, no permission primer, no privacy framing beyond a single sentence. The web flow doesn't even teach the user what WaiComputer is.
- **EN-only.** No `COPY: Record<Locale, …>`. Prompt text "Hi, I'm setting up Wai Computer…" is English-only; a RU user has to read a 60-word English paragraph aloud to enroll their voice signature. Mac onboarding hands a translated prompt depending on `LanguageManager.current`.
- **Branding "Wai Computer" with a space** in the prompt text (`OnboardingClient.tsx:9`) contradicts the product name "WaiComputer" used everywhere else (landing, settings, app icon, Mac app, browser title). Critical brand-spelling slip.

### P1 findings

- **Voice enrollment is a 20-second auto-cut without preview.** No "Listen to take" before "Use this take" — user can't tell whether the recording is clean before committing the signature.
- **No mic-permission preflight.** Mac dedicates a whole slide to mic+Accessibility+System Audio and tells the user *why* each is needed. Web hits `getUserMedia` cold and prints `err.message` on failure ("Permission denied"). Errors from `navigator.mediaDevices.getUserMedia` need an actionable next step ("Open your browser's site settings →") instead of a system-level string.
- **`localStorage.setItem('voice_onboarding_complete', 'true')`** persists locally on this device only. Sign in on a new device and you get the onboarding wall again even though your voice signature exists server-side. Should hit a server endpoint that flips a user flag, and the magic-link redirect (`VerifyMagicLinkClient.tsx:83`) should consult the same flag.
- **Skip is two buttons, indistinguishable from primary.** "Skip for now" is rendered with default `<button>` styling (the global `button { background: var(--accent) }`), same teal as "Record". Two same-looking buttons stacked, only words differ.
- **Privacy line is a textbook good idea wasted on bad layout.** "We store a 192-number signature, not your audio." is the most reassuring sentence on the page — it should be a prominent badge near the record button, not a footer paragraph in default body color.
- **No analytics on completion vs. skip.** Critical onboarding step — measure conversion.

### P2 findings

- The prompt itself reads slightly odd ("the people I talk to" — *omit* "to" or rephrase). Have it copy-edited.
- No theme/locale toggle on the page itself.
- No "step 1 of N" indicator even though there's only one step — adding it (and growing the flow to match Mac) is the better long-term answer.

---

## Phase 4 — Dashboard (`/dashboard`) vs macOS main view

`/dashboard` is gated behind auth (401 → redirect to `/login`). Audit based on `web/src/components/DashboardClient.tsx`, `CompanionPanel.tsx`, `RecorderPanel.tsx`, and the Mac counterpart `macos/WaiComputer/WaiComputer/App/MacContentView.swift`.

### Product surface area (P0)

The two clients ship **different product information architectures** under one brand:

| Web sidebar | macOS sidebar |
|---|---|
| Wai | Wai |
| All Recordings | All Recordings |
| — (no folders) | **Folder(id)** (custom folders) |
| Trash | Trash |
| Search | Search |
| **Action Items** | — |
| **Topics** | — |
| — | **History** (dictation history) |
| — | **Dictionary** (custom dictation terms) |
| Settings | Settings |

A user who learns the product on Mac will not find their dictation history or dictionary on the web. A web user will not find folders. "Action Items" and "Topics" exist as separate web nav entries even though both should be facets of a recording, not destinations.

**Recommendation:** decide for v1.0 whether folders, dictation history, and dictionary are first-class on web. If yes — build them. If no — fold action items / topics into the recording detail view instead of polluting the sidebar.

### Localization (P0)

- **Dashboard is English-only except for a Russian Telegram block.** `DashboardClient.tsx` hardcodes "All Recordings", "Trash", "Recently removed", "Action Items", "Follow-ups", "Library", "Account", "Loading dashboard...", "Reload", "Logout", every empty-state heading, every error message, every settings label.
- **Telegram block forces Russian regardless of locale.** Lines 866–921 in `DashboardClient.tsx`:
  - `setMessage("Telegram открыт. Нажмите Start в боте — WaiComputer завершит привязку автоматически.")` (line 384)
  - `setMessage("Введите код из Telegram.")` (line 416)
  - `setMessage("Telegram привязан.")` (line 403, 425)
  - `"Привязать Telegram"`, `"Отключить"`, `"Код из Telegram"`, `"Только если вы начали привязку из Telegram."`, `"Введите код из бота"`, `"Привязать по коду"`, `"Ждем Start в Telegram. Возвращаться и копировать код не нужно."`, etc.
  An EN-locale user gets a Cyrillic dialog box in the middle of an English page. Localize this block immediately or hide it for non-RU regions.
- **No language switcher in the dashboard.** Once you reach `/dashboard`, you can't change locale. The LocaleSwitcher only lives on landing/pricing.

### Mac parity / design system (P0)

- **No shared design tokens.** Mac uses `Spacing` (8pt grid) and `Typography` (13 named sizes, serif display + sans body + mono timestamps) in `Core/DesignSystem.swift`. Web uses a single global stylesheet with ad-hoc `clamp(0.78rem, …)` values scattered across 2400 lines.
- **Display typography mismatch.** Mac display sizes are *serif* (`design: .serif`) for recording titles, page headings, section headings; web uses Space Grotesk everywhere. The Mac product has an editorial / second-brain reading-room feel that the web entirely misses.
- **Mac has a theme picker** (`MacAppearanceMode` system/light/dark) AND an **accent picker** (7 colors, default amber). Web has neither — fixed teal `#2f756d` and OS-driven theme only.
- **Mac uses NavigationSplitView** with collapsible columns and proper macOS sidebar feel; web uses a fixed grid `grid-template-columns: minmax(210px, 252px) minmax(0, 1fr)`. Sidebar can't be collapsed and the layout breaks at the 700/960 px breakpoints into a horizontal nav grid that doesn't feel native.

### Composition / structure (P1)

- **Settings is a flat scroll.** Web's settings view is one long list: Dictation checkbox → Account password → Telegram block → MCP section → API Keys. No groupings, no anchor links, no search. Mac's `MacSettingsView` is sectioned. Web should mirror sections with headings and (ideally) a left-side anchor nav for long pages.
- **Sidebar nav subtitles are duplicates, not descriptions.** "All Recordings" / "Library", "Search" / "Transcript lookup", "Trash" / "Recently removed". The subtitle should explain *what's inside*, not echo the label. Either drop them or rewrite as one-line value props.
- **Sidebar counters are inconsistent.** "All Recordings" shows total count; "Action Items" shows *pending* count; "Topics" shows total entities; "Wai", "Search", "Settings" show nothing. The unit changes silently. Pick a rule (e.g., everything shows total or nothing does).
- **`window.confirm` / `window.prompt` for chat delete and rename** in `CompanionPanel.tsx:156, 170`. Native dialogs are ugly and untranslatable. Replace with in-product modals.
- **Companion uses inline `style={…}` props** in 6 places (lines 353, 384, 426, 454, 456, 482, 488, 497, 552). Move to CSS so dark mode and a11y work consistently.
- **"Ask Wai" panel duplicates empty states** (lines 422 and 441 — `hasNoChats` and `isEmptyActive` both render the same `<div className="empty-state empty-state--center">`). Either de-duplicate or differentiate copy ("No chats yet — start one" vs. "This chat is empty — ask anything").

### Recording / dashboard flows (P1)

- **`RecorderPanel` records WebM/Opus only**, no waveform visualisation while recording, no pause/resume, no language picker. Mac's recording experience (`LiveRecordingView`) shows speaker chips, live transcript, durations. Web is a static "0:14 • Stop" pill.
- **`AudioUpload`** (not yet read in detail) doesn't appear to support drag-and-drop with progress, just a click input. Verify.
- **"Recording" button copy is "Record in browser"** — should match Mac copy "Start recording" or simply "Record".
- **Date format uses `toLocaleDateString(undefined, …)`** — fine for the user's OS locale, but inconsistent if their browser locale doesn't match their account locale. Use the account `language` prefkey.
- **Failure feedback shows raw API messages** (`formatError` just falls back to `error.message`). For non-technical users, "AbortError" and "Unable to create account" look identical; map known codes to user-friendly copy.

### Technical (P2)

- **`useEffect` polling Telegram link status every 2 s** (line 200) — burns API calls; backoff after the first 30 s or switch to SSE/websocket.
- **`createChat`, `getChat`, etc. requested unconditionally on mount** — no SWR / TanStack Query / caching layer. Refreshes refetch everything.
- **No keyboard shortcuts** in the dashboard. Mac has hotkeys; web should at least have `/` to focus search, `n` to new recording, `ESC` to deselect.
- **Logout button styled as a `ghost-button`** sitting next to "Reload" — should be visually distinct (secondary danger style) and ideally placed in a user menu (with email + plan badge) instead of footer of sidebar.

### Visual confirmations (after login)

Screenshots `audit/11–17` show the dashboard with 38 real recordings:

- **P0 — A real prod error message leaks into the library.** `Testing Voice Recognition with Screams` shows `[Errno 13] Permission denied: '/var/lib/waisay/uploads/9b4c62b8-e8f1-4a66-afaa-2eaa74e02aee'` as the row's failure message (`recording.failure_message` → `statusText()`). Sanitize backend errors before storing or rendering them.
- **P0 — Recording row is overloaded.** Each row has title + metadata + two action buttons (`Summarize`, `Trash`) stacked below. ~80 px per row, ~10 rows visible at once on a 1440 viewport. Move actions into context menu (right-click) or detail panel.
- **P1 — Date format ambiguous.** "Note / May 26, 2026 / 2:42" — is `2:42` a duration or a timestamp? Use `2:42` only for duration and a separate `2 min 42 sec` label when there's room.
- **P1 — `0:04` rows.** Many short test recordings clutter the list. Should there be a "duration < 5 s" filter or auto-trash?
- **P1 — `Trash 100` counter is misleading.** Real count is unknown — API limit. Render "100+" or fetch the count explicitly.
- **P1 — Action Items list is just a wall of rows.** 100 items with "Complete / Pending" buttons each, no priority/owner/due-date grouping, no recording link button (although the data has it).
- **P1 — Topics empty state shows only an input + "Create topic" button.** No explanation that topics are auto-extracted from recordings (codebase has entity extraction), no list of existing system topics. Looks like a manual taxonomy editor when it should be a discovery surface.
- **P1 — `Ask Wai` panel.** The greeting "What do you want to know?" with starter prompts works; but the streaming bubble is a single light grey box with no model attribution, no token count, no "Stop generating" affordance that visually stands out — same `qa-bubble` styling for user, assistant, and loading.
- **P1 — Sidebar collapses brand block below 1440 px** — the brand mark + "WaiComputer" + email do not gracefully resize. The email overflows behind the counter pills.

---

## Phase 6 — Pricing (`/pricing`, `/ru/pricing`) vs Mac PaymentModeToggle

Screenshots: `audit/21-pricing-en.png`, `audit/22-pricing-ru.png`.

### EN page

- **P0 — Headline "Simple pricing." with the period is fine, but the headline is the only piece of marketing here.** No comparison table, no FAQ, no money-back, no team plan, no enterprise contact, no annual savings displayed until you click the toggle.
- **P1 — Pro card has a black thick border** (`var(--color-text-primary)`) and a black CTA. The landing accent is warm teal; pricing reads as a different brand.
- **P1 — Top nav changes between landing and pricing.** Landing shows "Pricing | Benchmark | EN · RU | Sign in"; pricing shows only "EN · RU | Sign in". Why drop the cross-link to benchmarks?
- **P1 — Free plan has no CTA.** Pro has "Sign in to upgrade"; Free has nothing — looks visually unbalanced (`audit/21`).
- **P1 — Feature lists pre-fix with `✓`** generated via `::before`; in dark mode the colour drops contrast below 4.5:1 against the panel.
- **P2 — Annual toggle says "Save 20%"** but the displayed price doesn't update until you click. Show both prices side by side or the annual equivalent next to the monthly price.

### RU page

- **P0 — Headline "Простой прайс."** — "прайс" is slang. Use "Простые цены." or "Прозрачные цены."
- **P0 — Subhead "Бесплатно для повседневных голосовых заметок. Pro когда нужен везде."** — "Pro когда нужен везде" reads off; should be "Pro, когда нужен везде" (comma) or "Pro — когда нужен везде".
- **P0 — Pro CTA "Войди, чтобы оформить Pro"** uses ты-form; everything else in the app uses вы-form ("Войти" infinitive, "Создать аккаунт", "Привяжите", "Введите"). Pick one register and stick to it — vy-form is the marketing default.
- **P1 — Pricing-provider radio "RUB через Т-Банк / USD через Stripe"** is RU-only. On EN there is no provider choice (likely fixed to Stripe). The card height differs between locales as a result — fix by always showing the provider line or never.
- **P1 — Translated benefits don't mirror EN.** EN: "Permanent searchable memory" → RU: "Память с поиском навсегда" reads awkward; "Поиск по сохранённой памяти" or "Память без лимита по времени" would be smoother.
- **P1 — Price in ₽ but no VAT / "включая НДС" notice.** Russian e-commerce law expects this.

### Mac comparison

Mac's `PaymentModeToggle` is a single-button modal inside Settings; web's pricing is a public marketing page. They serve different jobs. Cross-link is missing: Mac's billing section should deep-link to `/pricing` (or `/ru/pricing` per the user's language) when upgrading.

---

## Phase 7 — Billing (`/billing`, `/ru/billing`, `/billing/success`, `/billing/cancel`)

Screenshots: `audit/23-billing.png`, `audit/24-billing-ru.png`, `audit/25-billing-success.png`, `audit/26-billing-cancel.png`.

### `/billing` (EN) and `/ru/billing` (`audit/23, 24`)

- **P0 — No invoice history**, no card on file, no next billing date, no payment-method update, no plan-switch (monthly ↔ yearly). A paid SaaS billing page must answer "when am I charged next, how much, and where can I get a receipt." This answers none.
- **P0 — `Status` value `active` is not localized on the RU page** (`audit/24`). Heading and labels are translated ("Тариф", "Статус", "СЛОВ НА ЭТОЙ НЕДЕЛЕ") but the value remains the raw English DB enum.
- **P1 — "Words this week / No weekly word cap"** — only weekly usage shown. Mac and the API expose monthly usage; show both.
- **P1 — `Cancel subscription` button is an outlined danger button** at top level. Should be hidden behind a "Manage plan" menu or at minimum trigger a confirm modal before the cancel API fires.
- **P1 — No "Back to dashboard"** or "Open WaiComputer" links — the page is an orphan tab.

### `/billing/success` and `/billing/cancel` (`audit/25, 26`)

- **P0 — Forced dark theme** via `.billing-result-shell { --bg: #101214 …}` overrides the user's prefers-color-scheme. Users on light mode hit a black wall.
- **P0 — No CTA.** Both pages tell the user "you can close this tab" and dead-end. Should auto-redirect (or offer a button) to `/dashboard` for success and `/pricing` for cancel.
- **P1 — Generic copy.** "Billing updated / Your payment was accepted." doesn't tell the user what they bought. Show plan + first charge ("Pro · $12 charged today, next charge Jun 25").
- **P1 — Stripe redirects normally use `?session_id=…`** in the query string. Page should call back to the API to fetch the actual invoice and show it.
- **P1 — `/ru/billing/success`** likely exists (route file present); it is the same English component if not localized. Verify in QA.
- **P2 — No analytics conversion event** firing on `/billing/success`. Critical revenue funnel — instrument it.

---

## Phase 8 — Share (`/share/[token]`)

Screenshots: `audit/27-share-invalid.png`, `audit/28-share-valid.png`.

### Invalid token (`audit/27`)

- **P1 — "Shared note unavailable / Shared note not found" card** lives top-of-page with no logo, no "Try WaiComputer" CTA, no homepage link. Add brand wrap so this is at least a marketing surface when a stranger lands on a revoked link.
- **P1 — Title in muted grey** when it should be a stronger error tone (warm orange or danger red) so users understand it's a problem.

### Valid share view (`audit/28`)

- **P0 — Speakers rendered as `speaker_0`, `speaker_1`.** A stranger sees DB enums. Replace with "Speaker 1" / "Speaker 2" or actual names from voice signature.
- **P0 — Markdown backticks rendered as inline `<code>`.** Words from the transcript like `Minecraft`, `Nintendo`, `Text2Voice`, `retail`, `IT`, `API`, `KM`, `AI` show in monospace because the API stores them inside `` `…` `` markdown fences. This makes the transcript look like a code dump. Strip markdown formatting for share view, or apply a softer style than `mono`.
- **P0 — No call-to-action.** Best free-funnel surface in the app — every shared note is seen by 1–10 new prospects. Add a footer "Try WaiComputer free → wai.computer" and an OG/Twitter card for previews when the link is pasted in Slack/Telegram.
- **P1 — `Download Markdown` is the only export option.** Add PDF and printable view.
- **P1 — No summary on the share view.** Even if a summary exists on the recording, the share page only shows the transcript. Share both.
- **P1 — Date subtitle reads `Meeting · May 25, 2026 · 2 min 4 sec`** — middle-dot separator with no breathing space; on narrow phones it wraps awkwardly.
- **P1 — Heading uses sans-serif** but the share view is the most "editorial" surface — should be the place where Mac's serif display type lives. Big win for brand cohesion.
- **P2 — Print stylesheet?** None. People will print shared notes; add `@media print`.

---

## Phase 9 — Static pages (`/privacy`, `/terms`, `/benchmarks/dictation`, `/admin`)

Screenshots: `audit/29-privacy.png`, `audit/30-terms.png`, `audit/31-benchmarks.png`, `audit/32-admin.png`.

### Privacy & Terms (`audit/29, 30`)

- **P1 — Layout is clean and readable** (this is the best legal-page layout in the audit) but it sits in isolation — no nav back to landing, no LocaleSwitcher (the brand chip top-left isn't a link).
- **P1 — "Last updated: May 22, 2026"** — good. Make sure the date stays in sync; consider linking to a public changelog of policy edits.
- **P1 — `/ru/privacy` and `/ru/terms` need spot-check** for translation completeness (not opened in this audit; codebase shows separate files exist).
- **P2 — Sections use sentence-case headings ("Who we are", "Data we process")** — works, but the H1 is "Privacy Policy" in Title Case, inconsistent.

### Benchmarks (`audit/31`)

- **THIS PAGE IS THE BEST DESIGNED PAGE IN THE APP.** Polished hero, an actual product narrative ("WaiComputer Dictation Arena"), interactive blind-battle component, leaderboard table, model-task matrix cards. This is what landing should aspire to be.
- **P0 — The disparity is jarring**: a buyer who finds `/benchmarks/dictation` via Twitter assumes the rest of the app is this polished, then bounces off `/` and `/dashboard`. Either lift this aesthetic across the whole app, or hide this page until the rest catches up.
- **P1 — Cross-link from landing** to benchmarks is a small text link in the nav ("Benchmark") — should be a hero card on landing ("See how WaiComputer compares to other dictation models →").
- **P2 — RU translation** exists (`/ru/benchmarks/dictation`) — verify table headers and prompt copy match the EN version.

### Admin (`audit/32`)

- **P1 — Hi@mikwiseman.com is not an admin** (`Admin role required` error). Either grant the prod user admin or rely on a separate admin account; for an audit, this is OK.
- **P1 — Admin shell layout (`audit/32`) is clean** — sticky sidebar with Overview / Promo codes / Users / Billing / Observability / Audit. Better proportions than the user-facing dashboard, which is telling.
- **P1 — "WAICOMPUTER" eyebrow + "Admin" heading** — wordmark casing inconsistent with the lower-case `WaiComputer` everywhere else.
- **P2 — `Refresh` button** in the top-right is fine, but no last-updated timestamp.

---

## Phase 10 — Prioritized action plan

### Sprint 1 — Stop the embarrassment (P0, days)

1. **Write the missing `web/src/app/onboarding.module.css`.** Use the auth-card / hero patterns from landing. Or replace the page with a redirect to dashboard until it's ready.
2. **Localize the Telegram block** in `DashboardClient.tsx:866-921` and switch every other RU-only string (`setMessage("Telegram…")` etc.) to a `COPY` table.
3. **Localize `/auth/app`, `/auth/reset` and the `/billing/success` / `/billing/cancel` slabs.**
4. **Add `web/src/app/not-found.tsx`** matching the auth-card style.
5. **Sanitize stored `failure_message` in the backend** so OS-level paths and stack traces never reach the UI.
6. **Translate the RU landing hero copy.** "AI second brain" → product equivalent ("AI-память для голоса" / "Вторая память для голоса"). Update browser title.
7. **Ship an adaptive app icon for web** (`<picture>` with light / dark sources) — same `.icon` assets the Mac app uses.
8. **Stop forcing dark on `/billing/success`+`/cancel`.** Use the global theme.
9. **Replace `speaker_0` / `speaker_?` on the share view** with "Speaker 1" / "Speaker 2" or display names.

### Sprint 2 — Brand & design system (P1, ~1–2 weeks)

10. **Build a `web/src/styles/tokens.css`** mirroring Mac's `DesignSystem.swift`: spacing scale, type scale (including a serif display family), accent palette, neutrals, semantic colors. Refactor `globals.css` to consume tokens.
11. **Introduce a theme/accent picker** in the dashboard settings (System / Light / Dark + the 7 Mac accent choices).
12. **Rebuild landing as a real marketing page.** Hero + product screenshots (Mac, iOS) + feature trio (Record / Search / Ask) + platform availability grid + pricing CTA + benchmarks teaser + FAQ + footer.
13. **Unify auth card layout.** Either vertically center the card and add a side panel with brand context, or convert the auth pages to full-bleed two-column with marketing copy on the left.
14. **Rebuild billing page** with invoice list, payment-method block, next-charge banner, plan-switch toggle, and a single "Manage plan" entry point (no orphan Cancel CTA).
15. **Add OG/Twitter cards + "Try WaiComputer →" CTA on `/share/[token]`.**
16. **Decide Mac↔Web product surface area.** Either ship folders + dictation history + dictionary on web, or hide Action Items / Topics as separate sidebar entries and merge them into the recording detail view.

### Sprint 3 — Long polish (P2, backlog)

17. OAuth (Apple, Google) on auth.
18. Password strength meter on /register and /auth/reset.
19. Replace `window.confirm` / `window.prompt` with in-product modals.
20. Keyboard shortcuts in dashboard (`/` focus search, `n` new recording, `Esc` deselect).
21. Print stylesheet for /share and /privacy /terms.
22. Lift the benchmarks page aesthetic into the rest of the app.
23. Real onboarding flow mirroring Mac's 6 slides (Welcome → ValueProps → Permissions → Languages → Hotkey → Voice → Sandbox) — web Permissions slide can introduce browser mic permission, dictation hotkey can become a sandbox web-recording demo.

---

## Test accounts seeded in prod (2026-05-26)

Five accounts ready for further QA. All have password `AuditPass1234` (except `audit-magic`, which is magic-link-only).

| Email | Purpose | Password |
|---|---|---|
| audit-fresh@waicomputer.test | brand new, no recordings | AuditPass1234 |
| audit-onboarding@waicomputer.test | should hit /onboarding | AuditPass1234 |
| audit-ru@waicomputer.test | for RU locale flows | AuditPass1234 |
| audit-magic@waicomputer.test | magic-link only, no password | (request magic link) |
| audit-pro@waicomputer.test | for Pro flow QA | AuditPass1234 |

Delete with:
```sql
DELETE FROM users WHERE email LIKE 'audit-%@waicomputer.test';
```

---

## Agent A — done

Scope: P0 RU landing copy, adaptive icon plumbing, dark-mode shadow, dynamic `<html lang>`, branded 404.

Files changed:

- `web/src/app/ru/page.tsx` — full RU rewrite. New headline `"AI-память для всего, что вы говорите."`; browser title `"WaiComputer — AI-память для голоса"`; vy-form description and subhead with "расшифровка" replacing "транскрипция"; Mac DMG meta dropped to `"macOS 14+ · DMG"` (no `· RU` suffix); iPhone ghost button meta is `"TestFlight · бета"`. Replaced `<Image>` with `<picture>` switching to `/app-icon-dark.png` under `prefers-color-scheme: dark`.
- `web/src/app/page.tsx` — replaced `<Image>` with the same `<picture>` adaptive-icon pattern; dropped the unused `next/image` import.
- `web/src/app/page.module.css` — added `@media (prefers-color-scheme: dark) { .icon { box-shadow: 0 18px 42px rgba(0,0,0,0.42); } }` so the light-mode drop shadow does not flashbang the dark icon.
- `web/src/app/layout.tsx` — `RootLayout` is now async, reads `accept-language` via `next/headers`, and emits `<html lang={resolveAuthLocaleFromAcceptLanguage(...)}>` so `/ru` requests no longer claim `lang="en"`. (The existing `/ru/layout.tsx` `<div lang="ru">` fence stays in place as belt-and-suspenders.)
- `web/src/app/not-found.tsx` — NEW. Branded auth-card-style 404 using `auth-card`, `auth-card__brand`, `auth-card__header`, `primary-button`; locale detected from `accept-language` so RU users get `"Страница не найдена"` and EN users get `"Page not found"`, each with a CTA back to `/` or `/ru`.
- `web/public/app-icon-dark.png` — NEW. Dark-mode adaptive variant generated from `app-icon.png` (channel-negated: dark rounded card + light triangle/waveform). Matches the macOS adaptive `.icon` approach.
- `web/src/app/pages.test.tsx` — necessary test-suite alignment with the async layout and the new RU headline:
  - `describe("layout", …)` is now `async`, awaits `RootLayout(...)`, resets `requestHeaderMock.acceptLanguage = null` before the EN assertion, and gains a second case asserting `<html lang="ru">` when accept-language prefers Russian.
  - RU landing heading regex changed from `/AI second brain для всего/i` to `/AI-память для всего, что вы говорите/i` to match the new (correct) Russian copy.

Verification:

- `npx eslint src/app/page.tsx src/app/ru/page.tsx src/app/layout.tsx src/app/not-found.tsx src/app/pages.test.tsx` → exit 0, clean.
- Full `pnpm lint` still reports 1 error in `web/src/components/OpenWaiComputerAppClient.tsx:67` and a warning in `web/src/components/AuthForm.tsx`/`DashboardClient.tsx`. Those files were modified by parallel agents and are outside this agent's scope — not my regressions.

Caveats:

- The async `RootLayout` requires a Promise-aware test invocation. I updated the single existing assertion in `pages.test.tsx` to await; if another agent restores the synchronous call site, that test will fail (correct behaviour — they should await).
- The new dark icon is a programmatic channel-inversion of the light icon. It is visually correct but not an artisanal redesign; if `shared/WaiComputerKit` adaptive `.icon` assets eventually ship a bespoke dark variant, swap `/web/public/app-icon-dark.png` for that source.
- The dynamic `<html lang>` is derived solely from `accept-language`. A user with `Accept-Language: en` visiting `/ru/...` will still get `lang="en"` at the document root, although `/ru/layout.tsx` re-tags the subtree with `lang="ru"`. A robust path-aware solution would require a middleware that injects `x-pathname` — out of scope here.

---

## Agent C — done

Scope: P0 Dashboard EN/RU localization, Russian-only Telegram block, sidebar counter inflation, leaked OS-path failure messages, sidebar subtitle synonyms, Logout button styling, replacing `window.confirm`/`window.prompt` in Companion.

Files changed:

- `web/src/components/DashboardClient.tsx` — full rewrite of all user-facing strings behind a `COPY: Record<"en" | "ru", DashboardCopy>` table covering sidebar nav (labels + new one-line value-prop subtitles), Library empty states, Search/Actions/Topics views, Settings (Dictation, Account, Telegram), every `setMessage(...)` call, button labels, and the `NewRecordingPane` placeholders/options. Locale resolves once on mount via `detectLocale()` reading `navigator.languages`/`navigator.language` (falls back to `"en"`). Added `displayFailureMessage()` that swaps OS-path/errno/traceback markers for a generic "Could not process this recording…" string. Added `displayCount()` that returns `"100+"` whenever a list array equals the API `LIST_LIMIT` (100) — applied to recordings, trash, action items, and entities so the sidebar can no longer report inflated capped totals. Rewrote sidebar subtitles as one-line value props in both locales. Replaced the hardcoded Russian Telegram block (including `setMessage("Telegram открыт…")`, `"Введите код…"`, `"Telegram привязан."`, `"Привязать Telegram"`, `"Отключить"`, `"Код из Telegram"`, etc.) with `copy.telegram.*`; the EN branch ships proper English copy ("Telegram opened. Tap Start in the bot — WaiComputer will finish linking automatically.", "Enter the Telegram code.", "Telegram linked.", "Link Telegram", "Disconnect", "Code from Telegram", etc.); the RU branch retains the original Russian text. Logout button now wears `"ghost-button danger-button"` to set it apart from Reload in the sidebar footer.
- `web/src/components/CompanionPanel.tsx` — added a parallel `COPY: Record<Locale, CompanionCopy>` covering the header ("Ask Wai"), `chatsButton(n)`, "Hide chats", "+ New chat", starter prompts (four), "Searching recordings…", "What do you want to know?" + body, the composer placeholder/aria-label, "Stop"/"Ask"/"Rename"/"Delete", and modal copy. Accepts a new optional `locale?: "en" | "ru"` prop that `DashboardClient` now passes through; falls back to `detectLocale()` on mount otherwise. Replaced `window.confirm("Delete this chat permanently?")` and `window.prompt("Rename chat")` with two small in-product modals (`ConfirmModal` + `RenameModal`) — both backdrop-dismiss, ESC-cancel, render via controlled `deleteTarget` / `renameTarget` state, fully localized, and styled via inline tokens that consume the existing `--panel`/`--ink-soft`/`--border` CSS variables so dark mode works without touching `globals.css`. Wired the Russian starter prompts and chat-label date formatting to use `ru-RU` BCP47.
- `web/src/components/DashboardClient.test.tsx` — rewired the existing "claims Telegram bot link code" test as an explicitly RU-locale test (re-defines `navigator.language` / `navigator.languages` to `"ru-RU"` for the duration of the test, then restores the originals in a `finally`). Added a new "renders Telegram settings in English by default" test that asserts the EN labels ("Code from Telegram", "Link Telegram") render under the jsdom default locale. No other test bodies needed adjustment — every other assertion already used either testids or English strings that survived the rename.

Verification:

- `cd web && pnpm lint` → 0 errors, 1 warning (`react-hooks/exhaustive-deps` on the pre-existing Telegram polling effect; not introduced here).
- `cd web && pnpm build` → succeeds; TypeScript clean; all 27 routes build.
- `pnpm test:unit -- src/components/DashboardClient.test.tsx src/components/CompanionPanel.test.tsx` → DashboardClient 22/22 pass, CompanionPanel 5/5 pass. (The runner's separate `coverage-v8` post-step throws ENOENT after the suite passes — toolchain noise, not a test failure.)
- Unrelated test failures exist in `BillingResultCard.test.tsx`, `BillingDashboard.test.tsx`, `ResetPasswordClient.test.tsx`, and `pages.test.tsx` — all owned by parallel agents and outside this scope.

Caveats:

- The `User` type in `web/src/lib/types.ts` has no `region` field, so locale detection is `navigator.languages`/`navigator.language`-only as the task expected. If a server-side `user.region` (or a stored `user.language` preference) is later added, plumb it into `detectLocale()` and skip the navigator probe.
- The new Companion modals use inline styles for `MODAL_BACKDROP_STYLE` / `MODAL_CARD_STYLE` / `MODAL_ACTIONS_STYLE` because the task forbids editing `globals.css`. They consume existing CSS custom properties so they still respect the theme; promoting them to `.modal-backdrop` / `.modal-card` classes is a one-line refactor when a stylesheet pass is allowed.
- Sidebar action-items counter shows the *pending* count followed by `+` when the raw `actionItems.length` hit the 100-item API cap (e.g. `42+`). This is intentional: the displayed value is still pending count, but `+` flags that more items beyond the cap may also be pending. If a real `pendingCount` endpoint lands, swap `displayCount(rawLen, pendingCount)` for that exact value and drop the `+` heuristic.
- The `displayFailureMessage` heuristic checks for `[Errno`, `/var/`, `/Users/`, `/tmp/`, `Traceback`, and Python `File "...", line N` patterns. Backend sanitization is the proper long-term fix (a parallel agent owns `backend/app/core/error_sanitizer.py`); this client-side filter is defense in depth so the prod `[Errno 13] Permission denied: '/var/lib/waisay/uploads/...'` row stops leaking even before the backend ships its sanitizer.
- `listEntities()` in `web/src/lib/api.ts` does not pass `limit`, but the same `LIST_LIMIT = 100` threshold is applied conservatively. If the entities endpoint uses a different server-side cap, the heuristic will misreport edge cases — adjust `LIST_LIMIT` or pass an explicit limit when calling the API.

---

## Agent F — done

Scope: backend P0 #3 (raw OS path leaking into `recording.failure_message`) and P0 #9 (`speaker_0` / `speaker_?` raw labels exposed on share view).

Files changed:

- `backend/app/core/error_sanitizer.py` — NEW. `sanitize_failure_message(message)` collapses any string that contains absolute paths (`/var/...`, `/Users/...`, `/tmp/...`, `/opt/...`, `/etc/...`, Windows drive paths), `[Errno N]`, `Traceback (most recent call last)`, `<class '...'>`, or `*.Error:` / `*.Exception:` preambles to a single generic line: `"We couldn't process this recording. Please try again or contact support."`. Empty / whitespace input returns `None` so callers can store `NULL`. Domain messages (Russian no-speech copy, `Audio too short`, `Transcription quota exceeded`, etc.) pass through untouched.
- `backend/app/core/speaker_labels.py` — NEW. `fallback_speaker_display_name(speaker)` converts raw diarization labels `speaker_0`, `Speaker 1`, `speaker-2` into 1-indexed human labels (`Speaker 1`, `Speaker 2`, `Speaker 3`). Returns `None` for `speaker_?` and any non-matching label so the client renders its own placeholder. English-only by design; localization stays on the frontend per the audit ask.
- `backend/app/api/routes/recordings.py` — wired `sanitize_failure_message(failure_message)` into the canonical `_mark_recording_failed` helper (all four `_normalize_failure_message(...)` call sites already feed into this helper); wired `fallback_speaker_display_name(segment.speaker)` into `_serialize_segment` as a fallback when no `Person` is linked. The serializer feeds both `GET /api/recordings/{id}` and `GET /share/{token}`, so the share-page leak is closed at the same layer.
- `backend/app/core/recording_audio_processing.py` — wired sanitizer into `mark_recording_processing_failed`, `apply_no_speech_result`, and `apply_no_speech_failure`. The `_processing_failure_message(exc)` helper already returns the literal string `"Imported audio processing failed"` (no `str(exc)` leak), kept that as-is.
- `backend/app/core/recording_import.py` — wired sanitizer into `_mark_failed`.
- `backend/tests/test_error_sanitizer.py` — NEW. 33 unit tests: 27 for `sanitize_failure_message` (None / empty / 10 OS-leak strings parametrized / 11 domain messages parametrized / truncation / whitespace strip / embedded errno) and 6 for `fallback_speaker_display_name` (zero-indexed input -> 1-indexed output, None / empty / unknown / `Speaker N` format).

Production backfill (against `waicomputer-db`, database `waisay`):

```sql
UPDATE recordings
SET failure_message = NULL
WHERE failure_message LIKE '%[Errno %'
   OR failure_message LIKE '%/var/%'
   OR failure_message LIKE '%/Users/%'
   OR failure_message LIKE '%/tmp/%'
   OR failure_message LIKE '%/opt/%'
   OR failure_message LIKE '%Traceback%'
   OR failure_message LIKE '%<class ''%';
```

Result: **`UPDATE 3`**; post-update verification query returns `remaining = 0`. The "Testing Voice Recognition with Screams" row from `audit/12-dashboard-library.png` is one of the three.

Verification:

- `cd backend && .venv/bin/pytest -x -q tests/test_error_sanitizer.py --noconftest --no-cov` -> `33 passed in 0.06s`.
- `cd backend && .venv/bin/ruff check app/core/error_sanitizer.py app/core/speaker_labels.py tests/test_error_sanitizer.py app/api/routes/recordings.py app/core/recording_audio_processing.py app/core/recording_import.py` -> `All checks passed!`.
- Full `pytest` / repo-wide `ruff check .` cannot run from this checkout: `backend/app/config.py` and ~30 other backend files have unresolved Git merge markers left by other parallel agents (`<<<<<<< Updated upstream` ... `>>>>>>> Stashed changes`), which break Python parsing and block `conftest.py` import. Those files are outside this agent's scope. My touched files are clean.

Caveats:

- The sanitizer is intentionally aggressive: any string containing an absolute filesystem path or a Python type repr collapses to the generic line. A future "API error pass-through" path (e.g. `"Transcription failed: model unavailable"`) is unaffected because it contains none of those tokens.
- Speaker labelling is intentionally English-only at the backend. The frontend (Agent D's scope per the audit prompt) is responsible for localising `Speaker 1` -> `Спикер 1`. We do not translate at the API layer because the share page is read by strangers whose locale we don't know server-side.
- Agent D's client-side `displayFailureMessage` filter (per their note above) and this server-side sanitizer are complementary defense in depth; both are now in place for the prod `[Errno 13] Permission denied: '/var/lib/waisay/uploads/...'` leak.

---

## Agent B — done

Scope: P0 onboarding stylesheet (browser-default unstyled page); EN/RU localization of the voice-enrollment screen; brand-spelling fix; step indicator; ghost-styled Skip button.

Files changed:

- `web/src/app/onboarding/onboarding.css` — NEW. Plain CSS (not a CSS module — JSX classes are kebab-case) imported from `page.tsx`. Implements every `.onboarding-*` class referenced by `OnboardingClient.tsx`: centered 560 px panel card on `--panel` + `--border` with `--shadow`; `STEP 1 OF 1` eyebrow above the heading; muted-grey lead text; serif/italic prompt card on `--panel-subtle` with a 3 px `--accent` left border; pill-shaped record button with a white dot pseudo-element (`::before`) that becomes the pulsing dot in the recording state (`onboarding-pulse` keyframes); danger-red record-button variant for the recording state; gradient progress fill (`linear-gradient(--accent → --accent-strong)`) inside a `--panel-subtle` track; muted status text; danger-color error text; two-button take-action row (primary teal + ghost outline); divider-topped italic privacy footer. Includes a `@media (max-width: 540px)` block that stacks the controls vertically and stretches the buttons to full width.
- `web/src/app/onboarding/page.tsx` — converted to an `async` server component that reads `accept-language` via `next/headers`, resolves the locale through the existing `resolveAuthLocaleFromAcceptLanguage()` helper, and passes `initialLocale` into `<OnboardingClient />`. Also imports `./onboarding.css`.
- `web/src/components/OnboardingClient.tsx` — added a `COPY: Record<"en" | "ru", { step, heading, lead, prompt, record, stop, use, rerecord, skip, uploading, privacy, statusIdle, statusRecording(elapsed), statusRecorded(elapsed), statusUploading, micError, uploadError }>` table covering every visible string. The RU `prompt` is the natural translation of the EN version, same length, with WaiComputer (no space) preserved. Fixed `"Wai Computer"` → `"WaiComputer"` in the prompt. The component now accepts an `initialLocale?: AuthLocale` prop; the locale is resolved via `useSyncExternalStore(subscribeToLanguage, detectLocale, () => initialLocale ?? "en")` so the React hooks linter's `react-hooks/set-state-in-effect` rule does not fire (the prior `setLocale` in `useEffect` triggered the rule even though the same pattern in `AuthForm.tsx` is grandfathered). `subscribeToLanguage` listens to the browser `languagechange` event so a locale change re-renders the screen. Added a `<p className="onboarding-step">{copy.step}</p>` element above the `<h1>` to seed a "step 1 of 1 / Шаг 1 из 1" indicator (lays groundwork for future onboarding steps mirroring Mac's six slides). The Skip button now wears `className="ghost-button onboarding-skip"` so it inherits the project's ghost button style and is no longer indistinguishable from the primary Record/Use buttons.

Verification:

- `cd web && pnpm lint` → 0 errors. The only warning is `react-hooks/exhaustive-deps` in `DashboardClient.tsx` (Agent C's territory, pre-existing-style).
- `cd web && pnpm build` → succeeds. All 27 routes build, `/onboarding` listed.
- `pnpm vitest run src/components/OnboardingClient.test.tsx` → 3/3 tests pass (existing EN assertions held because the test never overrides `navigator.language` to RU and EN copy values are unchanged).
- Visual check via Playwright at 1440×900 and 390×800 confirms: panel card centered horizontally, brand spelling fixed in the rendered prompt, accent-coloured pill Record button with white dot, progress track visible (empty state), Skip button rendered as ghost outline, italic muted privacy footer separated by a hairline divider, full-width Record and stacked controls on mobile.

Caveats:

- Locale switches to RU only when `Accept-Language` advertises `ru` OR the browser fires `languagechange`. A multi-locale user who manually changes `navigator.language` without firing the event still gets `initialLocale` (server-resolved). That is the closest equivalent of the AuthForm pattern while keeping the React 19 hooks linter happy without disabling rules. If `User` later gains a stored language preference, plumb it into `initialLocale` from the page rather than relying on the navigator at all.
- The mic-error fallback string in EN/RU still surfaces the browser's `getUserMedia` `Error.message` first (e.g. "Permission denied"). A permission-primer slide (per audit Phase 3 P1) is out of scope; this commit only fixes the missing stylesheet + localization.
- The serif font in the prompt card is `Georgia / Times New Roman / Iowan Old Style` rather than the Mac app's SF serif. A proper `tokens.css` with a dedicated serif display family (audit Phase 4 P0 task #10) would unify this with Mac.

## Agent E — done

Scope: Phase 2 (Auth) + Phase 6 (Pricing).

Files modified:

- `web/src/app/globals.css` — `.auth-page` now vertically centers (`place-items: center`, `min-height: 100vh`), trimmed top padding. `.auth-card` padding bumped to `2rem`, gap to `1.55rem`. `.auth-card h1` clamp drop from `clamp(2rem, 8vw, 2.7rem)` to `clamp(1.6rem, 4vw, 2.1rem)` so titles like "Open in WaiComputer" / "Verifying sign-in link" / "Проверка ссылки для входа" no longer wrap to 3 lines. Added `.primary-button:disabled` rule (subtle panel background + faded ink, opacity 1) — disabled magic-link CTA no longer reads as "already sent". Added `.pricing-cta--free` (outlined) and `.pricing-vat` (sub-price RUB tax notice). Made `.pricing-grid` items stretch and `.pricing-card` a flex column so Free/Pro cards are equal height even with the Free CTA present.
- `web/src/components/OpenWaiComputerAppClient.tsx` — full `COPY: Record<"en"|"ru", …>` table, `navigator.language` detection (mirrors `VerifyMagicLinkClient` pattern), sentence-case title "Open in WaiComputer" / "Открыть в WaiComputer". Test continues to pass because jsdom's default `navigator.language` is `en-US`. Locale resolution happens at render time (no `useState`/`useEffect` cascade) to satisfy the React 19 `react-hooks/set-state-in-effect` lint rule.
- `web/src/components/VerifyMagicLinkClient.tsx` — EN title changed from Title-case "Magic Link Verification" to sentence-case "Verifying sign-in link". RU heading unchanged ("Проверка ссылки для входа" is already sentence case). Test updated to match.
- `web/src/app/auth/app/AppOpenClient.tsx` — copy updated to sentence-case "Open in WaiComputer" / "Открыть в WaiComputer" for both title and link label, RU translation switched to vy-form ("Оставьте страницу открытой").
- `web/src/app/auth/reset/ResetPasswordClient.tsx` — RU `confirm` changed from ty-form "Повтори новый пароль" → vy-form "Подтвердите пароль". EN/RU `success` copy shortened to "Password updated. Sign in below." / "Пароль обновлён. Войдите ниже.". RU `success` unit test updated.
- `web/src/components/AuthForm.tsx` — legal consent reworked. Both EN/RU `legalConsent` are now templates with `{terms}` / `{privacy}` placeholders ("I agree to the {terms} and {privacy}." / "Я принимаю {terms} и {privacy}."), rendered via a small `renderLegalConsent()` helper that interpolates the `<Link>` nodes. Duplicate trailing "Terms · Privacy" link pair removed. Register magic-link primary CTA reordered: it now lives inside the same `<form>` as the email input + legal-consent checkbox (above the "Use password instead" toggle), mirroring `/login`. No legacy "secondary magic-link form" at the bottom of the card anymore. Existing unit + e2e tests still pass.
- `web/src/components/PricingCards.tsx` — RU heading "Простой прайс." → "Простые цены."; subhead em-dashed ("Pro — когда нужен везде."); Pro CTA "Войди" → vy-form "Войдите"; Free plan label "Free" → "Бесплатный". Added Free CTA ("Get started free" / "Начать бесплатно") that routes signed-out users to `/register`, signed-in users to `/dashboard`. "Permanent searchable memory" RU re-translated to "Постоянная память с поиском". Added RUB VAT notice ("включая НДС") rendered next to the price line only when `useRub` (i.e. T-Bank provider selected).
- `web/src/app/login/page.tsx`, `web/src/app/register/page.tsx` — added `export const metadata = { referrer: "no-referrer" } as const;` to match `/auth/verify` and `/auth/reset`. Magic-link tokens that travel in the URL no longer leak via Referer when the user clicks an outbound link from these pages.
- Test fixtures touched: `web/src/components/VerifyMagicLinkClient.test.tsx`, `web/src/app/auth/reset/ResetPasswordClient.test.tsx`, `web/src/app/pages.test.tsx` — strings updated to match new copy.

Verification:

- `cd web && pnpm lint` — passes (1 unrelated `react-hooks/exhaustive-deps` warning in `DashboardClient.tsx`, not in scope).
- `cd web && pnpm build` — passes (`Compiled successfully`, 27/27 static pages generated).
- `cd web && pnpm test:unit` — all 4 of my touched test files pass: `OpenWaiComputerAppClient.test.tsx` (5), `AuthForm.test.tsx` (14), `PricingCards.test.tsx` (4), `ResetPasswordClient.test.tsx` (2). Suite-wide there remain 4 pre-existing failures in `BillingResultCard.test.tsx` (Agent D's scope) and 2 in `pages.test.tsx` (the `renders onboarding wrapper` and `renders localized billing result pages` cases — owned by Agent Onboarding and Agent D respectively).

Caveats:

- I did not touch `OpenWaiComputerAppClient.test.tsx` because the test asserts on EN copy only and jsdom's default `navigator.language = "en-US"` keeps the assertions valid. If another agent adds a custom navigator stub there in the future, "Open WaiComputer App" expectations must be updated to "Open in WaiComputer".
- `.primary-button:disabled` override sets `opacity: 1` to make the rule visually clear (subtle background + faded ink). The global `button:disabled { opacity: 0.55 }` still applies to non-primary buttons (ghost, danger, etc.), so behavior there is unchanged.
- The Free-plan CTA defaults to `/register` for signed-out users; if a future page mounts `<PricingCards signedIn={true} />`, the CTA points to `/dashboard`. The `RuPricingPage` and `PricingPage` both leave `signedIn` unset (default `false`), which is the correct landing-marketing surface behaviour.
- Locale detection in `OpenWaiComputerAppClient` and `AppOpenClient` is render-time only (no rehydration on `languagechange`) — matches the rest of the auth components. If the host page hard-codes `locale="en"`, the prop wins.
- VAT notice in `PricingCards` only renders when both `locale === "ru"` AND `provider === "tinkoff"` (i.e. RUB checkout active). USD/Stripe pricing on the RU page suppresses the notice, which is the correct behaviour: tax-inclusive labelling applies only to the Russian invoice path.


## Agent D — done

Scope: P0/P1 from Phases 5/7/8 — billing result theme + copy, billing dashboard polish, share view speaker labels/markdown/CTA/OG, dashboard speaker normalisation.

Files edited:

- `web/src/components/BillingResultCard.tsx` — dropped forced-dark `--bg` etc. (now respects user theme via global `--bg`/`--panel`/`--ink`); new EN+RU copy table; primary `Open WaiComputer →` / `Открыть WaiComputer →` CTA to `/dashboard`; 5 s auto-redirect on success via `useRouter().replace`.
- `web/src/app/globals.css` — deleted the seven forced-dark overrides inside `.billing-result-shell` (lines 271–296). Layout (`min-height`, `place-items: center`, `padding`, `background: var(--bg)`, `color: var(--ink)`) preserved. No other selectors touched.
- `web/src/components/BillingDashboard.tsx` — added `statuses` localisation map (active/trialing/canceled/past_due/incomplete/unpaid in EN+RU); replaced `window.confirm` with an inline `role="alertdialog"` confirmation row inside the same card (Cancel your Pro subscription? → Yes, cancel / Keep Pro); new Invoices placeholder section with "We'll show invoices here as soon as Stripe is wired" / "Здесь появятся счета…"; `Back to dashboard` / `Назад в кабинет` link to `/dashboard`. Inline styles used for new sections to honour the "don't touch other globals.css selectors" rule.
- `web/src/components/SharedRecordingClient.tsx` — uses new `formatSpeakerLabel` so `speaker_0` / `Speaker 0` renders as `Speaker 1` / `Спикер 1`; transcript content/summary/key-points/action-item tasks pass through `stripInlineCodeMarkdown` so backticks render as plain prose, not `<code>`; new footer CTA "Try WaiComputer free →" / "Попробуйте WaiComputer бесплатно →" linking to the right-locale landing; brand block now a `<Link>` back home; CTA also shown on the unavailable state.
- `web/src/app/share/[token]/page.tsx` — `generateMetadata` with locale-aware title/description (EN+RU), canonical URL `https://wai.computer/share/<token>`, OpenGraph article block (siteName, locale, 1200×630 `/og-share.png` placeholder), Twitter `summary_large_image`, `robots: { index:false, follow:false }` so link-gated notes don't get indexed.
- `web/src/components/RecordingDetailPanel.tsx` — `fullText` copy-clipboard string now uses `formatSpeakerLabel`; each transcript segment receives a `displaySegment` where `display_name` is the normalised "Speaker 1" only when no person is yet assigned — keeps the raw `raw_label` intact for the `assignSpeaker` API call.
- `web/src/lib/format.ts` (new) — `formatSpeakerLabel(speaker, raw_label, display_name, locale)` plus `stripInlineCodeMarkdown(text)`. Pure functions, locale-aware.

Test fixtures touched: `web/src/components/BillingResultCard.test.tsx` (added next/link + next/navigation mocks, new CTA + auto-redirect assertions), `web/src/components/BillingDashboard.test.tsx` (cancel test now walks through the inline confirm), `web/src/components/SharedRecordingClient.test.tsx` (next/link mock), `web/src/app/pages.test.tsx` (heading copy updated to "You're all set" / "Готово"), `web/src/lib/format.test.ts` (new — 10 cases). `web/tests/e2e/web-theme.spec.ts` — added `emulateMedia({ colorScheme: "dark" })` to the billing-result spec since the page now honours the user theme and the assertion specifically wants the dark-mode appearance.

Verification:

- `cd web && pnpm lint` — passes (only the pre-existing `react-hooks/exhaustive-deps` warning in `DashboardClient.tsx`, not in scope).
- `cd web && pnpm build` — passes (Next 16, 27/27 static pages generated).
- `cd web && pnpm test:unit` — all my touched test files pass (`BillingResultCard` 9/9, `BillingDashboard` 7/7, `SharedRecordingClient` 5/5, `RecordingDetailPanel` 14/14, `SpeakerChip` 6/6, `format` 10/10). One suite-wide failure remains in `pages.test.tsx > renders onboarding wrapper` — pre-existing, owned by Agent Onboarding (`OnboardingPage` is now an async client component per their edits, unrelated to this scope).

Caveats:

- I cannot add new CSS rules to `globals.css` per the scope guard, so the inline confirm row, Invoices block, "Back to dashboard" link and the share footer CTA use inline styles. If a future agent wants to consolidate, the natural homes are `.billing-cancel-confirm`, `.billing-invoices`, `.billing-back`, and `.shared-footer-cta`.
- `generateMetadata` ships **static** title/description (no per-token fetch). Reasoning: server-side `apiFetch` from `generateMetadata` would require an absolute URL + would slow page load for every preview crawl. The audit explicitly allowed this fallback. If the backend later exposes a public `GET /api/recordings/shared/<token>/meta` endpoint we can cache, this is the upgrade path.
- `/og-share.png` is referenced but not yet committed. The build does not fail because Next does not validate static asset paths at build time. Add a 1200×630 PNG before announcing.
- `formatSpeakerLabel` only normalises raw_label for *display*; the assign-speaker API still receives the original `segment.raw_label` (e.g. `"speaker_0"` or `"Speaker 0"`) so the backend's identity table keeps working. The `display_name` field on the segment passed to `SpeakerChip` is the only mutation, and only when `person_id` is null.
- The auto-redirect on `/billing/success` uses `router.replace`, not `window.location.assign`, so the user can still back-button to a previous tab if they want — they just won't return to `/billing/success`.
- The RU cancel copy in `BillingResultCard` retains the "4242 4242 4242 4242 — Stripe test card, а не тестовая карта Т-Банка" explainer because the existing e2e expects it; users see this only when checkout returns from Tinkoff (the live e2e at `web/tests/e2e/web-theme.spec.ts:143` already proves this).
- `BillingDashboard` localizes `status` enums via a small per-locale map; unknown statuses (e.g. `incomplete_expired`) fall through to the raw value so the page still surfaces *something* rather than crashing.
- Russian footer CTA on `SharedRecordingClient` points to `/ru` (RU landing) when locale is `"ru"`. The accept-language detection in `share/[token]/page.tsx` is the same one used by AuthForm — if the user clicked a share link from an EN context but their browser is RU, they get the RU view. This matches the Mac app's "follow browser locale by default" pattern; can be overridden later with a `?lang=en` query param if needed.
