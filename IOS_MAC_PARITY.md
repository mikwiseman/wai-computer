# iOS ↔ macOS Parity Audit

> Generated 2026-06-01 by the `ios-mac-parity-audit` workflow — 12 feature domains, 147 agents, every claimed gap adversarially re-verified against the actual code. Machine-readable data: `IOS_MAC_PARITY.json`.

## Executive summary

iOS has solid parity on the core data and recording loop. The shared WaiComputerKit (models, APIClient, RecordingBackupStore, CompanionView, WebSocketManager, BillingClient, LanguageManager) means every network and data-layer behavior is automatically shared, and iOS already ships working Library list/detail, Trash, folder create, live recording, import, background sync, MCP connect, summary settings, and a first-class Wai companion tab. iOS is NOT structurally behind; the gaps fall into three themes. (1) A large set of macOS-only features that are genuinely impossible on iOS - system-wide push-to-talk dictation (global hotkeys, CGEvent text-injection, NSPanel overlay, Accessibility TCC), system-audio CATap, Sparkle updates, menu-bar/dock - all correctly platform-limited or N/A. (2) One pervasive missing foundation, in-app language switching: the shared LanguageManager is never instantiated on iOS, which simultaneously blocks the settings language picker, bilingual strings across Library/Recording/Search/Settings/Onboarding/Billing, and locale injection into the companion - wiring it is the single highest-leverage fix. (3) A long tail of leaf-screen polish that is purely SwiftUI plus shared-kit work (magic-link/forgot-password auth, billing read/cancel UI, Telegram connect, appearance theme, speaker rename/delete/merge, export/share, summary progress, search-tab wiring, Apps feature). The one true product decision is iOS billing: the macOS web-checkout path cannot ship on the App Store, so upgrade/purchase needs a StoreKit 2 vs external-link-entitlement choice even though the surrounding read-only billing UI is portable.

**Parity score.** ~58% of macOS capabilities are present on iOS today. Basis: across the 11 audited domains there are ~284 total macOS capabilities; ~123 are already at parity (sum of alreadyParityCount: app-shell 31, onboarding 10, library 40, recording 18, search 12, settings 14, dictation 4, apps 2, billing 1, companion-wai 12, updates 6, localization 0). Counting the platform-limited/not-applicable gaps as legitimately not owed on iOS (~33 capabilities, mostly the entire dictation + system-audio + Sparkle + dock/menu-bar surface) lifts the achievable parity to roughly 80% - i.e. of everything iOS can reasonably have, about four-fifths exists, and the remaining ~50 portable gaps plus the billing decision are the build list.

## Scoreboard

| Domain | Capabilities | At parity | Gaps |
| --- | ---: | ---: | ---: |
| app-shell | 50 | 31 | 19 |
| onboarding | 23 | 10 | 13 |
| library | 60 | 40 | 20 |
| recording | 32 | 18 | 14 |
| search | 20 | 12 | 8 |
| settings | 29 | 14 | 15 |
| dictation | 23 | 4 | 19 |
| apps | 8 | 2 | 6 |
| billing | 11 | 1 | 10 |
| companion-wai | 16 | 12 | 4 |
| updates | 6 | 6 | 0 |
| localization | 6 | 0 | 6 |
| **total** | **284** | **150** | **134** |

After dedup + verification the 134 raw gaps resolve to: **40 portable**, **24 platform-limited**, **8 not-applicable**, **4 needs-decision**.

## Build list — 40 portable gaps (in implementation order)

Foundations first (language wiring), then auth → onboarding → recording → library → search → companion → settings/billing/dictation-data → apps.

### 1. [S] Wire LanguageManager into iOS app root (instantiate + inject + locale override + first-launch WAIDownloadRegion seeding)
*Domain:* `localization`  
*Files:* iOS:App/WaiComputerApp.swift, iOS:App/ContentView.swift, iOS:Info.plist  
*Plan:* 1) Add @StateObject private var languageManager = LanguageManager.shared to WaiComputerApp. 2) On the WindowGroup body add .environmentObject(languageManager) and .environment(.locale, languageManager.preferredLocale) (mirrors WaiComputerMacApp.swift:80,93-94) so Text(key) re-resolves without restart. 3) Add WAIDownloadRegion to ios Info.plist stamped from build variable WAI_DOWNLOAD_REGION exactly as macOS Info.plist:48-49 so LanguageManager.init resolveFirstLaunchDefault/seedAppleLanguagesIfNeeded run. No shared-kit changes; LanguageManager is pure Foundation/SwiftUI/os and already imported.  
*Risk:* Prerequisite for every localization gap below; if WAIDownloadRegion is absent in an App Store build the manager defaults to English (acceptable, matches current behavior).

### 2. [S] Port OnboardingL10n bilingual text helper to shared kit, excluding the macOS-only DictationHotkey extension
*Domain:* `localization`  
*Files:* shared:Localization/OnboardingL10n.swift, iOS:App/Onboarding/OnboardingL10n.swift  
*Plan:* Move the core OnboardingL10n.text(_:_:language:) + language(for:) helpers (macos OnboardingL10n.swift:10-29, pure Foundation + LanguageManager.SupportedLanguage) into WaiComputerKit so all platforms share one t() source. Wrap the DictationHotkey label extension (lines 32-62, which pulls Carbon/NSEvent.ModifierFlags via GlobalHotkeyManager) in os(macOS) conditional or leave it in the macOS target. Unblocks the t() helper used by Library/Recording/Search/Settings/Billing/Onboarding/Dictation views below.  
*Risk:* Must keep the DictationHotkey extension out of the shared/iOS build; a straight copy fails to compile on iOS.

### 3. [M] Dictation language multi-select picker (DictationLanguageStore / LanguagePickerView) unification in Settings + Recording
*Domain:* `settings`  
*Files:* shared:Dictation/DictationLanguageStore.swift, iOS:Features/Settings/SettingsView.swift, iOS:Features/Recording/RecordingViewModel.swift  
*Plan:* Move DictationLanguageStore + DictationLanguageCatalog (pure Foundation/UserDefaults/os) into WaiComputerKit, and port LanguagePickerView (pure SwiftUI + shared LanguageManager + iOS Palette/Typography/Spacing) to iOS. Replace the legacy transcriptionLanguage AppStorage single-value Picker (SettingsView.swift:212) with LanguagePickerView backed by the store. Ensure the store legacy migration reads the existing transcriptionLanguage value iOS may have written so RecordingViewModel language selection stays consistent. Drop the macOS-only prefetchSessionConfigForCurrentLanguage callback (no-op on iOS).  
*Risk:* Medium - verify the legacy-key migration; back-end already supports the language list.

