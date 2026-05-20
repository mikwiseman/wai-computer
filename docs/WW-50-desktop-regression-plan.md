# WW-50 Desktop Regression Plan

Source of truth for the current desktop/web/auth/billing cleanup pass. Screenshots below refer to the image numbers from the Codex thread. Keep this file updated before adding, changing, or closing items.

## Rules

- Quality over speed: fix the real source, not just the visible symptom.
- No silent fallbacks: errors must be explicit and diagnosable.
- Test each critical flow before marking it done.
- Commit and push finished batches; release to the stable macOS channel when the full checklist is green.
- New user-reported issues go into the queue here first, then implementation follows this order unless a blocker forces a dependency change.

## Prior Checklist To Re-Verify

These items were already handled in the previous pass, but must be regression-checked before final sign-off.

- [ ] P01. Onboarding voice screen: mention minimum useful recording length and dictation context. Screenshot: earlier Image #1.
- [ ] P02. New Recording screen: remove the "recordings shorter than 5 seconds" hint. Screenshot: earlier Image #2.
- [ ] P03. Toolbar icon consistency. Screenshot: earlier Image #3.
- [ ] P04. Move Search near Wai in the sidebar. Screenshot: earlier Image #4.
- [ ] P05. Remove Meetings, Notes, Reflections from the sidebar. Screenshot: earlier Image #5.
- [ ] P06. New Folder modal: fix button sizing. Screenshot: earlier Image #6.
- [ ] P07. Fix shifted layout in folder/recording views. Screenshot: earlier Image #7.
- [ ] P08. Do not pin the main window to the top edge on launch/reopen. Screenshot: earlier Image #8.
- [ ] P09. Make the recording-title column wider by default. Screenshots: earlier Images #9 and #10.
- [ ] P10. Simplify New Recording choices to recording and file import; Cmd+N should start recording. Screenshot: earlier Image #11.
- [ ] P11. Recording stop button must match the app button style and fit at small widths. Screenshot: earlier Image #12.
- [ ] P12. Move-to-folder menu must not show broken "Unfiled" behavior. Screenshot: earlier Image #13.
- [ ] P13. Shared note duration must show duration, not recording time. Screenshot: earlier Image #14.
- [ ] P14. Payment test card failure after checkout must be handled correctly. Screenshot: earlier Image #15.
- [ ] P15. Audit translations across all supported app languages, not only Russian. Screenshots: earlier Images #16, #22-#26.
- [ ] P16. Russian app language should default billing to RUB. Screenshot: earlier Image #17.
- [ ] P17. Billing region labels should be simple: "USD via Stripe" and "RUB via T-Bank"; no World/Russia phrasing. Screenshot: earlier Image #18.
- [ ] P18. 15-inch sidebar collapse icon must not overlap. Screenshot: earlier Image #19.
- [ ] P19. Rename popover layout must fit and use consistent button sizing. Screenshot: earlier Image #20.
- [ ] P20. Add folder rename.
- [ ] P21. Folder delete must exist and work. Screenshot: earlier Image #27.
- [ ] P22. Keep rename/create popover buttons visually consistent. Screenshot: earlier Image #21.
- [ ] P23. Onboarding right-side preview/text must be visible. Screenshot: earlier Image #28.
- [ ] P24. Onboarding must allow going backward. Screenshot: earlier Image #29.
- [ ] P25. Onboarding start must allow choosing app language. Screenshot: earlier Image #30.
- [ ] P26. Remove Help from onboarding. Screenshot: earlier Image #31.
- [ ] P27. Hotkey selection should update immediately when a key card is clicked. Screenshot: earlier Image #32.
- [ ] P28. Non-Russian language must not show multiple payment-region choices; only Stripe. Screenshot: earlier Image #33.
- [x] P29. Remove Stripe trial wording; free weekly words are the trial. Screenshot: earlier Image #34. Fixed by removing Stripe trial days from checkout creation.
- [ ] P30. Free plan must show 3,000 words/week; paid quota must be explicit in UI after margin review. Screenshot: earlier Image #35.

## Current Queue

