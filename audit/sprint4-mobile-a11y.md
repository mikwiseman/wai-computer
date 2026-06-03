# Sprint 4 — Mobile + Accessibility audit

Baseline: prod `https://wai.computer`, audit performed 2026-05-27 at iPhone 14 viewport (390x844) with a real Playwright Chromium client, signed in as `hi@mikwiseman.com` (password flow). 21 screens captured.

Screenshots: `audit/sprint4-mobile-01-*` through `audit/sprint4-mobile-24-*`.

Severity scale:
- **P0 mobile** — literally broken on a phone (overflow, untappable, illegible).
- **P1 mobile** — works but ugly / high friction.
- **P0 a11y** — blocks a screen-reader or keyboard-only user.
- **P1 a11y** — polish (better focus rings, better labels).

---

## Method

- Viewport set to 390x844 (iPhone 14, no DPR scaling) before each capture.
- Per page: capture full-page PNG, then run a synthetic audit script that records:
  - horizontal overflow (`right > vw + 1`),
  - hit-target sizes <44px in either axis (`button`, `a`, `[role=button]`, form input clicks),
  - icon-only buttons with no accessible name (svg child, no `aria-label`/`aria-labelledby`/`title`/inner text),
  - heading hierarchy,
  - `<html lang>` attribute correctness,
  - dialog/modal `role` + `aria-labelledby` presence,
  - first-focused element after dialog open,
  - presence/absence of `prefers-reduced-motion` CSS in any loaded sheet.

Token values pulled from `web/src/styles/tokens.css` light theme:

```
--panel:        #ffffff
--panel-subtle: #f1f3f2
--bg:           #f7f7f5
--ink:          #191a1f   (contrast on white 16.4:1 — fine)
--ink-soft:     #626a73   (contrast on white  6.0:1 — fine, AA passes)
--ink-faint:    #9199a2   (contrast on white  2.88:1 — FAILS AA both for normal and large)
                          (contrast on panel-subtle 2.59:1 — FAILS AA)
```

---

## Per-screen findings

### 1. `/` Landing (EN) — `sprint4-mobile-01-landing-en.png`

- Document layout fits: `scrollWidth == 390`. No overflow elements.
- `<html lang="en">`. Title set. Headings: h1 ("An AI second brain for everything you say"), then a healthy h2→h3 cascade.
- Header nav is the worst hit-target offender on the site:
  - `.brand` "WaiComputer" — 131x22 (link, target the entire header chip instead).
  - `.navLink` "Pricing" — 46x18.
  - `.navLink` "Benchmark" — 74x18.
  - `.locale-switcher__item` "EN" — 31x21. "RU" — 32x21.
  - `.signin` "Sign in →" — 64x18.
  - Body "See full pricing →" link — 123x18.
  - Footer "Privacy"/"Terms" — 39x15.
  - **All under 44px tall.** On a phone these are guess-and-tap targets surrounded by other guess-and-tap targets.
- No icon-only buttons here (everything is text). Focus indicator confirmed: 2px solid `--accent` outline on focus.

### 2. `/ru` Landing (RU) — `sprint4-mobile-02-landing-ru.png`

- Same nav micro-link problem as EN (locale-switcher, sign-in, etc.).
- **`<html lang="en">` even though every content string on the page is Cyrillic** — VoiceOver will read Russian text with English phonemes ("шторитейлинг" pronounced as if it were English letters). This is a clear P0 a11y bug.
- Title in Russian, header lang in English; mismatched.

### 3. `/pricing` — `sprint4-mobile-03-pricing.png`

- No horizontal overflow.
- Same header nav micro-link problem as landing.
- Billing-period toggle buttons "Monthly" 95x38 and "Yearly Save 20%" 142x38 — 38px tall, under the 44px iOS HIG floor.
- Otherwise OK on mobile.

### 4. `/login` — `sprint4-mobile-04-login.png`

- Auth card is full-width, no overflow.
- Magic-link button labeled "Email me a sign-in link" defaults to focused/disabled until email entered. Good.
- "Use password instead" toggle works; password form has labeled inputs (`label[for=email]`, `label[for=password]`).
- Heading hierarchy: h1 "Sign in", then the form. Clean.