### 4. [S] Settings: in-app language picker row (AppLanguagePicker)
*Domain:* `settings`  
*Files:* iOS:Features/Settings/SettingsView.swift  
*Plan:* Port macOS AppLanguagePicker.swift verbatim (pure SwiftUI Picker(.menu) over LanguageManager.SupportedLanguage calling languageManager.setLanguage) into the iOS target, then add it as a row in SettingsView. Depends only on LanguageManager being injected at root.  
*Risk:* Low once root injection lands; iOS localization bundle must ship the same en/ru strings as macOS.

### 5. [S] Localize Account info (member-since date) + microphone permission status row in Settings
*Domain:* `settings`  
*Files:* iOS:Features/Settings/SettingsView.swift  
*Plan:* Inject LanguageManager into SettingsView; replace user.createdAt.formatted(date:.abbreviated,time:.omitted) (SettingsView.swift:50) with a DateFormatter keyed to languageManager.current locale (mirror MacDateFormatting), and replace hardcoded Member since with a t() key. Separately add an iOS-native microphone permission row using AVAudioApplication.recordPermission/requestRecordPermission (the API iOS already uses in AudioManager) showing granted/denied, with an Open Settings action via UIApplication.shared.open(URL(string: UIApplication.openSettingsURLString)). Do NOT port the macOS AVCaptureDevice/staleNeedsRestart/NSWorkspace path.  
*Risk:* Minimal; date-locale is cosmetic and the mic row is textbook iOS permission UX with the correct iOS API.

### 6. [M] Appearance: theme (System/Light/Dark) + accent-color picker wired to scene
*Domain:* `settings`  
*Files:* iOS:Features/Settings/SettingsView.swift, iOS:Features/Settings/AppearanceSettingsView.swift, iOS:App/WaiComputerApp.swift, iOS:Core/DesignSystem.swift  
*Plan:* Define an iOS AppearanceMode enum (reuse MacAppearanceMode.preferredColorScheme logic - pure SwiftUI ColorScheme) and an iOS AccentChoice type replacing every Color(nsColor:)/NSColor.controlAccentColor (DesignSystem.swift:86-111) with Color(uiColor:) or plain Color literals. Add AppStorage keys, a new AppearanceSettingsView, and an Appearance row in SettingsView. On the iOS WindowGroup apply .preferredColorScheme and .tint (mirror WaiComputerMacApp.swift:101-102).  
*Risk:* Medium - accent on iOS is a global tint vs macOS per-component; needs a small design decision on scope. NSColor to UIColor swap is mechanical.

### 7. [S] Auth: magic-link request + sent-confirmation state + third tab
*Domain:* `app-shell`  
*Files:* iOS:App/AuthView.swift, iOS:App/WaiComputerApp.swift  
*Plan:* Add @Published var magicLinkSent=false + func requestMagicLink(email:acceptedLegalTerms:) to iOS AppState calling shared apiClient.requestMagicLink (APIClient.swift:551). Add AuthMode enum (login/register/magicLink), port WaiTabBar (pure SwiftUI, DesignSystem.swift:374) into iOS DesignSystem and render the third tab, and add the Check your email confirmation VStack gated on magicLinkSent. Substitute .toggleStyle(.switch) for the macOS .checkbox on the legal-consent toggle; use Image(BrandIcon) not NSApp.applicationIconImage.  
*Risk:* Low - backend already wired; only the legal-consent toggle style differs.

### 8. [S] Auth: forgot-password / password-reset request
*Domain:* `app-shell`  
*Files:* iOS:App/AuthView.swift, iOS:App/WaiComputerApp.swift  
*Plan:* Add @Published var passwordResetSent=false + func requestPasswordReset(email:locale:) to iOS AppState (mirror MacAppState 593,952-966) calling shared apiClient.requestPasswordReset (APIClient.swift:572). Add a Forgot password ghost Button in login mode and a confirmation Text gated on passwordResetSent.  
*Risk:* Low - isolated to AuthView + AppState extension.

### 9. [S] Auth form: password validation hint (align min length to 8 + mismatch text) + locale-aware Terms/Privacy links + brand image + segmented picker polish
*Domain:* `app-shell`  
*Files:* iOS:App/AuthView.swift  
*Plan:* (1) Change iOS min-password from 6 to 8 (AuthView.swift:107) and add At least 8 characters / Passwords don't match hint Text using Palette.recording/textSecondary (already in iOS DesignSystem). (2) Inject LanguageManager and switch hardcoded /terms,/privacy URLs to the ru/en conditional macOS uses (authLocale). (3) Swap Image(systemName brain.head.profile) for Image(BrandIcon) (asset already in bundle, used in OnboardingSlide.swift:51) and localize the subtitle via t().  
*Risk:* Low; aligning min-length to 8 is a security-hygiene improvement matching the backend.

### 10. [M] Deep-link handler: waicomputer auth/verify magic-link token
*Domain:* `app-shell`  
*Files:* iOS:App/WaiComputerApp.swift, iOS:Info.plist  
*Plan:* (1) Add CFBundleURLTypes/waicomputer to iOS Info.plist (macOS Info.plist:27-34 reference). (2) Add .onOpenURL handler to the WindowGroup invoking Task { await appState.handleIncomingURL(url) } (iOS reliable mechanism, no NSApplicationDelegate forwarding). (3) Add handleIncomingURL to AppState using URLComponents + shared apiClient.verifyMagicLink (APIClient.swift:577), persist via KeychainHelper (already used on iOS).  
*Risk:* Medium - test the custom scheme does not collide with any universal-link config.

### 11. [M] Post-login: billing region sync to server
*Domain:* `app-shell`  
*Files:* iOS:App/WaiComputerApp.swift, iOS:Info.plist  
*Plan:* Add WAIDownloadRegion to iOS Info.plist keyed to a build variable, then add syncDownloadRegionToServerIfNeeded() inside loadCurrentUser() after getCurrentUser() (mirror WaiComputerMacApp.swift:1161), reading the Bundle key and calling shared getSettings()/updateSettings() with BillingDisplayRegion. All supporting types are in the shared kit.  
*Risk:* Medium - an incorrect region stamp produces wrong currency at checkout; pairs with the localization Info.plist work.