- [ ] C29. Old app icon still appears in onboarding welcome; replace with current icon everywhere. Screenshot: current Image #1.
- [ ] C30. Rewrite Russian onboarding "two ways to use WaiComputer" copy in polished, market-appropriate Russian. Screenshot: current Image #2.
- [ ] C31. Permission step right-side illustration looks strange; redesign or remove the fake permission preview. Screenshot: current Image #3.
- [ ] C32. Permission step needs equal spacing and no text overlap. Screenshot: current Image #4.
- [ ] C33. Permission notification/banner still in English in Russian UI. Screenshot: current Image #5.
- [ ] C34. macOS microphone permission explanation still mixes English and Russian. Screenshot: current Image #6.
- [ ] C35. System audio permission appears green even when the app cannot actually record meeting/system sound; fix real permission detection and onboarding state. Screenshots: current Images #7 and #8.
- [ ] C36. Localize hotkey labels/icons for Russian. Screenshot: current Image #9.
- [ ] C37. Onboarding dictation sandbox duplicates text from one utterance. Screenshot: current Image #10.
- [ ] C38. Search layout has a large shifted empty top area. Screenshot: current Image #11.
- [ ] C39. Search view text is still English in Russian UI. Screenshot: current Image #12.
- [ ] C40. Wai section text is still English in Russian UI. Screenshot: current Image #13.
- [ ] C41. Dictionary view text is still English in Russian UI. Screenshot: current Image #14.
- [ ] C42. Dictation History view is partially untranslated. Screenshot: current Image #15.
- [ ] C43. New Folder modal buttons/layout need polish. Screenshot: current Image #16.
- [ ] C44. Recording status phrases are untranslated. Screenshot: current Image #17.
- [ ] C45. No-speech/noise recordings get English titles/comments despite Russian app/settings. Screenshot: current Image #18.
- [ ] C46. New Recording screen still uses the old icon. Screenshot: current Image #19.
- [ ] C47. Replace awkward Russian "саммари" wording with clearer product language. Screenshot: current Image #20.
- [ ] C48. Summaries for Russian transcripts are generated in English. Screenshot: current Image #21.
- [ ] C49. Remove the Actions tab/section from recording detail. Screenshot: current Image #22.
- [ ] C50. Microphone warning icon shows while permissions are granted; fix permission/status logic. Screenshot: current Image #23.
- [ ] C51. Transcription model descriptions in Settings are English in Russian UI. Screenshot: current Image #24.
- [ ] C52. Login/register/magic-link screen is English; default should follow system language and use Russian when system is Russian. Screenshot: current Image #25.
- [ ] C53. Magic-link email text is English; localize email templates and related messages. Screenshot: current Image #26.
- [ ] C54. Browser "Open WaiComputer App" auth page is English; localize app-open/browser fallback pages. Screenshot: current Image #27.
- [ ] C55. Auth best practice: make email login/magic link the primary flow for any email, including new users; keep password as secondary, add explicit reset path. Screenshot: current Image #28.
- [ ] C56. Add "forgot password" to password login. Screenshot: current Image #29.
- [ ] C57. New user registration fails; fix backend/client flow and show localized, specific errors. Screenshot: current Image #30.
- [ ] C58. Folder toolbar action purpose is unclear; make the folder action understandable and discoverable. Screenshot: current Image #31.
- [ ] C59. Recording detail header does not adapt at narrow width. Screenshot: current Image #32.
- [ ] C60. Summary generation loader appears outside the selected recording; scope loading state to the active recording only. Screenshot: current Image #33.
- [x] C61. After T-Bank checkout/cancel, `/billing/cancel` page is English and visually broken; localize, polish, and route users back cleanly. Screenshot: current Image #59. Fixed with localized RU/EN billing result pages and provider-specific checkout return URLs.
- [x] C62. While a new recording is still processing, the detail view says "No transcript"; show an explicit processing/preparing state instead. Screenshot: current Image #60. Fixed in web and macOS transcript empty states.
- [x] C63. Public shared note page still shows the old logo; replace it with the current brand mark. Screenshot: current Image #61. Fixed by serving the current brand mark and masking web shared/new-recording marks from it.
- [x] C64. Rename modal/popover is too narrow on macOS; widen it and keep the field/actions readable. Screenshot: latest user item 63. Fixed by widening speaker assignment popover and folder rename/create sheets, including readable text fields and stable action button widths.
- [ ] C65. After T-Bank payment, the subscription status does not update to Pro in the macOS settings view. Screenshot: latest user item 62. Backend webhook ACK was fixed to exact plain `OK` and deployed; still needs live valid T-Bank payment/status verification and macOS refresh check.
- [x] C66. T-Bank success/cancel pages must be Russian and polished even if the browser lands on `/billing/success` or `/billing/cancel`. Screenshots: latest user items 59 and 61. Fixed with `provider=tinkoff&lang=ru` return URLs plus localized result pages.
- [x] C67. Stripe checkout must not offer or mention a 14-day trial; the free weekly word quota is the free tier. Screenshot: latest checkout trial image. Fixed by sending no trial period to Stripe checkout.
- [x] C68. T-Bank test-card failures, including the Stripe test card `4242 4242 4242 4242`, must show a clear Russian failed-payment page instead of generic English cancel copy. Screenshot: latest user item 59. Fixed by using Russian T-Bank cancel copy that explains card/provider mismatch.