### 5. `/register` — `sprint4-mobile-05-register.png`

- No horizontal overflow.
- All buttons (`Email me a sign-in link` 292x38, `Use password instead` 292x39) are 38–39px tall — under 44 by ~5–6px. Buttons are wide enough not to feel terrible, but still under HIG.
- Footer "Terms of Service" 86x14 and "Privacy Policy" 74x14 — tiny.
- **P0 a11y**: there is an `<input type="checkbox" name="">` on the page with **no associated label**, no `aria-label`, no `aria-labelledby`. (The agreement checkbox needs a programmatic name; the visible text near it is not associated via `for`/`id`.)

### 6. `/dashboard` default (Wai pane) — `sprint4-mobile-06-dashboard-default.png`, `sprint4-mobile-07-dashboard-wai.png`

- No horizontal overflow.
- **P0 mobile**: at 390px, the sidebar `<aside>` is **577px tall and renders ABOVE main content** instead of behind a hamburger. Users must scroll past 577px of nav (folder list + 8 nav items + actions) every time they land on `/dashboard`. There is no off-canvas drawer, no top-bar nav, no skip-link. This is the dominant mobile pain point.
- **P0 a11y**: the create-folder `+` button is **24x22**. Even on desktop pointer it's small; on touch it's basically untappable.
- **P0 a11y**: per-folder `Rename` (55x22) and `Delete` (45x22) buttons are 22px tall and only revealed on `:hover`/`:focus-within` (`globals.css:2540`). On a phone there is no hover state — these actions are unreachable for keyboard or touch unless the user happens to focus the folder row first; they are also tiny when shown.
- The folder-name input in the create-folder popover has `<input type="text">` with no `name`, no `id`, no `aria-label`, only `placeholder="Folder name"`. Screen readers report it as anonymous text input.

### 7. `/dashboard` All Recordings — `sprint4-mobile-08-dashboard-all-recordings.png`

- No horizontal overflow.
- Row-level `Summarize` (78x30) and `Trash` (49x30) `.compact-button.ghost-button` are 30px tall — under 44. Stacked vertically per row.
- Pagination/footer buttons not present in this view; rows form a long scroll list.

### 8. `/dashboard` Trash — `sprint4-mobile-09-dashboard-trash.png`

- No overflow.
- Empty state shown ("Trash is empty"). Clean.

### 9. `/dashboard` Search — `sprint4-mobile-10-dashboard-search.png`

- No overflow.
- Search input is full-width 38px tall — acceptable for desktop but feels small on iOS. Empty state is text-only.

### 10. `/dashboard` Dictation History — `sprint4-mobile-11-dashboard-dictation-history.png`

- No overflow.
- Long list of past dictations, each row has a `Summarize`+`Trash` 30px button pair.

### 11. `/dashboard` Dictionary — `sprint4-mobile-12-dashboard-dictionary.png`

- No overflow.
- Two-column desktop layout collapses to single column on mobile correctly.

### 12. `/dashboard` Action Items — `sprint4-mobile-13-dashboard-action-items.png`

- No overflow even with 100+ items.
- Checkbox + label pairs use proper `<label for>` association (verified in spot-check).

### 13. `/dashboard` Topics — `sprint4-mobile-14-dashboard-topics.png`

- No overflow.
- Empty state ("0 topics yet"). No content-level bugs.

### 14. `/dashboard` Settings — `sprint4-mobile-15-dashboard-settings.png`

- No overflow.
- Many inputs (Telegram bind, etc.) inherit `width: 100%` from the global rule — OK.
- The Russian Telegram block flagged in `findings.md` is still mixed-language but that is a content issue, not a layout one.

### 15. Cheatsheet (keyboard shortcuts) modal — `sprint4-mobile-16-cheatsheet-modal.png`