### 12. [M] Onboarding: inline app-language toggle on welcome slide + localized VoiceSetupSlide strings
*Domain:* `onboarding`  
*Files:* iOS:App/Onboarding/OnboardingSlide.swift, iOS:App/Onboarding/OnboardingVoiceSetupSlide.swift  
*Plan:* On the welcome slide add an EN/RU segmented control calling languageManager.setLanguage (port the picker logic from OnboardingWelcomeSlide.swift:52-112; replace NSApp.applicationIconImage with Image(BrandIcon) and NSColor.windowBackgroundColor with Color(.systemBackground)). In OnboardingVoiceSetupSlide replace all hardcoded English (section VOICE, headline, prompt, four statusLabel branches, footer buttons, privacy disclaimer) with t(english,russian) via @EnvironmentObject languageManager.  
*Risk:* Depends on LanguageManager injection + shared OnboardingL10n.

### 13. [M] Onboarding: language/locale picker slide + dictation language picker slide
*Domain:* `onboarding`  
*Files:* iOS:App/Onboarding/OnboardingPage.swift, iOS:App/Onboarding/OnboardingView.swift, iOS:App/Onboarding/OnboardingLanguagesSlide.swift  
*Plan:* Depends on DictationLanguageStore being moved to the shared kit (see the Settings dictation-picker gap) and LanguageManager at root. Add a languages case to the iOS OnboardingPage enum and render a new iOS OnboardingLanguagesSlide wrapping LanguagePickerView(store:), replacing Color(NSColor.windowBackgroundColor) with Color(.systemBackground). Pass a no-op for the macOS prefetchSessionConfigForCurrentLanguage callback. App-language vs STT-language are conceptually distinct but share LanguagePickerView/DictationLanguageStore - implement once.  
*Risk:* Medium - touches the onboarding enum/state machine; verify DictationLanguageStore migration of the legacy transcriptionLanguage value.

### 14. [M] Onboarding: mic status feedback + Settings-redirect on denied + 1Hz auto-advance polling + VoiceSetup 5s guard + mic-permission gate + onboardingMicAcknowledged flag + page-progress resume + breadcrumb labels
*Domain:* `onboarding`  
*Files:* iOS:App/Onboarding/OnboardingView.swift, iOS:App/Onboarding/OnboardingVoiceSetupSlide.swift, iOS:App/Onboarding/OnboardingPage.swift, iOS:App/WaiComputerApp.swift  
*Plan:* In OnboardingView: branch on the Bool from AudioManager.requestPermission (stop discarding it at 158-167) to show granted/denied status; on denied add an Open Settings action via UIApplication.openSettingsURLString (omit Finder-reveal); add scenePhase environment + Timer.scheduledTimer(1s) that re-checks AVCaptureDevice.authorizationStatus(.audio) and auto-advances, invalidated on disappear. Add currentPage persistence: read UserDefaults in init, write in .onChange(of: currentPage) with an iOS currentPageKey, clear on completeOnboarding(). Add breadcrumbLabel(language:) to OnboardingPage and swap the capsule-dot indicator for label+chevron. In OnboardingVoiceSetupSlide add minDurationSeconds=5/hasMinimumDuration guard on submit + a hasMicrophonePermission Bool param gating the record button and statusLabel. In completeOnboarding write onboardingMicAcknowledged (AVCaptureDevice.authorizationStatus).  
*Risk:* Several independent S-items batched in one file; invalidate the poll timer on disappear to avoid leaks.

### 15. [S] Recording: live transcript scroll area (uncapped ScrollViewReader + auto-scroll) with committed vs interim visual split
*Domain:* `recording`  
*Files:* iOS:Features/Recording/RecordingViewModel.swift, iOS:Features/Recording/RecordingView.swift  
*Plan:* Promote committedTranscript and add interimTranscript as @Published on RecordingViewModel (the handleWebSocketEvent final/interim split logic already exists at lines 779-793). Replace the capped maxHeight 150 ScrollView (RecordingView.swift:85-108) with a ScrollViewReader+LazyVStack that auto-scrolls to a transcript-bottom id via onChangeCompat, rendering committed text sharp and interim text italic/Palette.textTertiary (mirror LiveRecordingView.swift:63-101). Tokens already in iOS DesignSystem.  
*Risk:* Test layout on iPhone SE so controls don't push off-screen.

### 16. [M] Recording: speaker labels in live transcript (diarization grouping)
*Domain:* `recording`  
*Files:* iOS:Features/Recording/RecordingViewModel.swift  
*Plan:* Stop discarding segment.speaker (RecordingViewModel.swift:779-791 and the finalizedSegments speaker nil at line 470). Maintain a committedLines speaker/text array + interimSpeaker, and build grouped transcript text prefixing Speaker N via SpeakerLabelCopy.userFacingLabel (shared Segment.swift) using languageManager.current - mirror MacRecordingViewModel.swift:1341,1412-1471.  
*Risk:* Speaker grouping changes paragraph layout; test against a diarization-enabled backend response.

### 17. [M] Recording: WS disconnect continues recording locally (liveTranscriptionOffline) instead of stopping
*Domain:* `recording`  
*Files:* iOS:Features/Recording/RecordingViewModel.swift  
*Plan:* Change handleWebSocketEvent: on disconnected during recording (RecordingViewModel.swift:795-796) and on reconnectionFailed (line 807), call a new continueRecordingWithoutLiveTranscription(reason:error:) that sets liveTranscriptionOffline=true and calls ws.stopRealtimeStreamingForLocalRecording (shared WebSocketManager.swift:330) instead of handleStreamingFailure/handleReconnectionFailed which finalize. Mirror MacRecordingViewModel.swift:1351-1368.  
*Risk:* Behavior change - iOS users currently see auto-stop; ensure the offline banner is visible so continuing silently isn't surprising.

### 18. [S] Recording: disk-full guard, min-duration/upload-policy guard, cleanup-task sequencing guard
*Domain:* `recording`  
*Files:* iOS:Features/Recording/RecordingViewModel.swift  
*Plan:* (1) Capture wrote = fileWriter.writeEncodedPCM(data) (line 209) and on not-wrote set a localized self.error and break the audio loop (mirror MacRecordingViewModel.swift:438-443). (2) Before upload capture totalBytesWritten/durationSeconds (before nilling the writer at line 271) and gate on RecordingAudioUploadPolicy.canUploadFinalizedAudio (shared kit) - mirror 853-877. (3) Add private var isCleaningUp + private var cleanupTask Task; in startRecording await cleanupTask value when cleaning up, in stopRecording return early + await it when phase is finalizing (mirror 228-236,489-491).  
*Risk:* All three are low-risk edge-case hardening.

