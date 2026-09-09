# English school website — 9 September 2026

The public WAI School homepage, all 12 student projects, the gallery and both
mentor profiles are available in English under wai.computer. The school seller
is WaiWai, LLC, Delaware, United States, as explicitly requested by Mik.
The company address and EUR 700 four-week / EUR 2,500 ten-lesson offers come from
the existing approved English company materials. Russian company details,
Russian affiliations, ruble prices and their logo assets were removed.

The homepage retains the source desktop animation and separate mobile layout.
Contact buttons lead to the English `/school/contact` enquiry page, with
`/legal/offer` and `/legal/privacy` covering the school pages. The contact action
opens the parent's email application. No booking or payment is automatically
created; teaching language and scheduling are confirmed with the parent.

## Published content

The source school landing build is from wai-school `bd4fe09b`, fingerprint
`7c6e504e24c3279c7fa311cff655db0e632c3ef94422b216764944a676697c1e`.
Source directories: `landings/wai-school-v2`, `landings/wai-school-magazine-v0`
and `landings/wai-school-mentors-v0`. Student demos were copied from the existing
public `/g2/project/…` and `/g3/project/…` publications on 9 September.

`public/school-static/student-projects/` contains Hallownest, Block Modz,
RIFFLEGG, QFA 26, FLEUR, MathAi, Naughty Kid, Escape the Game, Bug Battle,
Bunker Zombie, Striker Training and CheckMedia. Their interfaces, instructions,
stories, hints, answer feedback and canvas labels are in English. All 13
Minecraft packs include English manifests, item names and script messages.
`project-previews/` contains fresh browser screenshots of these English editions;
the old screenshots with Russian text have been removed.

Child author identifiers were anonymized. Project data uses the existing public
school service. A bounded server route adds `payload.site = "wai.computer"` to
new records and excludes all untagged original records when reading them for
this edition. It preserves upstream validation and quotas. Original projects,
reports, teaching materials, CRM and existing records were not changed.
MathAi retains its existing temporary multiplayer rooms. Student apps are
prototypes; CheckMedia labels its conversation as a demo.

## Routing and deployment

Next rewrites serve school pages and `/school/projects/<slug>` including nested
app pages and assets. The recording application's login, authenticated routes
and API retain their routes. Public `/ru` marketing routes redirect to English.
Application `/privacy` and `/terms` identify WaiWai, LLC; existing customer
billing contracts are not migrated by this publication.

Run `scripts/deploy-web.sh` from a clean, merged checkout. It builds the web
image locally for linux/amd64 using the existing Dockerfile and Sentry source
map upload. `deploy-web-server.sh` holds the production deployment lock, checks
a candidate container, replaces only web, and checks the public edge and origin.
It rolls back the web image if verification fails. The runtime env file and all
other container IDs are compared before/after; API, migrations and stopped
workers are not changed. The previous web image is saved beside the release.

## Verification

- Focused Vitest content, routing, JavaScript syntax and data-boundary tests.
- ESLint and production Next build.
- `web/scripts/school-smoke.py`: public pages, all 19 student HTML routes,
  referenced assets, all Minecraft archive contents, five bounded data routes,
  login, legal pages and the legacy homepage redirect.
- Codex in-app browser: desktop/mobile homepage and gallery, all 12 project
  interfaces, FLEUR's seven-question flow, MathAi correct answers including
  English units and its 30-task self-check, QFA match start, Bug Battle purchase
  and battle result, Naughty Kid clue and unlock, Pong restart, Bunker Zombie
  intro and game, Striker daily check-in and training, CheckMedia demo answer.
- Minecraft archives and downloads are checked; execution inside the Minecraft
  client has not been tested.