- Modal sized `351.625x342.625`, centered. Fits the viewport.
- `role="dialog"` is set on `.modal-backdrop`, but **no `aria-labelledby` and no `aria-label`** — screen readers announce "dialog" with no name.
- After opening, **`document.activeElement === document.body`** — focus is NOT moved into the dialog. A keyboard user must reach for Tab without knowing where they are; a screen-reader user does not get an automatic dialog announcement.
- Modal has a 0.14s fade-in (`@keyframes modal-fade-in` in `globals.css:2566`) and there is **no `@media (prefers-reduced-motion: reduce)`** rule anywhere on the site — animations always play. Vestibular-sensitivity users have no opt-out.
- Esc closes the modal (verified). No focus-trap was triggered while tabbing inside the modal — focus can escape behind the backdrop.

### 16. Delete-folder confirm modal — `sprint4-mobile-23-delete-confirm-modal.png`

- Same shell as cheatsheet — `role="dialog"`, no `aria-label`, no focus-into-dialog, no focus trap, no reduced-motion respect.
- "Delete" and "Cancel" buttons are 38px tall; small but reachable.

### 17. Create-folder inline popover — `sprint4-mobile-22-folder-create-popover.png`

- Renders inside the sidebar. Buttons "Create" and "Cancel" are 38px tall.
- Input has no label (see screen 6 finding).

### 18. `/billing` — `sprint4-mobile-17-billing.png`

- No overflow.
- Single "Cancel subscription" button + plan summary. Functional on mobile, content sparse (already P0 in `findings.md` for being bare).
- `<html lang="en">` — correct.

### 19. `/share/[token]` (valid) — `sprint4-mobile-18-share.png`

- No overflow.
- **Heading skip bug**: DOM order is `<h1>Роман и Василий</h1>` followed directly by `<h2>TRANSCRIPT</h2>` — no h2 between them — but actually that is acceptable as long as the next heading is h2 (here it is). No skip.
- **`<html lang="en">` while page content is Russian** — P0 a11y, same root cause as `/ru`.
- "TRANSCRIPT" is all-caps in markup, not a CSS transform — screen readers will spell it out letter-by-letter on some configurations. (P1.)
- Earlier `findings.md` already flagged the `speaker_0`/`speaker_?` raw labels exposed here.

### 20. `/privacy` — `sprint4-mobile-19-privacy.png`

- No overflow.
- Heading hierarchy clean: h1 then a flat sequence of h2s. Good.
- `<html lang="en">` — correct (content is English).

### 21. `/terms` — `sprint4-mobile-20-terms.png`

- No overflow.
- Same structure as privacy. Clean.

### 22. `/benchmarks/dictation` — `sprint4-mobile-21-benchmarks-dictation.png`

- **P0 mobile**: The leaderboard `<table>` is **780px wide** inside a `.tableWrap` wrapper with `overflow-x: auto` and the wrapper itself is 362px wide. The page-level `<body>` and `<html>` have `overflow-x: hidden`. Result: the table is horizontally scrollable inside its own card, but **there is no visible cue** (no fade, no "scroll →" hint, no sticky scrollbar) that the table extends beyond the visible edge. Most mobile users will assume those four columns are all there is. Concretely 4 columns are clipped (`right=445, 553, 688, 795`).
- Mobile typography is fine; no other overflow.

### 23. Recording detail (clicked a row from All Recordings) — `sprint4-mobile-24-recording-detail.png`

- No horizontal overflow.
- The detail screen shows a list of per-row `Summarize`/`Trash` 30px ghost-buttons exactly like the parent list. Same hit-target problem.
- Title, transcript, and summary tabs all readable.

---

## Aggregate findings

### `/ru` and `/share/*` `<html lang>` is wrong
Both routes serve Russian content but the root element advertises `lang="en"`. This is the single most impactful screen-reader bug on the site because it changes pronunciation for every word.

Files: `web/src/app/layout.tsx` (top-level root), and the `/ru` segment layout should override `lang` to `"ru"`. Share pages should derive `lang` from the recording's detected language.

### `--ink-faint` color fails WCAG AA in light mode
- `#9199a2` on `#ffffff` = **2.88:1**.
- `#9199a2` on `#f1f3f2` (`--panel-subtle`, the most common subtle background) = **2.59:1**.
- WCAG AA needs 4.5:1 for normal text and 3:1 for large text/UI components.