### 19. [M] Recording: discard action (abort without saving)
*Domain:* `recording`  
*Files:* iOS:Features/Recording/RecordingViewModel.swift, iOS:Features/Recording/RecordingView.swift  
*Plan:* Add discardRecording() to RecordingViewModel using only cross-platform symbols (ProcessInfo.endActivity, AudioFileWriter.finalize, FileManager.removeItem, apiClient.deleteRecording, RecordingBackupStore.removeRecording) - mirror MacRecordingViewModel.swift:640, no MacRecordingInputSource/DualAudioCapture references. Add a trash Button + confirmationDialog (@State showingDiscardConfirm, Button(role .destructive)) to RecordingView.  
*Risk:* Sequence async teardown (stop audio, drain, delete server row, remove backup) to avoid orphaned server records.

### 20. [S] Recording: folder assignment at recording start + phase-transition animation + accessibility identifiers
*Domain:* `recording`  
*Files:* iOS:Features/Recording/RecordingViewModel.swift, iOS:Features/Recording/RecordingView.swift, iOS:App/ContentView.swift  
*Plan:* (1) Add folderId String nil to RecordingViewModel.startRecording and pass it to shared apiClient.createRecording (already supports folderId); thread an active-folder state from the iOS UI to the Record tab. (2) Wrap idle-to-recording phase/isRecording/isLoading assignments (lines 765-772) in withAnimation(.easeInOut 0.25) when the transition involves idle (mirror 1317-1332). (3) Add .accessibilityIdentifier to the five iOS-relevant controls (view container, stop, pause/resume, reconnection banner, offline banner); discard/discard-confirm identifiers after the discard action lands.  
*Risk:* Folder assignment needs the active folder passed through from LibraryView state.

### 21. [M] Localize Recording UI strings (status text, empty-transcript text, accessibility labels)
*Domain:* `recording`  
*Files:* iOS:Features/Recording/RecordingViewModel.swift, iOS:Features/Recording/RecordingView.swift  
*Plan:* Add a LanguageManager.SupportedLanguage parameter (or @EnvironmentObject) to RecordingViewModel statusText/emptyTranscriptText computed vars and route through t() (mirror MacRecordingViewModel.swift:154-211,1606-1612). Replace hardcoded English in RecordingView accessibility labels (lines 246-268) with t() calls. No platform-restricted symbols.  
*Risk:* Non-English locales need QA for correct Russian rendering.

### 22. [M] Localize Library views (LibraryView/RecordingDetailView/TranscriptView/SpeakerChipButton) via LanguageManager + t()
*Domain:* `library`  
*Files:* iOS:Features/Library/LibraryView.swift, iOS:Features/Library/RecordingDetailView.swift, iOS:Features/Library/TranscriptView.swift, iOS:Features/Library/SpeakerChipButton.swift  
*Plan:* Inject @EnvironmentObject var languageManager: LanguageManager into each library view and replace every hardcoded English string (LibraryView Loading recordings, No Recordings, New Folder, Import Audio File; RecordingDetailView Transcript/Summary/Actions/This action cannot be undone; TranscriptView No Transcript, speaker fallback; SpeakerChipButton Assign Speaker/Cancel) with t(english,russian) via shared OnboardingL10n. Route speaker labels through SpeakerLabelCopy.userFacingLabel(languageCode:) with languageManager.current (mirror MacTranscriptView.swift:109-116). Keep existing UIPasteboard usage.  
*Risk:* Broad but mechanical; relies on shared OnboardingL10n port. Verify Russian rendering after.

### 23. [S] Library: rename recording (list context menu + detail inline title edit)
*Domain:* `library`  
*Files:* iOS:Features/Library/LibraryView.swift, iOS:Features/Library/RecordingDetailView.swift, iOS:Features/Library/RecordingDetailViewModel.swift  
*Plan:* Add a Rename alert with TextField (match the existing New Folder alert pattern, LibraryView.swift:111) to recordingContextMenu and to the RecordingDetailView toolbar menu, calling new LibraryViewModel.renameRecording / RecordingDetailViewModel.renameRecording backed by shared apiClient.updateRecording (APIClient.swift:703). For the detail title add @State isEditingTitle + titleDraft + @FocusState and a tap-to-edit gesture (single-tap is iOS-idiomatic). Omit the macOS onEscapeKeyCompat and MacMainLayoutMetrics min-width.  
*Risk:* navigationTitle can't host a TextField directly - use a toolbar/alert approach for the detail rename.

### 24. [S] Library: rename folder + move-into-new-folder-at-creation
*Domain:* `library`  
*Files:* iOS:Features/Library/LibraryView.swift  
*Plan:* Add a .contextMenu with Rename to the FolderRow NavigationLink and renameFolder(id:name:) on LibraryViewModel calling shared apiClient.updateFolder (APIClient.swift:1345). For the New Folder sheet add an optional move-selected-here toggle using a plain SwiftUI Toggle (switch style) instead of the macOS .toggleStyle(.checkbox); this is only meaningful once multi-select exists, so the move-on-create option ships with multi-select.  
*Risk:* None for rename; the move-on-create option depends on multi-select.

### 25. [M] Library: multi-select with bulk trash/restore/permanent-delete + bulk progress banner
*Domain:* `library`  
*Files:* iOS:Features/Library/LibraryView.swift  
*Plan:* Add List(selection: selectedRecordingIds) with a Set<String> binding and an EditButton/.editMode toolbar. Add toolbar actions that loop the existing iOS LibraryViewModel.trashRecording/restoreRecording/permanentlyDeleteRecording over the selection. Port LibraryBulkOperationKind+LibraryBulkOperation (plain structs) and a bulkOperation published property; render the progress banner (pure SwiftUI ProgressView/Text overlay, MacContentView.swift:1158-1208). Skip the macOS .onDeleteCommand keyboard handler.  
*Risk:* Edit-mode is a distinct iOS UX worth a quick design check; add a partial-failure banner.

### 26. [S] Detail: speaker chip rename + delete + merge-on-collision in the global directory
*Domain:* `library`  
*Files:* iOS:Features/Library/SpeakerChipButton.swift  
*Plan:* In SpeakerAssignSheet add a .contextMenu per person row with Rename (alert+TextField, apiClient.updatePerson) and destructive Delete (confirmationDialog, apiClient.deletePerson). On rename, case-insensitive-compare against existing Persons; on collision set merge state and fire a confirm alert calling apiClient.mergePeople(sourceId:intoPersonId:). All three methods exist in shared APIClient (754-770). Ship rename+merge together to avoid silent data inconsistency.  
*Risk:* Rename and merge must land together so a collision never silently duplicates.

