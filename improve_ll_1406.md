# Lecture 14.06 — *Build Your Own Game with Claude Code* 🎮

> **Audience:** kids aged 10–11 (≈ grades 4–6), near-zero prior coding, mixed Mac & Windows laptops.
> **Duration:** ~60 minutes (trimmable to 45).
> **Date:** 2026-06-14.
> **One-line goal:** every child leaves the room saying *"I made a game!"* — and understands enough about AI to do it safely and want to do it again.
>
> **How this was made.** A team of 6 specialist agents (Pedagogy, Claude Code product, Game-curriculum, Responsible-AI, Classroom facilitation, Engagement) each researched current best practice, made distinct offers, and self-checked them. The lead scored all 30 offers on `I·E·C → P` (Impact·Effort·Confidence, `P = I×C÷E`) and cherry-picked the winners into one coherent lesson. The full scoring table is at the bottom; the body is the teachable result.
>
> **How to read.** Start with **§0 The one decision that gates everything** (pick a mode). Then the **60-minute run** is the lesson itself — teach straight off it. **§5 Ready-to-use assets** (prompts, the Remix Menu, the AI Rules, badges, certificates, glossary) are print-and-go. **§6 What goes wrong** + **§7 Plan B** keep you safe on the day.

---

## §0 The one decision that gates everything (read first)

**Anthropic requires users to be 18+ for their own Claude accounts.** Children do **not** sign up, do not type emails/passwords/payment, and do not use personal accounts. Everything below assumes **adult-owned, supervised access**. Pick one mode:

| | **Mode A — Single screen (teacher-driven)** | **Mode B — Paired laptops (recommended target)** ⭐ |
|---|---|---|
| **How** | Teacher drives Claude Code on the projector; kids take turns being the "Prompt Pilot" dictating the next change. | Each pair opens a pre-built starter game on a **school-provisioned, supervised account** and modifies it. |
| **Best when** | Accounts/install/policy/network **can't** be solved, or you want zero day-of risk. | You can pre-install the app, provision supervised accounts, and whitelist the network. |
| **Hands-on depth** | Lower (kids watch + dictate). | High (every kid builds their own). |
| **Engagement ceiling** | Good. | Excellent — this is what produces *"I made a game!"* |

