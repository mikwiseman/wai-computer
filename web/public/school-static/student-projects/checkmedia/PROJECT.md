# PROJECT — CheckMedia Assistant

> **One file for everything**: what we're building, why, what's done, and what's next.
> Hand this to any AI or teammate as background.
>
> Last updated: 2026-06-25.

---

## 1. The big idea (what & why)

A **support + sales chatbot** that lives on the CheckMedia website and works like a
smart guide. The bot is **part of the CheckMedia site**, not a separate thing — it
should look like it belongs there.

**In one line:** the visitor describes their situation in plain words → the bot
recommends the **one** tool they actually need, explains it, talks price, and guides
them to the next step (try for free **or** book a call).

**The "why":** the bot is a *translator between a complex website and a confused
human*. It catches the visitor in the 5 seconds before they give up, turning
*"too complicated, I'm out"* into *"ah, that's what I need."*

The same idea is meant to work two ways later: a **Skill for Claude** and a
**Gem/GPT for ChatGPT**.

---

## 2. Who it's for + the pain

**Primary user — a startup founder.**
They were **referred** to CheckMedia (an ad, a friend, a blog — they didn't find it
themselves). They're getting ready for a pitch or investor talks, but **don't know
which tool they need.**

**The pain:** they have to figure out unfamiliar tools alone, under stress. It's a
double problem — they **don't know what to buy** *and* they **aren't sure it'll even
help their pitch**. So they leave without deciding.

**Second user — a marketer / CMO** at a company who spends ad budget and wants to
**prove to finance that the money works.**

---

## 3. About CheckMedia + its tools