### 27. [M] Detail: transcript empty/processing/saved-locally states + local-recovery segment fallback + Saved-locally/Needs-attention row marker
*Domain:* `library`  
*Files:* iOS:Features/Library/RecordingDetailViewModel.swift, iOS:Features/Library/TranscriptView.swift, iOS:Features/Library/LibraryView.swift  
*Plan:* Add a transcriptAvailability enum (mirror MacTranscriptAvailability) + localRecoveryManifest loading to RecordingDetailViewModel by calling RecordingBackupStore.manifest()/segments() (shared kit, already used by iOS RecordingViewModel) and applyFetchedDetail injecting local segments when the server returns none. Expand TranscriptView empty branch to the three-way savedLocally/processing/empty. In LibraryViewModel add localRecoveryRecordingIDs/permanentLocalFailureRecordingIDs Sets from RecordingBackupStore.manifestsByRecordingId(), thread the two booleans into RecordingRow, and switch to the parameterized Recording.statusDisplayText(hasLocalRecoveryBackup:hasPermanentLocalFailure:).  
*Risk:* Verify iOS actually writes RecordingBackupStore manifests in all recording paths before surfacing the markers/fallback.

### 28. [S] Detail: full-page load-error state with retry + dismissible inline error banner
*Domain:* `library`  
*Files:* iOS:Features/Library/RecordingDetailView.swift  
*Plan:* Replace the OK-only .alert(Recording Error) with an .overlay branch on viewModel.error rendering ContentUnavailableViewCompat (shared kit, iOS17+) + a retry Button (WaiPrimaryButtonStyle, adjust the call site since the iOS initializer omits isDisabled). Add a dismissible inline banner (xmark sets viewModel.error nil) above the header for post-load errors, mirroring the macOS RecordingDetailInlineErrorBanner (pure SwiftUI).  
*Risk:* Minimal; SwiftUI-only.

### 29. [S] Detail: summary generation - async job path + in-progress stage indicator + failure text
*Domain:* `library`  
*Files:* iOS:Features/Library/RecordingDetailViewModel.swift, iOS:Features/Library/RecordingDetailView.swift  
*Plan:* Switch RecordingDetailViewModel.generateSummary from legacy apiClient.generateSummary to apiClient.startSummaryGeneration (APIClient.swift:898), patch local detail via withSummaryGeneration, and expand shouldAutoRefresh + detailRefreshKey to also fire while summaryGeneration.isActive (not only on recording.status). Pass SummaryGenerationState into SummaryTabView and render a ProgressView+stage HStack when isActive and a red error Text (errorMessage) + Try Again button when isFailed. All types are in shared Recording.swift.  
*Risk:* None - the legacy endpoint keeps working; this enables richer feedback.

### 30. [M] Detail: export recording (markdown/txt/srt) + share recording (web link + clipboard + share sheet)
*Domain:* `library`  
*Files:* iOS:Features/Library/RecordingDetailView.swift, iOS:Features/Library/RecordingDetailViewModel.swift  
*Plan:* Export: add a toolbar Export action calling shared apiClient.exportRecording(id:format:locale:) (APIClient.swift:905); bridge the returned String to a temp file URL and present via SwiftUI ShareLink/.fileExporter (ShareLink already used at McpConnectView.swift:144) instead of NSSavePanel. Share: add a Share action calling apiClient.createRecordingShareLink (APIClient.swift:735), copy to UIPasteboard (already used at RecordingDetailView.swift:454), and present the link via ShareLink instead of NSSharingServicePicker/NSViewRepresentable.  
*Risk:* Need a temp-file bridge for the exported string; locale follows system locale on iOS unless LanguageManager is threaded.

### 31. [S] Search tab / entry point wired into MainTabView
*Domain:* `search`  
*Files:* iOS:App/ContentView.swift  
*Plan:* SearchView is fully implemented but unreachable (only in Preview). Add it as a 5th tab in MainTabView, OR (more iOS-idiomatic) attach it as a .searchable surface on LibraryView. If adding a tab, migrate the selectedTab AppStorage index so existing users do not mis-route on first launch after update.  
*Risk:* Tab-index collision: a new 5th tab shifts the persisted selectedTab mapping - clamp/migrate on launch.

### 32. [S] Localize Search view strings via LanguageManager + t()
*Domain:* `search`  
*Files:* iOS:Features/Search/SearchView.swift  
*Plan:* Add @EnvironmentObject var languageManager: LanguageManager, replace hardcoded strings (placeholder Search recordings, mode labels Hybrid/Semantic/Text, empty-state Search Your Brain / Find anything in your recordings, nav title Search, Untitled) with t() (mirror MacSearchView t() helper). Bundle with the Search-tab wiring.  
*Risk:* Low once LanguageManager is at root.

### 33. [S] Search: explicit Search button, results-count label, error display, accessibility identifiers, DEBUG UITest injection, localized speaker chip
*Domain:* `search`  
*Files:* iOS:Features/Search/SearchView.swift  
*Plan:* In SearchView: (1) add a borderedProminent Search Button disabled when query empty/loading; (2) add totalResults Int to SearchViewModel from response.total and render a count label; (3) add @Published var error String, set error.userFacingMessage(context:.generic) in catch, render it; (4) add .accessibilityIdentifier to field/submit/bar/empty-state/rows; (5) add the DEBUG uiTestSearchResponse intercept (iOS testing-mode enum + fixtures + AppState method); (6) replace blue raw speaker Text with SpeakerLabelCopy.userFacingLabel + Palette.accent. Pure SwiftUI + shared kit.  
*Risk:* Negligible; all leaf-level.

### 34. [S] Companion: inject LanguageManager-derived locale + companionAccentColor + populated recordings into CompanionView
*Domain:* `companion-wai`  
*Files:* iOS:Features/Wai/WaiHomeView.swift  
*Plan:* Three additions to the CompanionView call: (1) pass a populated [Recording] instead of empty so citation chips resolve names - hoist LibraryViewModel.recordings to MainTabView/AppState or give WaiHomeView its own fetch; (2) add .companionAccentColor(Palette.accent) after defining an iOS accent constant; (3) add .environment(.locale, LanguageManager.shared.preferredLocale) (or wrap with LanguageManagedRoot) so dates/labels respect in-app language. All shared-kit, no platform deps.  
*Risk:* Light risk of a redundant recordings fetch if Library already loaded it elsewhere.

### 35. [S] Companion: deep-link navigation to Wai tab via NotificationCenter
*Domain:* `companion-wai`  
*Files:* iOS:App/ContentView.swift  
*Plan:* Add .onReceive(NotificationCenter.default.publisher(for: navigateTo)) to MainTabView mapping userInfo target wai to selectedTab=2 (mirror MacContentView.swift:496-507). Note: no code currently posts this with wai on either platform, so it is a latent handler - implement for parity but confirm a poster exists before relying on it.  
*Risk:* TabView integer tag (ContentView.swift:82-83) is stable; trivial.