`--ink-faint` is referenced in `globals.css` at lines 297, 822, 1300, 1363, 2462, 2496 (text usages) and as a 2px border at 862. Used heavily for metadata strings, hint copy, empty-state labels, and the chip color of `.ghost-button` placeholder text. Every one of those is below the floor.

Dark-mode `--ink-faint = #8d9996` on `--bg #101214` — separate calculation but visually similar tone; needs to be recalculated.

Fix: bump light `--ink-faint` to ~`#6b737d` (would yield ~4.55:1 on white, ~4.1:1 on panel-subtle). Or restrict `--ink-faint` to non-text decorative uses (borders, dots) and force any text usage onto `--ink-soft` (already AA-passing at 6.0:1).

### Hit-targets across the product
The site has two systemic patterns under the 44px floor:
1. **Marketing nav / inline text-links** — `.navLink`, `.locale-switcher__item`, `.signin`, footer `Privacy`/`Terms` all sit at ~14–22px tall. Most show up in the header; the entire header is reachable but each tap is a guess. (`web/src/app/page.module.css` + `web/src/app/legal.module.css`.)
2. **`.compact-button` / `.ghost-button.compact-button` / `.sidebar-folder-list__item .compact-button`** — `globals.css:321` sets `.compact-button { min-height: 30px }`; the sidebar overrides at line 2545 with `min-height: 20px`. Both are well under 44px. These power: per-recording Summarize/Trash row actions, per-folder Rename/Delete, the create-folder `+` (24x22), the password-strength chips, etc.

Either bump these to 44px for touch, or add a `@media (hover: none) and (pointer: coarse)` block that does so only for touch devices, leaving desktop density intact.

### Sidebar takes over the dashboard on mobile
`aside.WaiComputer-navigation` at 390x577px stacks above main content on `/dashboard`. There is no responsive collapse, no off-canvas behavior, no hamburger. Probable file: `web/src/components/dashboard/DashboardLayout.module.css` (or the equivalent — confirm in source). The whole experience needs a top-bar + drawer below `@media (max-width: 768px)`.

### Modals (cheatsheet + delete-confirm + folder-rename + folder-create-popover)
All four reach the user through `.modal-backdrop`/`.modal-card` in `globals.css:2553+`. They share these defects:
- `role="dialog"` but no `aria-labelledby` and no `aria-label`.
- No focus moved into the dialog when it opens — `document.activeElement` stays on `<body>`.
- No focus trap — Tab can escape to the backdrop and the page behind it.
- No `@media (prefers-reduced-motion: reduce)` to suppress the 140ms fade.

Fix: introduce a `<Dialog>` wrapper or use HTML `<dialog>` (which gives keyboard focus + Esc + inert backdrop for free), and wrap the fade in a reduced-motion guard.

### Form inputs missing labels
- Register page T&Cs checkbox is `<input type="checkbox">` with no `name`, no `aria-label`, no associated `<label for>`. (`web/src/app/(auth)/register/...` — confirm path.)
- Folder-create popover input is `<input type="text" placeholder="Folder name">` with no programmatic name.

### Benchmarks table overflow has no affordance
Wrapping a 780px-wide table in `overflow-x: auto` keeps the page from horizontal-scrolling, but there is no visual scrollbar on iOS and no fade/cue. Users on mobile think the table only has its visible columns.

### No `prefers-reduced-motion` anywhere
Site-wide grep across all loaded sheets in production returned zero `prefers-reduced-motion` rules. The modal fade is the obvious offender; there may also be hero animations, the password meter, sidebar transitions, etc. that all fire regardless of the user's accessibility preference.

---

## Severity buckets

### P0 mobile

1. Dashboard sidebar (577px tall) stacks above main content at 390px viewport; no drawer, no hamburger. — file: dashboard layout module.
2. `+` create-folder button at 24x22, sidebar folder `Rename` 55x22 / `Delete` 45x22 — untappable and only revealed on hover, which doesn't exist on phones. — `globals.css:2540–2549`.
3. Header nav micro-links (`Pricing`, `Benchmark`, locale switch, `Sign in`) all 14–22px tall and packed shoulder to shoulder. — `page.module.css`.
4. `/benchmarks/dictation` leaderboard table 780px wide in a silent `overflow-x: auto` wrapper — content past column 1 is invisible without scroll cue. — `benchmarks/dictation/benchmark.module.css`.