CheckMedia offers **go-to-market strategy consulting and AI-powered marketing
analytics** to help businesses lower customer acquisition cost (CAC) and improve
marketing ROI. Target site: [checkmedia.com](https://checkmedia.com).

**For startups (investor-ready):**
- **CAC Benchmarks** — *Free online.* CAC numbers for a pitch deck (investors ask first).
- **Commercial Risk Assessment** — make risks visible before investor talks.
- **Go-to-Market strategy** — how much to invest in marketing and how many customers
  you'll get; makes the project fundable.

**For companies / marketing teams:**
- **CAC Benchmarks** — *Free online.* Find ways to improve CAC.
- **AI-based ROI analytics** — precise ROI numbers finance people trust.
- **FP&A tool for brand portfolio** — for large teams / complex multi-brand projects.

**Free vs paid:** only **CAC Benchmarks is free**. Everything else is paid.

**Brand & tone:** purple/lavender accents (`--accent:#7C5CFC`) on dark navy
`#0A2540`; professional yet approachable, data-driven. Real-site CTAs:
"Try for free", "Find out more", "Book a call".

---

## 4. What's built + current state

**The site:** one self-contained file — `variant-C-landing.html` — opens by
double-click, no external libraries.

**Page structure (top to bottom):**
1. Header — logo + language picker
2. Hero — headline + promise + "Ask the assistant" button
3. Pain → solution band
4. How it works — 3 numbered steps
5. Tool cards — CAC / Commercial Risk / Go-to-Market (click to expand)
6. **Chat demo** — the live centerpiece
7. Trust band — 3 chips
8. Final CTA — "Stop guessing. Start asking." + Try for free / Book a call
9. Footer — logo + "demo assistant" note

Responsive for mobile (single-column, full-width buttons, no iOS zoom).

**How the chat works right now:**
- Opens with a friendly greeting: *"Tell me your situation in your own words…"*
- The visitor **types freely**. The bot reads the words (English keywords for now):
  - investor pitch / raising money / which tool / cost of a customer / confused →
    recommends **CAC Benchmarks** (free) with a chart.
  - marketing budget / how much to spend on marketing / go-to-market →
    recommends **Go-to-Market** with a chart.
  - anything it doesn't recognize → a gentle *"tell me a bit more"* reply
    (it never fakes a confident answer).
- The "Try for free / Book a call" buttons live **only at the bottom of the page**,
  not after every chat answer.

**Honest limits (on purpose):**
- Answers are **made-up placeholders** for now — the real AI brain and payments
  come later.
- Understanding and the Go-to-Market answer are **English-only** so far; other
  languages are a later step.

---

## 5. The full bot — all the parts (the whole picture)

The complete set of pieces the bot will eventually have. Not all are built yet —
this is what we're aiming for. *(Status added so we can see where we are.)*

1. **Rich Chat Interface** — text plus buttons, pictures, charts, cards, tables. — ✅ mostly built
2. **Who-Are-You Detector** — figures out startup / SMB / enterprise from the chat, no form. — ⬜ later (we removed the old "who are you" buttons on purpose)
3. **The Brain** — the Claude AI model. — ⬜ later (placeholders for now)
4. **Knowledge Base** — trusted facts the AI answers from. — ⬜ later
5. **Tool Matcher** — picks the right tool. — 🟡 started (keyword version: CAC + Go-to-Market)
6. **Calculators / Tools** — CAC, risk check, spend forecast. — ⬜ later
7. **Language System** — multi-language. — ✅ English edition
8. **Memory** — remembers the conversation. — ⬜ later
9. **Lead Capture & Payment** — hand off to sales or take payment in-chat (Stripe). — ⬜ later
10. **Guardrails** — keeps it on-topic and honest. — 🟡 started (off-topic gets a gentle reply)
11. **Admin Panel** — staff edit content without a coder. — ⬜ later
12. **Analytics** — tracks questions, recommendations, and sales. — ⬜ later

---

## 6. English edition

This edition on wai.computer always opens in English. The language picker is hidden.

- The English website uses English for the landing page, chat, tool descriptions and controls.
- In code: one `I18N` object keyed by language; HTML uses `data-i18n` attributes;
  `t(key)` falls back to English.



---

## 7. Development plan

### ✅ Done
1. ✅ Build the landing page (hero, cards, chat, trust, CTA, footer) in CheckMedia's
   style — purple brand, logo, mobile-friendly.
2. ✅ 10-language system + auto-detect & remember the choice.
3. ✅ Friendly first message when the chat opens.
4. ✅ **Let people type freely** — the bot understands the typed situation (English).
5. ✅ **Bot recommends different tools** for different situations (CAC vs Go-to-Market).
6. ✅ Clean up the next-step buttons — only at the bottom, not after every answer.

### ⬜ Next / open
7. ⬜ Teach a **third situation**: *Commercial Risk* ("show my risks before an
   investor finds them").
8. ⬜ Make the **two bottom buttons real** — "Try for free" → the free CAC tool,
   "Book a call" → the real booking page. *(Needs the real links.)*
9. ⬜ Add the new understanding + answers in **all 10 languages**.
10. ⬜ **Give the bot a real brain** — connect Claude (or ChatGPT) through the API so
    it can answer any question and use real CheckMedia facts. Set its rules: stay
    warm, simple words, only talk about CheckMedia, always end with one next step.
11. ⬜ **Show buttons smartly** — only when the visitor seems almost convinced, then
    ask if they want the next step *(Kris's idea)*.
12. ⬜ **Count what people do** — which language, which path, which button. See what works.
13. ⬜ Fix the *"reads the live CheckMedia site"* trust badge — make it true or soften
    the wording (right now it's a promise we don't keep yet).
14. ⬜ **Put it online** (hosting) so anyone can visit with a link.
15. ⬜ **Stripe payment flow** — let the bot help the person pay right in the chat (see §9).
16. ⬜ **Watch & improve** — use the numbers from step 12 to fix weak spots.

---

## 8. The customer's point of view (judge every idea this way)

For each new idea ask: **Is it useful? Could it be a problem? What could we add?**

**✅ Useful**
- A warm first message so they never face an empty box.
- One clear answer and one next step — not a wall of choices.
- Replies in their own language; simple words; short answers.
- The bot says *"I don't know, but here's who can help"* instead of guessing.

**⚠️ Problems to avoid**
- Slow replies (feels broken). Wrong/made-up answers (trust gone). Too much text.
- A promise we don't keep (like "reads the live site"). Asking for an email too early.
- No way out if the bot gets stuck.

**➕ Could add later**
- Quick-tap example questions. A "Was this helpful? 👍👎". Tiny charts inside the chat.
- Save the chat so a refresh doesn't lose it. A "talk to a human" door.

---

## 9. Future: Stripe payment flow (build with care)

Big idea: the bot doesn't just *recommend* — it can help the person **pay** in the
chat using **Stripe**.

1. User describes their situation in plain words.
2. Bot picks the right services **and how many** (Kris will explain this logic).
3. Bot works out the **total**, applies a **volume discount** (more services =
   cheaper) and a **coupon discount** if they have one.
4. Bot shows the list + price; user **confirms or corrects**.
5. On confirm, the bot calls **Stripe** through its API.
6. Stripe returns a **payment-page link**; the user pays on Stripe's secure page.

**Cautions:** the user must **see and confirm** the exact price **before** anything
charges. The Stripe key is a **secret** — it must stay on a safe server, never in the
webpage. The math (totals, discounts, coupons) must be **correct every time**.

---

## 10. What good-design research told us

We researched how to design a chatbot landing section (5 search angles, 22 sources,
top claims checked with a 3-vote review). Confirmed:
- A **5-block structure**: hero (live demo) → pain+solution → features → social proof
  with numbers → conversion footer.
- The **hero headline should name what makes it different**, not generic features.
- **Embed the live demo in-page**, wrapped in a story: pain → promise → demo → proof → CTA.
- **Simple, clear screenshots; minimal animation.**
- **Social proof** = recognizable logos + named testimonials, spread across the page.

**Don't cite** the inflated marketing stats ("interactive demos convert 7.2× better",
"we retain 80% of what we do") — those are unproven vendor claims.

Our page already does the research-backed thing: a live interactive demo as the
centerpiece, wrapped in the pain → how-it-works → demo → trust → CTA story.

---

## 11. Tech notes + owner

- **File:** `variant-C-landing.html` (single self-contained file; double-click to
  open; no build step, no libraries).
- **Folder:** the project folder also holds `CLAUDE.md` (rules), this `PROJECT.md`,
  and `article-summary.md`.
- **i18n:** `I18N` object + `data-i18n` / `data-i18n-ph` attributes; `t()` with
  English fallback.
- **Chat:** pure JS. `understand(text)` reads typed keywords and returns which tool to
  recommend; rich answers add a small chart + a tool card; typing animation.
- **Language picker:** `LANGS` array (code, endonym, English name); search filters on
  all three; choice saved in the browser (`cm_lang`).
- **Colors:** purple `--accent:#7C5CFC`, navy `#0A2540`. Logo embedded inline as SVG.

**Owner:** A WAI School student — a beginner, no prior coding experience.
Keep explanations simple and jargon-free. Mentoring frame: refine audience → function
→ problem one step at a time, then build.