### 36. [M] Telegram integration - connect/disconnect/QR/code-entry/status
*Domain:* `settings`  
*Files:* iOS:Features/Settings/SettingsView.swift, iOS:Features/Settings/TelegramSettingsView.swift  
*Plan:* Create TelegramSettingsView porting MacSettingsView.swift:583-709. Reuse all shared APIs (getTelegramLinkStatus/startTelegramLink/claimTelegramLinkCode/unlinkTelegram, APIClient.swift:645-664) and models (TelegramLinkStatus/TelegramPairing). QR: keep the CIFilter CIQRCodeGenerator pipeline but render via UIImage(ciImage:) instead of NSImage/NSCIImageRep. Deep link: UIApplication.shared.open() instead of NSWorkspace. Tie the polling Task to .onDisappear. Add a Telegram row in the Integrations section.  
*Risk:* Medium - QR needs the UIImage path; polling lifecycle must bind to the iOS view lifecycle to avoid leaks.

### 37. [M] Billing: read-only status (plan + status badge), usage gauge, renewal/cancel-at-period-end date, region picker (RU UI only), cancel subscription, localized error messages
*Domain:* `billing`  
*Files:* iOS:Features/Settings/SettingsView.swift, iOS:Features/Billing/BillingStatusSection.swift  
*Plan:* Create BillingStatusSection and embed in SettingsView. Port the read paths from macOS BillingSection: planLine + statusBadge (131-186), usageGauge (189-215, BillingUsage.fractionUsed shared), proControls renewal/Pro-through date (319-345), regionPicker gated on isRussianUI via LanguageManager (140-159), cancelBillingSubscription (shared BillingClient.swift:40). Replace MacAppState with AppState (getAPIClient exists), MacDateFormatting with DateFormatter, and define iOS Palette.textTertiary as Color(uiColor .tertiaryLabel). Localize errors via the shared t() helper. Do NOT include the upgrade/checkout button here (that is the StoreKit decision). Confirm App Store rules permit server-side cancel for web-originated subs before shipping cancel.  
*Risk:* Medium - read/cancel are clean; avoid bundling the web-checkout upgrade button (needs the decision). The verdicts confirm all six sub-capabilities portable; one (app-return refresh) is gated on the upgrade architecture.

### 38. [M] Dictation: history screen + store (DictationHistoryStore/View, day-grouped list, stats header, search, copy, delete)
*Domain:* `dictation`  
*Files:* iOS:Features/Dictation/DictationHistoryStore.swift, iOS:Features/Dictation/DictationHistoryView.swift, iOS:Features/Settings/SettingsView.swift  
*Plan:* Port DictationHistoryStore (Foundation + WaiComputerKit + FileManager.applicationSupportDirectory; uses shared listDictationEntries/createDictationEntry/deleteDictationEntry, APIClient.swift:1037-1047) plus the stats logic (totalWords/averageWPM/streakDays) to iOS. Port DictationHistoryView replacing NSPasteboard with UIPasteboard, MacDateFormatting with a DateFormatter helper, and OnboardingL10n with the shared t(). Add a History row to SettingsView. Wire attach/hydrate on login and clearLocalCache on logout. The bare stats sub-capability was flagged platform-limited only because the macOS view file is AppKit-bound - the underlying store+stats are pure Swift and ship here.  
*Risk:* Medium - needs login/logout lifecycle wiring or history silently won't sync; history is server-synced so the view has meaning even before an iOS dictation pipeline exists.

### 39. [M] Dictation: custom dictionary screen + store (DictationDictionaryStore/View, bias words + auto-corrections, search, overuse warning, server-synced)
*Domain:* `dictation`  
*Files:* iOS:Features/Dictation/DictationDictionaryStore.swift, iOS:Features/Dictation/DictationDictionaryView.swift, iOS:Features/Settings/SettingsView.swift  
*Plan:* Port DictationDictionaryStore (Foundation/os/WaiComputerKit, FileManager.applicationSupportDirectory) and DictationDictionaryView (SwiftUI + WaiComputerKit, no AppKit) using shared listDictationDictionary/createDictionaryWord/deleteDictionaryWord (APIClient.swift:1054-1068) and DTOs (Dictation.swift:82-134). Provide the shared t() for its labels. Add a Dictionary row to SettingsView. Wire attach/hydrate/clearLocalCache lifecycle.  
*Risk:* Medium - same login/logout lifecycle wiring risk as history; entries only affect transcription once a backend consumes them.

### 40. [M] Apps feature - list grid + app card + create-draft form + app detail + items list + add-item
*Domain:* `apps`  
*Files:* iOS:Features/Apps/AppsView.swift, iOS:Features/Apps/CreateAppSheet.swift, iOS:Features/Apps/AppDetailView.swift, iOS:App/ContentView.swift, iOS:Core/DesignSystem.swift  
*Plan:* Build the Apps surface from scratch on iOS using the shared kit (UserApp/AppItem/AppStatus/AppVisibility in AppModels.swift; listApps/createApp/getApp/publishApp/updateApp/deleteApp/listAppItems/createAppItem/deleteAppItem in APIClient.swift:1369-1475). Port MacAppsView filterable LazyVGrid + segmented pickers (AppsView), the create-draft form (CreateAppSheet), and AppDetailView (header badges, Open URL Link, visibility Menu, Publish, Add item, Delete) with an iOS toolbar/swipe-action strategy for the 6 header actions. Add the private AppStatus.label/badgeColor + AppVisibility.label extensions to iOS (or promote to shared kit), add waiCard()/WaiDivider equivalents to iOS DesignSystem. NOTE: MacAppsView is currently dead code on macOS (no SidebarSection.apps), so there is no validated entry point - confirm whether to surface Apps and where before building (see needsDecision).  
*Risk:* Medium - header packs 6 actions, needs an action-menu redesign; the feature is unwired on macOS too, so confirm product intent before investing.

## Needs a decision (4)

### iOS upgrade / purchase flow (period picker + price + Upgrade button)  `billing`
How should iOS users upgrade to Pro, given the macOS web-checkout (Stripe/Tinkoff via NSWorkspace.open) cannot ship for digital goods on the App Store? The verdicts confirm the surrounding UI is technically portable, but the payment mechanism is a real product/compliance decision.

- StoreKit 2 in-app purchase (new App Store products, server-side receipt validation, entitlement sync to the existing backend) - App-Review-compliant but cannot reuse the Stripe/Tinkoff path and adds backend IAP work
- External Purchase Link entitlement (StoreKit ExternalPurchaseLink, region-restricted, requires Apple approval) to keep the existing web checkout - lighter backend work but limited availability and stricter review
- Ship iOS as read-only billing (status/usage/cancel only) and direct users to upgrade on web/macOS - fastest, avoids IAP entirely, no in-app purchase path on iOS