**This packet defaults to Mode B** (that's where the magic is) **with Mode A as the explicit, named fallback** when prerequisites aren't met. *No silent degradation:* if you can't do Mode B, you consciously switch to Mode A and tell the class it's a shared-build day.

**Mode B prerequisites (non-negotiable, confirm 3+ school days before):**
1. Claude Code desktop app pre-installed on every laptop (Mac: `Claude Code.app`; Windows: `Claude Code.exe` + one-time **Git for Windows** install).
2. **One school-owned workspace/account**, provisioned by the teacher, billing pre-set. No kid ever enters an email, password, phone, or card.
3. **Network/firewall whitelist** — school filters routinely block AI endpoints. Test from a *real student laptop on the school Wi-Fi*. File the IT whitelist (domain + IP) now; get the IT contact's mobile for the day.
4. Acceptable-use sign-off covering minors using an AI tool under supervision (COPPA <13 / FERPA apply).

> In Mode A, prerequisites 2–4 still apply (the teacher still needs a working account + network), but 1 drops to "teacher's laptop only."

---

## §1 The lesson in 30 seconds (the spine)

**Three beats, two brain-breaks, one loop the kids chant:**

> **Describe → Build → Run → Tweak → Repeat.** (Write this on the board. It's the one idea that survives any app update.)

- **Beat 1 — WOW + I-do (≈18 min):** a game appears live in 60 seconds → the 3 safety rules → "AI is a tool, not a friend" → a deliberate break-and-fix so kids see *the AI can be wrong and that's normal*.
- **Beat 2 — WE-do (≈12 min):** the whole class co-pilots **one** identical prompt and lands a working game together. First win by ~minute 20.
- **Beat 3 — YOU-do (≈25 min):** pairs **personalize** their game (the Creator Card) → pick from the **Remix Menu** → Driver/Navigator swap at the midpoint.
- **Finale — SHOWCASE (≈8 min):** play-your-neighbour + spotlight + certificate. *Never cut this.*

Pedagogical basis: 10–11s' sustained-attention ceiling is ~20–30 min (Beat structure respects it); Piaget's *concrete-operational* stage means the lesson must produce a **visible, runnable thing**; the I-do/we-do/you-do arc is ASCD-endorsed gradual release; and 2025 research (Hsu, *TechTrends*) shows **prompting *is* computational thinking** — so the "Prompt or Wish?" contrast (§5) is the conceptual core, not a side activity.

---

## §2 The 60-minute run (minute-by-minute)

| Time | Activity | Teacher does | Kids do |
|---|---|---|---|
| **0–5** | **WOW hook** | Run the 60-second live demo (§5.1). Let one kid come up and play for 30s. Then: *"Today, every one of you builds your own."* | Watch, react, want in. |
| **5–9** | **3 Rules + "tool not friend"** | The 5 AI Rules (§5.3) — thumbs-up to agree. The 2-sentence "super-smart parrot, not a friend" reframe (§5.4). | Repeat rules back; agree. |
| **9–13** | **Setup check** (Mode B) | Walk the room: app open, chat box visible, `my-game` folder present, network replying. Fix logins/crashes now. *(Mode A: just your laptop.)* | Open app, give thumbs-up. |
| **13–18** | **"Prompt or Wish?"** (we-do) | Side-by-side: type a *wish* ("make it cool") → meh; type a *prompt* ("make the player jump on Space, blue background") → exactly that. *"A wish is vague, a prompt is a recipe."* | See their words could change the game. |
| **18–20** | **Brain break** | Stand, 30-sec stretch, "show me your game face." | Move. |
| **20–30** | **Guided first build** | Whole class types the **Treat Catcher prompt** (§5.2) together — word-for-word. Checkpoint: *"Who sees a treat falling?"* Fix the 1–2 that don't. **First win by ~min 25.** | Type it, open it in the browser, play. |
| **30–31** | **Role swap** | *"Driver and Navigator — swap!"* (one laptop per pair, §5.6) | Swap seats. |
| **31–48** | **Make it YOURS** | Hand out the **Creator Card** (personalize: name, colour, emoji) → then the **Remix Menu** (§5.5). Circulate. Use the "Stuck?" menu (§5.7) and the **Oops-it-broke** reframe (§6). | Customize, try things, break things, fix them. |
| **48–52** | **Polish** | *"Last push: one thing to make it yours."* Help stragglers reach *something playable*. | Final tweak; reopen to confirm it runs. |
| **52–60** | **Showcase** 🎉 | Play-your-neighbour (1 min each way) → 2–3 voluntary 60s spotlights → **certificates** (§5.8) → group cheer. *Applaud creativity, not polish.* | Show off, clap, get the certificate. |

> **Buffer rule:** if setup eats time, cut **Build-Your-Own** — *never the showcase.* The showcase is what they remember.

---

## §3 What the kids actually build (the game)

**Format: a single self-contained `.html` file.** Claude Code writes it; kids double-click to play in a browser. This is the lowest-friction format for a mixed Mac/Windows room: **zero install, instant payoff, trivially tweakable, takes the file home.** Python/pygame needs an interpreter + library install per machine — a reliable way to strand half the class in the first 10 minutes.

**Default starter — "Catch the Falling Treats"** (catch objects in a basket; score; timer). Universally appealing, single-file, ~80 lines Claude writes in seconds, infinitely themeable. **Fallback starter — "Cookie Clicker"** (one giant emoji, click for +1): the simplest possible "game," a guaranteed win for any pair that's stuck.

**Scope discipline — what NOT to attempt in 60 min (put this on every prompt card):**
> *Single screen. Single file. One level. No Minecraft, no 3D, no multiplayer, no physics platformer.*
> Today's games are: **clicker / catch / quiz**. That's plenty. (An advanced kid goes *deeper* via the Remix Menu, not *wider* in scope.)

**Three starter concepts** (pick the catch game to lead; keep the others in your back pocket):

| Concept | One-liner | Why it fits |
|---|---|---|
| **Catch the Falling Treats** ⭐ | Basket catches falling emoji; score + 30s timer. | Most-documented beginner JS game; pure DOM, single file, satisfying in 30s. |
| **Cookie Clicker** (fallback) | Giant emoji; click = +1; buy an auto-clicker upgrade. | Zero movement/collision logic; 100% of kids get a working game. |
| **Quiz About Yourself** | 5 multiple-choice Qs about the kid; friends play it. | Maximum personalization; the content *is* the kid. |

---

## §4 The safety & AI-literacy block (don't skip — it's legally grounded)

COPPA (under-13) + FERPA apply; the teacher/school owns the workspace so no child's PII enters the tool. Frame it for kids as **5 rules they agree to** (full text in §5.3) plus one 2-sentence demystification:

> *"Claude has read a giant library and is unbelievably good at guessing what words/code come next — like a super-smart parrot. It doesn't think, feel, or care; it's a tool, like a calculator. So we don't tell it secrets, and we don't believe it just because it sounds sure — we **test**."*

**The single highest-leverage safety moment — the "planted-wrongness" demo (fold into Beat 1, 5 min):** deliberately ask Claude for something subtly wrong (e.g., "make the score go up when the player *looks* at a coin"), run it, let the class spot that it doesn't work, then say the magic line:

> **"It sounded confident. It was still wrong. That's normal — we check, we fix. When your game breaks, it's not because you're bad at this."**

This reframes every later bug as normal (protecting motivation) and teaches the one idea that matters: *confident AI can be wrong, so verify.* (UNESCO AI-competency *ethics* dimension; Common Sense Media "question AI outputs.")

---

## §5 Ready-to-use assets (print & go)

### 5.1 The 60-second WOW demo script
> *"Watch this. I'm going to talk to Claude Code like a teammate, and in one minute we'll have a real, playable game."*
> *(type, narrating)*: *"Make me a game where a smiley catches falling stars. Arrow keys. Make it fun."*
> *(press Enter — **go silent**, let them watch Claude 'think' and write files for ~15s. Don't talk over the magic.)*
> *(it finishes — hit Run)*: *"Three… two… one…"* → game pops up with a ding and a score.
> *(encore — the break-and-fix)*: deliberately type something that breaks it, then *"fix this"* → it fixes. *"See? Game devs break things all the time."*
> *"Now — whose turn is it to make THEIR game?"*

### 5.2 The ready prompt kids type first (guaranteed win ~min 25)
```
Make a single HTML file game called "Catch the Falling Treats".
A basket at the bottom moves left/right with the arrow keys AND the mouse.
Treats (the emoji 🍩) fall from the top at random spots.
Catch one = +1 point and a little "pop" sound.
Show the score at the top in big colorful letters.
The game lasts 30 seconds, then shows "Time's up! You scored ___" with a Play Again button.
Put EVERYTHING in one file called my-game.html so I can just double-click it to play in my browser.
```
Then the **second instruction** (forces them to open it → the wow lands): `Open the game, then tell me how to play it.`

### 5.3 The 5 AI Rules (kids thumbs-up to agree)
1. **I test before I trust.** AI can sound sure and still be wrong — so I run it and check.
2. **I keep secrets out.** No real names, addresses, numbers, or passwords — only fake fun data (Captain Pixel on Planet Sprinkle 🍩).
3. **AI is a tool, like a calculator — not a brain or a friend.** The ideas and choices are mine.
4. **I'm honest about my helper.** If AI helped me build it, I say so.
5. **I'm kind.** I never ask the AI to make mean, scary, or yucky things. If it does something weird — I close it and tell the teacher. I won't be in trouble.

### 5.4 Teacher's plain-language glossary (read aloud as needed)
- **AI coding agent** — a helper that doesn't just talk; it makes files and runs things when you ask.
- **Prompt** — what you type to tell Claude what you want, in normal words.
- **Code** — instructions in a language the computer understands. Claude writes it for you.
- **File** — one saved thing on the computer. A game is a few files working together.
- **Project / folder** — the place where all your game's files live.
- **Preview / Run** — seeing your game actually work before it's finished.
- **Browser preview** — opening your game in Chrome/Safari to play it.
- **Diff** — a side-by-side view of what Claude *changed* (red = removed, green = added).
- **Bug** — a mistake that makes the game do something wrong. You tell Claude; it fixes it.
- **Iterate** — go around the loop again: try it, notice something, ask for a change, try again.

### 5.5 The Remix Menu ("Make it your own" — ★ difficulty, test each before class)
Pick ONE at a time. Play it. Then pick the next.

| ★ | Remix (type this to Claude) |
|---|---|
| ★ | *"Add a fun 'pop' sound when I catch a treat, and a little song when the game ends."* |
| ★ | *"Change the background to a starry night sky and make the treats glow."* |
| ★ | *"Change the player to a 🐉 and put my name '____' at the top in my favourite colour."* |
| ★★ | *"Add a golden star ⭐ that falls rarely — catching it gives me 5 bonus points."* |
| ★★ | *"Add a 'bomb' 💣 that falls sometimes — if I catch it, I lose 2 points."* |
| ★★ | *"Save my best score ever and show it at the top as 'Best: ___'."* |
| ★★★ | *"Add a start screen with my game's name and a Start button."* |
| ★★★ | *"When time's up, show my name in huge rainbow letters with confetti."* |

### 5.6 Pairing — Driver / Navigator (one laptop per pair)
- **Driver** — hands on keys; types what you *both* agree on.
- **Navigator** — hands off the keyboard; says the next idea in one sentence, then watches if it worked.
- **Swap at minute 30** (ring a bell — make it fun, not a reprimand).
- Pre-assign pairs: mix one confident-keyboard kid with one less-confident. Never pair two brand-new-to-mouse kids.
- *Why:* a 2024 study found pair programming **significantly improved computational thinking and self-efficacy in 4th graders**, cut syntax errors, and reduced fear of failure — and it halves your hardware need in a mixed Mac/Windows room.

### 5.7 The "Stuck? Try this" card (self-serve unblocking — same prompts as the menu, plus)
- If the game is blank / won't run, type: *"It didn't work. Open the game, find the problem, and fix it."* (Claude self-repairs well.)
- If you overwrote it: *"Undo my last change — the game was working before."*
- If you're just blank: pick any ★ remix from §5.5.

### 5.8 Creator Card + Certificate + Badges
- **Creator Card** (a paper slip per kid, fills in 2 min): *My name (fake/fun) ___ · My emoji ___ · My colour ___ · the sentence to type.* → becomes a keepsake.
- **Certificate**: *"I Made a Game with Claude Code 🎮"* — pre-fill the kid's name; leave a blank for **their** game's name (they write it themselves → ownership).
- **Creator Badges** (keep light, non-competitive — reward *behaviours*, not "best game"): 🚀 **First Launch** · 🎨 **Personalizer** · 🔍 **Debug Detective** (fixed a bug) · 🎧 **Remix Master** (2+ remixes) · 🤝 **Helper Hero** (helped a classmate) · 🎤 **Show-Off** (presented). Everyone can earn every badge. *Rewarding "Debug Detective" reframes errors as achievements — critical for AI-assisted coding.*

---

## §6 What goes wrong & how to fix it (the rescue table)

| Issue | Immediate fix |
|---|---|
| **Network/firewall blocks the AI** (the #1 day-of killer) | Shouldn't happen (whitelisted §0). If it does: call IT (pre-arranged) to whitelist live; **meanwhile pivot the whole class to Plan B (§7)** — never let them sit idle. |
| **App won't install/open on one machine** | Second adult fixes it off-side with the spare USB installer. Pair joins a neighbour's screen. *Never stop the whole class for one machine.* |
| **App shows a login/paywall** | Teacher enters the school workspace. Reinforce: *"Nobody types a login — if you see this, hand up."* |
| **A pair is stuck / blank-page freeze** | Hand them the "Stuck?" card (§5.7). If still stuck after 2 min, sit 90s and type the first prompt aloud together. |
| **Code Claude wrote doesn't run** | Kid types *"It didn't work. Open the game, find the problem, and fix it."* If still broken after one retry, restart from the clicker fallback prompt (§3). |
| **A kid finishes early** | Give ★★★ remixes; recruit them as **"Game Expert"** to help a neighbour (and earn Helper Hero). |
| **A kid types personal info** | Cut in calmly: *"Stop — rule 2, no real names or secrets."* Have them delete it. Reassure, don't shame. Reinforce the rule to the class once, briefly. |
| **API/rate limit hit (shared account)** | Throttle: pairs take a 5-min "design on paper" break while quota recovers; resume. Fallback to Plan B. *(Prevent: provision a workspace tier with adequate quota.)* |
| **Projector/adapter fails at showcase** | Pass-the-laptop gallery instead. Lower-tech, still works. |
| **A kid's game is unfinished at showcase** | Frame play-swap as *"show what you've got, even just the start."* The break-and-fix reframe already normalised unfinished = in-progress. |

**The "Oops, It Broke" reframe (protects momentum):** normalize it with *"Game devs break things all the time — that's how we learn. Let's be Debug Detectives."* Kid raises hand → helper arrives **in <60 seconds** → pastes the error back to Claude → kid watches it fix → badge earned.

---

## §7 Plan B — offline / no-AI fallback (explicit, announced — not silent)

> If the AI or network is down: it's **"Plan B"**, not "we failed." Frame the paper activity as real game design (it is).
- **If down at start:** open the pre-downloaded folder of **3 playable HTML games** on every laptop (no internet needed) → kids play one → then **redesign it on paper** (new rules, new character, new level) as game designers.
- **If down mid-lesson:** the game file Claude already wrote is *local* — it still runs. Pairs keep polishing in the browser; keen kids hand-edit colours/text in the HTML.
- Have the second adult retry the network every 5 min so you resume the moment it's back.
- **Absolute rule:** never let kids sit idle staring at a spinner.

---

## §8 "Other fun" — bonus ideas (early finishers / next lesson)

The user asked for "game *and other fun*." Beyond the main game, kids who finish early (or for a follow-up lesson) can ask Claude Code to build:

1. **Superhero Name & Emoji Generator** — type your name → get a hero identity, powers, a custom emoji crest.
2. **Mad-Libs Monster Story** — fill in words → Claude writes a ridiculous story starring the kid.
3. **Virtual Pet 🐾** — feed it, pet it, watch it react; it gets hungry over time.
4. **Choose-Your-Own-Adventure Story** — a branching story where the kid picks what happens next.
5. **Fake Chatbot Friend** — a chat pal that jokes, remembers the kid's (fake) name, roasts them gently.
6. **"All About Me" Web Page** — favourite colour, food, hobby, giant emoji → show parents.

> **Language note:** every prompt above works in the kids' **native language** too (Claude understands Russian, etc.). Kids can type in whatever language they think in — the game comes out in that language. (This whole packet is in English; say the word and I'll produce a Russian version.)

---

## §9 Scoring matrix — all 30 offers (I·E·C → P)

`I`=Impact on "every kid builds & owns a game, safely, wants more" · `E`=Effort/prep/risk (higher=harder) · `C`=Confidence/evidence · `P = I×C÷E`. **✅ = cherry-picked into the lesson above.** Many winners were merged (e.g., 3.3+6.1 → Creator Card; 3.4+5.4+6.2 → Remix/Stuck menu; 1.3+5.2 → pairing; 5.5+6.5+1.5 → showcase).

| # | Offer | I·E·C | P | Verdict |
|---|---|---|---|---|
| **Agent #1 — Pedagogy** | | | | |
| 1.1 | 3-beat energy map (I/we/you + brain breaks) | 5·1·5 | **25** | ✅ structural spine (§1, §2) |
| 1.2 | "Make it YOURS" menu | 4·2·5 | 10 | ✅ folded into Creator Card (§5.5/§5.8) |
| 1.3 | Driver/Navigator pair roles | 4·2·5 | 10 | ✅ merged with 5.2 (§5.6) |
| 1.4 | "Prompt or Wish?" contrast | 5·1·5 | **25** | ✅ conceptual core (§2 row 13–18, §1) |
| 1.5 | Show-and-tell remix close-out | 4·2·4 | 8 | ✅ folded into showcase (§2 finale) |
| **Agent #2 — Claude Code product** | | | | |
| 2.1 | Core loop Describe→Build→Run→Tweak→Repeat | 5·1·5 | **25** | ✅ the chant (§1) |
| 2.2 | Teacher-driven single screen (Mode A) | 4·1·5 | **20** | ✅ fallback mode (§0) |
| 2.3 | Pairs modify a starter (Mode B) | 5·3·4 | 6.7 | ✅ target mode (§0) |
| 2.4 | WOW live demo hook | 5·2·5 | 12.5 | ✅ (§5.1) |
| 2.5 | Honest "what it is/isn't/safe" mini-talk | 4·1·5 | **20** | ✅ (§4, §5.3) |
| **Agent #3 — Game curriculum** | | | | |
| 3.1 | Single-file HTML format | 5·1·5 | **25** | ✅ (§3) |
| 3.2 | Catch-the-treats default + clicker fallback | 5·1·5 | **25** | ✅ (§3) |
| 3.3 | Personalization baked into first prompt | 5·1·5 | **25** | ✅ merged into Creator Card |
| 3.4 | "Make it your own" extension menu | 5·1·5 | **25** | ✅ Remix Menu (§5.5) |
| 3.5 | Scope discipline (what NOT to build) | 4·1·5 | **20** | ✅ (§3) |
| **Agent #4 — Responsible AI** | | | | |
| 4.1 | "Planted-wrongness" demo (AI can be wrong) | 5·2·5 | 12.5 | ✅ single highest-leverage safety moment (§4) |
| 4.2 | "Super-smart parrot, not a friend" | 5·1·5 | **25** | ✅ (§4, §5.3 rule 3) |
| 4.3 | "Secrets stay out" (fake fun data) | 5·1·5 | **25** | ✅ (§5.3 rule 2) |
| 4.4 | "Honest about my helper" | 4·1·5 | **20** | ✅ (§5.3 rule 4, showcase sentence) |
| 4.5 | Teacher-owns-workspace + kindness rule | 5·2·5 | 12.5 | ✅ (§0 prerequisites, §5.3 rules 1+5) |
| **Agent #5 — Facilitation** | | | | |
| 5.1 | "First win in 10 min" guided build | 5·1·5 | **25** | ✅ (§2 row 20–30, §5.2) |
| 5.2 | Driver/Navigator + mid-lesson swap | 4·2·5 | 10 | ✅ merged with 1.3 (§5.6) |
| 5.3 | Mac/Windows room zoning | 3·1·4 | 12 | ✅ (§0 — Macs one side, Windows the other) |
| 5.4 | "Stuck? Try this" prompt menu | 4·1·5 | **20** | ✅ merged into §5.7 |
| 5.5 | Showcase-first time protection | 5·1·5 | **25** | ✅ (§2 finale, buffer rule) |
| **Agent #6 — Engagement** | | | | |
| 6.1 | "Personalize it first" protocol (Creator Card) | 5·2·5 | 12.5 | ✅ the spine of Beat 3 (§5.8) |
| 6.2 | Remix Menu (creative extension) | 5·2·5 | 12.5 | ✅ merged with 3.4 (§5.5) |
| 6.3 | Creator Badges (reward behaviours) | 3·2·4 | 6 | ✅ adapted, kept light (§5.8) |
| 6.4 | "Oops, it broke" reframe + rapid rescue | 5·2·5 | 12.5 | ✅ (§6) |
| 6.5 | Gallery walk + certificates finale | 5·2·5 | 12.5 | ✅ merged with 5.5 (§5.8, §2 finale) |

**Top scores (P ≥ 20):** the structural + conceptual + safety core — 1.1, 1.4, 2.1, 2.2, 2.5, 3.1–3.5, 4.2, 4.3, 4.4, 5.1, 5.4, 5.5. **Essential high-12.5s:** 4.1 (the planted-wrongness demo), 4.5 (account/kindness), 6.1 (Creator Card), 6.4 (rescue reframe), 6.5 (certificates). Lower-scored offers (6.3 badges, 1.5/5.3) were kept in **adapted** form because they're cheap and add delight without risk; nothing was dropped for being wrong, only for redundancy.

---

## §10 Sources (the research behind it)

- **Hsu (2025), *TechTrends* — "From Programming to Prompting"** — prompting *is* computational thinking; 5-principle constructionist prompting framework; worked example with 5th-class pupils. https://link.springer.com/article/10.1007/s11528-025-01052-6
- **Resnick (MIT Media Lab) — "low floor, wide walls, high ceiling"** + Scratch pedagogy. https://mres.medium.com/designing-for-wide-walls-323bdb4e7277 · https://dl.acm.org/doi/10.1145/1592761.1592779
- **ASCD — Gradual Release of Responsibility (I do / we do / you do).** https://www.ascd.org/el/articles/revisiting-the-rules-of-gradual-release-of-responsibility
- **Pair programming in 4th graders — 2024 study** (CT + self-efficacy gains). https://www.frontiersin.org/journals/education
- **Anthropic / Claude Code docs (desktop app, 2026).** https://code.claude.com/docs/en/desktop · **Anthropic legal (18+ account policy).** https://www.anthropic.com/legal
- **UNESCO — AI Competency Framework for Students** (ethics-of-AI dimension). https://www.unesco.org/en/articles/ai-competency-framework-students
- **Common Sense Education — AI Literacy Lessons + Generative AI in K-12.** https://www.commonsense.org/education/collections/ai-literacy-lessons-for-grades-6-12 · https://www.commonsensemedia.org/research/generative-ai-in-k-12-education-challenges-and-opportunities
- **TeachAI — Guidance for Schools Toolkit** (academic integrity, safety & respect). https://www.teachai.org/toolkit
- **Code.org — Hour of Code / Hour of AI** ("are you still the programmer?"). https://code.org/learn · https://studio.code.org/s/coding-with-ai/lessons/2
- **COPPA (under-13) + FERPA** — why the teacher/school must own the workspace. https://www.curriculumassociates.com/blog/ai-and-student-data-privacy

---

*Curated 2026-06-14 by a 6-agent scoring pass (Pedagogy · Product · Curriculum · Responsible-AI · Facilitation · Engagement), each researching current best practice, making distinct offers, and self-checking them. The lead scored all 30 offers (`I·E·C → P`) and cherry-picked the winners into this single teachable packet. Next action: confirm the §0 Mode-B prerequisites 3+ school days before, rehearse the §5.1 WOW demo, print the §5 assets, and teach straight off §2.*