### P1 mobile

5. Pricing toggle buttons (Monthly/Yearly) 38px tall.
6. Auth submit buttons 38–39px tall.
7. Row-level `Summarize`/`Trash` (78x30 / 49x30) on All Recordings, Dictation History, recording detail.
8. Register footer `Terms of Service` 86x14 / `Privacy Policy` 74x14 links.
9. Default `button { min-height: 38px }` site-wide is under 44px — every button inherits this floor.

### P0 a11y

10. `--ink-faint #9199a2` text fails WCAG AA on both `#ffffff` (2.88:1) and `#f1f3f2` (2.59:1). Used on metadata strings, placeholder hints, empty-state copy across many screens. — `web/src/styles/tokens.css:252` (light) and `:342`/`:468` (dark).
11. `<html lang="en">` on `/ru` and on `/share/*` pages whose content is Russian. — `web/src/app/layout.tsx` + `[locale]` segment layouts.
12. Modal `role="dialog"` with no `aria-labelledby`/`aria-label`; no focus moved into dialog on open; no focus trap; Tab can escape behind the backdrop. Cheatsheet, delete-confirm, folder-rename, folder-create popover all affected. — `globals.css:2553+` + modal React components.
13. Folder-name input has no label/`aria-label`/`name`/`id`; register page T&Cs checkbox has no programmatic label. Screen readers cannot announce them.
14. No `prefers-reduced-motion` media query anywhere; modal fade and other transitions always fire. — `globals.css`.

### P1 a11y

15. Sidebar nav buttons have plain text only (no `aria-current="page"` checked — confirm). Folder action buttons are reachable only via `:focus-within` reveal — keyboard users have to know the visual idiom.
16. Skip-link absent (`a[href^="#main"]`): keyboard users sit through the entire sidebar before reaching content on dashboard. (`document.querySelectorAll('a[href^="#"]').length` returned 0 on landing.)
17. Share page renders `<h2>TRANSCRIPT</h2>` as literal upper-case in markup rather than `text-transform: uppercase` — letter-by-letter reading risk on some screen readers.
18. Body of marketing pages renders inside a single `<main>` with no `<nav>`/`<header>`/`<footer>` landmarks at the page level (header is a `<div>` not `<header>`); landmark-skip in screen readers is degraded.

---

## Prioritized fix list for next sprint

Each item names the file (or selector in `globals.css` / `tokens.css`) and the concrete change.

1. **`web/src/styles/tokens.css:252,342,468` — bump `--ink-faint` to AA-passing greys.**
   - Light: `#9199a2` → `#6b737d` (≥4.5:1 on both `--panel` and `--panel-subtle`).
   - Dark: `#8d9996` → recompute against `#101214`/`#171a1d` (`#aab3b0` or similar, target ≥4.5:1).
   - Alternative: keep `--ink-faint` for decorative borders only and re-route every `color: var(--ink-faint)` in `globals.css` (lines 297, 822, 1300, 1363, 2462, 2496) to `var(--ink-soft)`.

2. **`web/src/app/layout.tsx` and `web/src/app/[locale]/layout.tsx` — set `<html lang>` from the active locale.**
   - Russian routes (`/ru`, `/ru/*`) must render `lang="ru"`.
   - `/share/[token]` should set `lang` from the recording's detected language; default to `lang="en"` only if unknown.

3. **Mobile dashboard layout — add a responsive drawer.**
   - Add a top bar with a hamburger button and slide the existing `aside` off-canvas behind `@media (max-width: 768px)`. Use `<dialog>` or a portal with `inert` for the body behind.
   - File: dashboard layout module (probably `web/src/app/dashboard/page.module.css` and the wrapper component).