## Research Notes

- [ ] R01. Confirm passwordless/new-user email auth best practices against official guidance.
- [ ] R02. Confirm macOS microphone/system-audio permission behavior and best practices for explaining/requesting permissions.

## Verification Matrix

- [x] V01. macOS build: `xcodebuild -project macos/WaiComputer/WaiComputer.xcodeproj -scheme WaiComputer -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build`.
- [x] V02. Swift tests: `cd shared/WaiComputerKit && swift test -q`.
- [ ] V03. Backend tests for auth/billing/summary language changes.
- [x] V04. Web lint/tests for auth and billing pages.
- [ ] V05. Manual macOS pass in English and Russian: onboarding, permissions, new recording, import, search, dictionary, history, Wai, settings, recording detail.
- [ ] V06. Manual auth pass: login, magic link, new email, password reset, app-open/browser fallback.
- [ ] V07. Manual billing pass: Stripe USD, T-Bank RUB, success/cancel pages, free weekly word limit display.
- [ ] V08. Stable macOS release and production URL/appcast verification.

## Verification Log

- 2026-05-20: `cd web && pnpm lint` passed.
- 2026-05-20: `cd web && pnpm exec vitest run src/app/pages.test.tsx src/components/RecordingDetailPanel.test.tsx` passed, 32 tests.
- 2026-05-20: `cd web && pnpm build` passed.
- 2026-05-20: `cd backend && ruff check .` passed.
- 2026-05-20: `cd backend && pytest -q tests/test_billing_tinkoff.py --no-cov` passed, 16 tests.
- 2026-05-20: `cd shared/WaiComputerKit && swift test -q` passed, 410 tests.
- 2026-05-20: `xcodebuild -project macos/WaiComputer/WaiComputer.xcodeproj -scheme WaiComputer -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build` passed.
- 2026-05-20: Billing pass recheck: `cd backend && pytest -q tests/test_billing_tinkoff.py --no-cov` passed, 17 tests.
- 2026-05-20: Billing/pass recheck: `cd backend && ruff check .` passed.
- 2026-05-20: Billing/pass recheck: `cd web && pnpm exec vitest run src/app/pages.test.tsx src/components/RecordingDetailPanel.test.tsx` passed, 32 tests.
- 2026-05-20: Billing/pass recheck: `cd web && pnpm lint` passed.
- 2026-05-20: Billing/pass recheck: `cd web && pnpm build` passed.
- 2026-05-20: Commit `ba1ab237 fix: polish billing results and processing states` pushed to `origin/main`.
- 2026-05-20: Server deploy completed with `VPS_USER=root ./scripts/deploy-server.sh`; `/health` returned healthy with database connected.
- 2026-05-20: Live `https://wai.computer/billing/cancel?provider=tinkoff&lang=ru` served Russian failed-payment copy and explicitly explained that `4242 4242 4242 4242` is a Stripe test card, not a T-Bank card.
- 2026-05-20: Live `https://wai.computer/billing/success?provider=tinkoff&lang=ru` served Russian success copy.
- 2026-05-20: Live `https://wai.computer/billing/cancel` still served the generic English Stripe cancel page, as intended for non-Russian/non-T-Bank checkout.
- 2026-05-20: Live `https://wai.computer/brand-mark.svg` served the current brand mark asset.
- 2026-05-20: C64 macOS UI build passed with `xcodebuild -project macos/WaiComputer/WaiComputer.xcodeproj -scheme WaiComputer -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build` after widening the speaker assignment popover and folder name sheets.