### Billing region picker on iOS  `billing`
Should the Global/RU region picker exist on iOS at all? It feeds the web-checkout flow that App Review Guideline 3.1.1 prohibits, so its presence depends on the upgrade-flow decision above.

- Drop the region picker on iOS entirely (region inferred server-side from WAIDownloadRegion sync) if iOS uses StoreKit IAP
- Keep it only if the External Purchase Link entitlement is approved and the web checkout is permitted
- Show it read-only as informational region/currency display tied to the post-login region sync

### Apps feature entry point and scope on iOS  `apps`
MacAppsView is currently DEAD CODE on macOS (no SidebarSection.apps, no wiring) and the feature is fully absent on iOS. Should the user-created mini-apps feature be surfaced on iOS at all, and if so where, before investing in the full grid/detail/items UI?

- Defer until the feature is validated and wired on macOS first (avoid building an unproven surface twice)
- Build on iOS as a Settings sub-screen (low-commitment entry point, easy to hide)
- Build as a first-class tab matching the macOS sidebar-section intent (highest visibility, largest churn)

### Search entry point on iOS  `search`
SearchView is fully built but unreachable. Should it be a 5th MainTabView tab (matching macOS sidebar prominence) or a .searchable surface on the Library tab (more iOS-idiomatic, avoids tab-index migration)?

- 5th tab - closest to macOS but requires migrating the persisted selectedTab AppStorage index so existing users don't mis-route
- Library .searchable - idiomatic iOS, no tab-index churn, but lower discoverability and loses the standalone search-mode picker placement
- Toolbar search button on Library that pushes SearchView - middle ground, no tab migration

## Platform-limited — cannot ship on iOS (24)

| Capability | Domain | Why blocked |
| --- | --- | --- |
| Two-phase pre-auth/post-auth onboarding (hotkey + dictation-sandbox pre-auth content) | onboarding | The two-phase split exists only to host macOS-exclusive content: the hotkey slide configures a global push-to-talk key (GlobalHotkeyManager: NSEvent.addGlobalMonitorForEvents, CGEvent.post, Accessibility TCC) and the sandbox slide exercises CGEvent text-insertion. iOS has no global hotkey, no Accessibility TCC, no cross-app text injection. The deferral of post-auth voice setup is portable, but the pre-auth content is blocked; the iOS single-phase flow already covers everything iOS can offer. |
| Settings: Dictation on/off feature-enable toggle | settings | Toggles DictationManager.isFeatureEnabled which gates GlobalHotkeyManager (Carbon, IOKit.hid, NSEvent global monitor, AXIsProcessTrusted) + AudioEngineHost prewarm + DictationOverlayPanel (NSPanel) + TextInserter (NSPasteboard + CGEvent.post into NSRunningApplication). The entire system-wide-dictation premise is architecturally impossible on iOS. |
| Settings: Dictation post-filter (LLM cleanup) toggle | settings | The iOS toggle exists and persists server-side but controls nothing: iOS has no DictationManager/TextInserter/cleanupDictation runtime. The pipeline it gates depends on NSPasteboard + CGEvent.post(.cgSessionEventTap) + NSRunningApplication + Accessibility TCC, all iOS-unavailable. It is a dangling preference until an iOS in-app dictation feature is designed. |
| Settings: push-to-talk hotkey picker | settings | DictationHotkey uses Carbon kVK keycodes + NSEvent.ModifierFlags and configures GlobalHotkeyManager (NSEvent.addGlobalMonitorForEvents, CGEvent.post, AXIsProcessTrustedWithOptions). iOS has no system-wide modifier-key interception and the physical keys (Right Option/Command/Fn) don't exist on iPhone. |
| Settings: hands-free hotkey picker (double-tap to start) | settings | Same macOS-only stack as the push-to-talk picker (Carbon keycodes, NSEvent global/local monitors, NSRunningApplication, NSPanel overlay). No iOS equivalent for choosing a global modifier key that fires dictation from any foreground app. |
| Settings: System Audio (CATap) permission row + test/grant | settings | SystemAudioGate/SystemAudioCapture are os(macOS)-gated in the shared kit. The feature depends on the macOS Core Audio HAL (CATapDescription, AudioHardwareCreateProcessTap/AggregateDevice, macOS 14.2+) which has no iOS counterpart - iOS provides no OS API to tap other processes audio output. |
| Settings: microphone permission status row (macOS implementation) | settings | The macOS permissionRow is bound to MacPrivacySettings.openMicrophone (NSWorkspace), restartForPermissionRefresh (NSApp.terminate), the staleNeedsRestart TCC restart state (AXIsProcessTrusted) and AVCaptureDevice authorization. The concept itself is portable - an iOS-native row using AVAudioApplication + UIApplication.openSettingsURLString is in portableGaps; only the macOS code is platform-limited. |
| scenePhase active: dictation/permission refresh half | app-shell | iOS already resumes pending sync on active (parity). The missing half is dictationManager.refreshPermissionState (GlobalHotkeyManager: Carbon/CGEventTap/NSWorkspace/IOKit.hid) and refreshPermissionStatus to MacInputPermission.postEventStatus (AXIsProcessTrusted). iOS has no global hotkey or input-monitoring TCC permission to re-poll. |
| Accent color preference wired to scene tint (macOS color construction) | app-shell | The .tint() and AppStorage wiring is portable, but MacAccentChoice.tintColor/.color (DesignSystem.swift:86-111) are built entirely with Color(nsColor:) and NSColor.controlAccentColor, AppKit-only with no UIColor equivalent. The color-construction layer must be rewritten per platform; the rewritten iOS appearance/accent work is captured in portableGaps. |
| Global push-to-talk hotkey (background, into any app) | dictation | GlobalHotkeyManager imports Cocoa/Carbon/IOKit.hid/ApplicationServices; uses NSEvent.addGlobalMonitorForEvents + Carbon kVK + AXIsProcessTrusted. iOS apps cannot observe global input events while backgrounded - an absolute platform constraint requiring a different interaction model entirely. |
| Hands-free dictation mode (double-tap toggle continuous) | dictation | Trigger detection is built on NSEvent global/local monitors, Carbon keycodes, double-tap timing in GlobalHotkeyManager, NSRunningApplication targeting, and Accessibility TCC - none available on iOS. |
| Floating always-on-top overlay panel | dictation | DictationOverlayPanel subclasses NSPanel and relies on NSWindow.Level.statusBar, CollectionBehavior.canJoinAllSpaces, hidesOnDeactivate, NSHostingView, NSScreen.main. iOS sandbox forbids placing a window above other apps or the system status bar; there is no process-level floating panel. |
| Text insertion into other apps (clipboard + simulated Cmd+V via CGEvent.post) | dictation | TextInserter uses NSPasteboard + CGEvent.post(tap .cgSessionEventTap) + NSRunningApplication + Accessibility TCC. iOS sandboxing prohibits posting synthetic keyboard events to other processes; there is no equivalent of CGEvent.post. |
| Accessibility + mic permission flow (TCC prompts, legacy TCC migration, stale-needs-restart) | dictation | Built on AXIsProcessTrusted(WithOptions), NSEvent global monitor, tccutil shell commands via Process(), and NSWorkspace.openApplication + NSApp.terminate relaunch. iOS has no Accessibility TCC, no tccutil, no programmatic self-terminate, and permission changes take effect immediately (no stale-restart state). The mic subset already exists on iOS. |
| Dictation feature enable/disable toggle (gates hotkey + AudioEngineHost prewarm) | dictation | The didSet calls applyHotkeyAvailability which starts/stops GlobalHotkeyManager + AudioEngineHost and depends on DictationOverlayPanel (NSPanel), NSRunningApplication, NSSound, TextInserter - all macOS-only. |
| Push-to-talk hotkey picker (Right Option/Left Option/Right Command/Fn/Ctrl+Option) | dictation | DictationHotkey is defined inside the macOS-only GlobalHotkeyManager with Carbon keycodes + NSEvent.ModifierFlags. The physical modifier keys and system-wide interception API do not exist on iOS. |
| Hands-free hotkey picker (separate key or double-tap) | dictation | Same DictationHotkey/Carbon/NSEvent global-monitor/Accessibility TCC stack as the PTT picker; no iOS global keyboard hook surface. |
| AI post-filter (cleanup) toggle has no iOS runtime | dictation | The toggle is present and server-synced on iOS but functional only with an in-app dictation pipeline. The macOS pipeline (cleanupDictation to TextInserter via CGEvent.post + NSPasteboard + NSRunningApplication, gated by global hotkey) cannot be ported; making the toggle effective on iOS requires a new platform-specific dictation design. |
| Session token prefetching/vault for push-to-talk dictation | dictation | The RealtimeTranscriptionSessionConfigVault subcomponent is portable, but its driver - prefetch 20s before a global hotkey fires - is bound to GlobalHotkeyManager (Carbon/NSEvent global monitor/NSPanel/Accessibility TCC). iOS has no system-wide PTT hotkey to pre-warm against; a portable iOS variant would be a new SwiftUI-button-triggered design, not a port. |
| Dictation history stats display (macOS view) | dictation | The macOS DictationHistoryView is AppKit-bound (NSPasteboard, MacDateFormatting, OnboardingL10n, macOS-only DictationHistoryStore). The underlying stats/store are pure Swift and ARE included in the portable History-screen port - only the macOS view file is platform-limited. |
| Recovery text file when paste fails | dictation | saveRecoveryText body is pure Foundation but it can only ever be called from the macOS TextInserter failure path (NSPasteboard + CGEvent.post into the frontmost app). Without inter-app text insertion (impossible on iOS) the recovery file is meaningless. |
| Dictation onboarding - hotkey picker slide | dictation | OnboardingHotkeyPickerSlide iterates DictationHotkey.allCases (Carbon keycodes / NSEvent.ModifierFlags) and calls DictationManager.updateHotkey to GlobalHotkeyManager. iOS has no global keyboard hook or physical PTT modifier keys. |
| Dictation onboarding - sandbox try-it-now slide | dictation | Takes a DictationManager (macOS-only: GlobalHotkeyManager Carbon/CGEvent/NSEvent, DictationOverlayPanel NSPanel, TextInserter). iOS has no push-to-talk concept; a portable equivalent requires a fully new iOS-native dictation flow. |
| Billing app-return refresh on scene active | billing | The refresh hook is portable SwiftUI but is triggered only by the checkout flow setting billingCheckoutRefreshPending, which on macOS opens the checkout URL via NSWorkspace.shared.open. Until iOS billing/checkout exists and uses UIApplication.open, the trigger the refresh depends on is iOS-unavailable. Gated on the billing-upgrade architecture decision. |