4. **`globals.css:321` and `:2545` — raise tap targets for touch.**
   ```css
   @media (hover: none) and (pointer: coarse) {
     button, .compact-button, .ghost-button.compact-button,
     .sidebar-folder-list__item .compact-button,
     a.navLink, .locale-switcher__item, .signin {
       min-height: 44px;
       min-width: 44px;
     }
   }
   ```
   Also raise the global `button { min-height: 38px }` on `globals.css:43` to 44px (desktop will accommodate the extra 6px gracefully).

5. **`globals.css:2540` — make folder row-actions always-visible on touch.**
   ```css
   @media (hover: none) and (pointer: coarse) {
     .sidebar-folder-list__item .row-actions { opacity: 1; }
   }
   ```
   Bonus: replace the text "Rename"/"Delete" with kebab `…` icon + `aria-label`, and put the destructive action behind a confirm modal (already exists).

6. **Modal infrastructure — adopt native `<dialog>` or add aria + focus management.**
   - Add `aria-labelledby` pointing at the modal's `<h2>` to every `role="dialog"`.
   - On open: `dialog.querySelector('[autofocus], button, [href], input').focus()`. Save previously-focused element and restore on close.
   - Implement a focus trap (or use `<dialog>` which does it natively + supports Esc and inert backdrop).
   - File: the React modal wrapper (search `web/src` for `modal-backdrop` consumers).

7. **`globals.css` — add a reduced-motion section.**
   ```css
   @media (prefers-reduced-motion: reduce) {
     *, *::before, *::after {
       animation-duration: 0.01ms !important;
       animation-iteration-count: 1 !important;
       transition-duration: 0.01ms !important;
       scroll-behavior: auto !important;
     }
   }
   ```
   Top of file or near the `.modal-backdrop` definition (line 2553+).

8. **`benchmarks/dictation/benchmark.module.css` — add a scroll cue to `.tableWrap`.**
   - Mask-image gradient at the right edge that disappears when scrolled to end, or stack the columns on `@media (max-width: 600px)`. At minimum, set `scrollbar-width: thin` / `-webkit-overflow-scrolling: touch` and a sticky scroll hint ("Scroll →").

9. **Form labels** — add `aria-label` to:
   - The folder-name input in `web/src/components/sidebar/FolderCreate*.tsx` (`aria-label="Folder name"` or wrap with `<label>`).
   - The T&Cs checkbox on `web/src/app/register/page.tsx` — wrap the agreement copy in a `<label>` and link with `for=`.

10. **Add a skip-link** to `web/src/app/layout.tsx` (`<a class="visually-hidden focus:not-sr-only" href="#main">Skip to content</a>`) and set `id="main"` on the page-level `<main>`. Critical for keyboard users on dashboard.

11. **`page.module.css` (landing) — convert the top-bar `<div>` to `<header>` and put nav inside a real `<nav>`** so landmark navigation works for screen readers.

12. **`/share/*` heading "TRANSCRIPT"** — change to `text-transform: uppercase` in CSS so the underlying string is "Transcript". Same for any other all-caps display heading.

---

## Verified non-issues

- Page-level horizontal scroll is suppressed via `html, body { overflow-x: hidden }` (`globals.css:18`). No site-wide horizontal jiggle.
- Buttons have a 2px solid `--accent` focus outline with 2px offset (`globals.css:78`). Focus ring is consistently visible (no `outline: 0` without replacement found in the audit).
- Headings hierarchy on landing, privacy, terms, share is clean (no skipped levels).
- Most route titles set correctly via `metadata.title`.
- Onboarding (`/onboarding`) was not re-audited here because the prod account is already onboarded; `findings.md` already flags it as broken (no stylesheet).

---

## Caveats

- The Playwright Chromium client does not perfectly emulate iOS Safari (e.g., it shows a desktop scrollbar style). Real-device sanity testing on an iPhone 14 + iOS 17/18 Safari is still required.
- Contrast checks here are math against the design tokens; some screens use additional `color-mix()` overlays that could push numbers either way. Worth running an automated `axe-core` pass against each route in a follow-up sprint.
- Focus-trap verification was done programmatically; for a screen-reader test, run with NVDA/VoiceOver to confirm dialog announcement.
