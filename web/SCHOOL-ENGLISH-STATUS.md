# English school website — 9 September 2026

Work in progress. Nothing from this branch has been pushed or deployed.

The current wai.school homepage, the full 12-project gallery, and both public
mentor profiles have been translated, retaining their source layouts. The
homepage includes the separate desktop and mobile presentations. The generated
pages and assets live in `public/school-static`; Next rewrites cover `/`,
`/school/projects`, `/projects`, `/mentors/dima` and `/mentors/darya`.

Source: the wai-school checkout at `bd4fe09b`, whose public landing matches
`origin/main` as inspected on this date. Landing build fingerprint:
`7c6e504e24c3279c7fa311cff655db0e632c3ef94422b216764944a676697c1e`.
Source directories: `landings/wai-school-v2`, `landings/wai-school-magazine-v0`
and `landings/wai-school-mentors-v0`. Child names have been removed from the
English page copy and image descriptions; linked student projects remain the
original public work and may contain Russian interfaces.

## Questions awaiting the user

- Does “everything” mean the public site and enrolment, or also parent/student
  accounts, reports and teaching materials? Work so far covers the public pages
  listed above, not the whole product or every public route.
- Which seller and prices belong on wai.computer? The prior English draft at
  `codex/english-school-zen` uses Delaware WaiWai, LLC and EUR 700 / EUR 2,500.
  The current Russian site uses Russian OOO WAIWAI and starts at RUB 50,000/month.
  The current translation provisionally retains the Russian page's price. The
  correct offer and privacy pages cannot be selected from those conflicting
  sources without this decision.

## Remaining work

- Resolve those questions and finish the agreed scope. `/legal/privacy` and
  `/legal/offer` are still unimplemented on this branch; do not ship broken links.
- Localize enrolment. The current Cal.com event is Russian, including its title
  and description. `?locale=en` was tried in the real browser and did not switch
  the displayed interface, so that ineffective parameter was removed. No event,
  booking, calendar setting or CRM record has been modified.
- Translate other public routes if in scope: `/program`, `/calendar`, `/b2b`,
  `/schools`, and the other audience pages. No internal materials were changed.
- Review text inside project screenshots and linked original project interfaces
  against the final translation scope. Current pages distinguish original work.
- Finish browser QA across desktop sections, target links, keyboard/reduced
  motion, and the completed enrolment path.
- Integrate the verified branch and deploy. The existing full deploy script
  rebuilds API/web/worker services and runs migrations. Prefer a verified web
  deployment that preserves the running API and stopped workers; this has not
  been implemented or executed. Verify both edge and origin, plus existing
  app/login/API routes, after publication.

## Verification completed

- Production Next build passed, including TypeScript.
- Focused content/routing tests: 11 passed.
- ESLint for changed TypeScript passed; `git diff --check` passed after trimming
  whitespace in the imported HTML.
- The Codex in-app browser showed the desktop homepage hero and mobile homepage,
  gallery, and both mentor profiles. The Apps gallery filter showed exactly two
  projects. No console errors or warnings appeared on these inspected pages.
- The privacy checks covered page copy and descriptions; they do not establish
  consent for every identifier inside linked original student projects.

The original wai-school checkout and the earlier English worktree are unchanged.