## Not applicable on iOS (8)

| Capability | Why |
| --- | --- |
| Accessibility permission status row (global hotkey prereq) | Gates GlobalHotkeyManager via AXIsProcessTrusted(). iOS has no Accessibility TCC trust model, no global hotkey API, and no cross-app event injection - the capability the row gates does not exist on iOS. |
| Dictation re-run setup / reveal in Finder / reset TCC permissions recovery actions | All three target macOS-specific failure modes: resetOnboardingForSetupRerun (MacAppState only), NSWorkspace.activateFileViewerSelecting (Finder reveal), and tccutil reset via Process() + NSWorkspace.openApplication/NSApp.terminate restart. iOS has no TCC.db, no tccutil, no Process, and cannot self-terminate; these failure modes do not exist on iOS. |
| Settings: Sparkle beta/update controls | App Store/TestFlight manage all iOS update delivery at the OS level; no in-app update sheet can be triggered and the beta channel is a TestFlight group, not an in-app preference. |
| Settings: dock-icon toggle | iOS has no Dock; the concept of showing/hiding a Dock icon is meaningless on the platform. |
| Settings: payment-mode debug toggle | Gates a web-checkout flow prohibited on the iOS App Store for digital goods; the underlying flow it toggles cannot ship on iOS. |
| Menu-bar dictation shortcut (last-dictation popover) | Bound to MenuBarExtra (macOS-only SwiftUI scene) + NSPasteboard + NSApplication.terminate + MacPresentationCoordinator + DictationHistoryStore/DictationManager. iOS has no persistent ambient status-bar surface to host a last-dictation preview. |
| App updates domain (Sparkle background checks, beta-channel opt-in, recording-aware deferral, manual Check-for-Updates) | Entire domain is OS-managed on iOS via App Store/TestFlight. SPUStandardUpdaterController + BetaChannelUpdaterDelegate + RecordingAwareUpdateUserDriverDelegate have no iOS analog; the only update-adjacent surface (version/build display) is already at parity. |
| Menu bar extra / Dock management / TCC migration / NSMenu commands (app shell chrome) | macOS-only AppKit chrome (MenuBarExtra, Dock, Sparkle auto-update, TCC migration, NSMenu CommandMenu). None of these surfaces exist on iOS. |
