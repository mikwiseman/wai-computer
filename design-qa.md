# Design QA

- Reference: `/Users/mikwiseman/Documents/Code/wai-computer/artifacts/design/liquid-glass-spatial-studio-theme.png`
- Implementation: `/Users/mikwiseman/Documents/Code/wai-computer/artifacts/design/web-dashboard-final.png`
- Combined comparison: `/Users/mikwiseman/Documents/Code/wai-computer/artifacts/design/reference-vs-implementation-final.png`
- Comparison viewport: `1487 × 1058` CSS pixels
- Comparison state: authenticated dashboard, Pearl theme, Amber accent, Inbox split view, first recording selected

## Comparison history

1. Pass 1 established the pearl canvas, floating glass sidebar/header, opaque reading panels, split view, unified radii and Amber accent. The Appearance popover was clipped by the sidebar stacking context, and the mobile navigation consumed most of the first viewport.
2. Pass 2 moved sidebar scrolling to the navigation region, raised the sidebar stacking context, made the Appearance panel fully visible, and converted iPhone/iPad navigation into a compact horizontal glass shelf. A fixed mobile Appearance panel still inherited the glass ancestor's containing block and could crop.
3. Final pass anchored the responsive Appearance panel to its visible trigger, verified Pearl and Midnight plus live accent changes, added the functional Capture/Library/Ask Wai command dock, synchronized simultaneous appearance controls, and repeated the same-state desktop comparison. Responsive captures at `820 × 1180` and `390 × 844` showed no horizontal page overflow.

## Web dashboard result

passed

## Native verification

- iOS and macOS share the same appearance model and design tokens across onboarding, authentication, content, and settings surfaces.
- Release verification uses Swift package tests plus unsigned iOS Simulator and macOS builds.
- Native visual snapshots are not part of this web comparison artifact.

---

# Landing Design QA — 2026-07-21

## Visual truth

- Selected concept: `/Users/mikwiseman/.codex/generated_images/019f8337-ed7a-7aa2-b218-8164c59ec1eb/exec-b949bdfe-b20a-4e95-9563-733b20c31d6f.png`
- Implemented route: `http://localhost:3002/ru` from the production Next.js build
- Desktop state: 1440 × 1024 CSS px, DPR 1, light theme
- Mobile state: 390 × 844 CSS px, DPR 1, light theme
- Dark theme was also checked at 1440 × 1024 with the matching generated dark asset.

## Comparison evidence

- Full view: `artifacts/design-qa/landing-2026-07-21/reference-vs-implementation.png`
- Focused hero: `artifacts/design-qa/landing-2026-07-21/hero-reference-vs-implementation.png`
- Final desktop implementation: `artifacts/design-qa/landing-2026-07-21/final-ru-full.png`
- Final mobile hero: `artifacts/design-qa/landing-2026-07-21/final-ru-mobile-hero.png`
- Final mobile CTA: `artifacts/design-qa/landing-2026-07-21/final-ru-mobile-cta.png`

The selected source is a tall concept board, not a pixel-matched desktop frame. The comparison therefore checks the visible design system and hierarchy: pearl/amber palette, serif display type, glass lens hero, sparse memory checkpoints, real product proof, platform pills, privacy line, and final CTA.

## Findings and fix history

| Priority | Finding | Resolution |
| --- | --- | --- |
| P2 | The mobile final CTA inherited a large flex basis and became too tall. | Scoped the final CTA button to a 54 px touch-safe height; verified in the final mobile capture. |
| P2 | The desktop journey connector aligned only with the middle alternating checkpoint. | Removed the misleading desktop connector; retained the aligned vertical connector on mobile. |
| P2 | Manual theme selection initially needed parity with the OS theme asset. | Rendered explicit light and dark hero assets and tied their visibility to both `data-theme` and system preference. |

## Final checks

- No horizontal overflow at either viewport.
- No browser console warnings or errors on the production route.
- Primary hero CTA navigates to `/register`.
- Light/dark controls switch the hero asset and page theme together.
- EN and RU use the same component structure; RU legal/payment content remains present.
- No unresolved P0, P1, P2, or P3 findings.

final result: passed
