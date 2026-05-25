import Foundation
import AVFoundation
import SwiftUI
import os
import WaiComputerKit

private let log = Logger(subsystem: "is.waiwai.computer.app", category: "dictation")

private final class DictationAudioSendCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var chunks = 0
    private var bytes = 0

    func reset() {
        lock.lock()
        chunks = 0
        bytes = 0
        lock.unlock()
    }

    func record(bytes byteCount: Int) {
        lock.lock()
        chunks += 1
        bytes += byteCount
        lock.unlock()
    }

    func snapshot() -> (chunks: Int, bytes: Int) {
        lock.lock()
        defer { lock.unlock() }
        return (chunks, bytes)
    }
}

/// Orchestrates the complete dictation flow:
/// Hotkey → mic capture → provider-backed streaming → text delivery.
@MainActor
final class DictationManager: ObservableObject {

    enum State: Equatable {
        case idle
        case connecting
        case listening
        case processing
        case inserting
    }

    // MARK: - Published State

    @Published private(set) var state: State = .idle
    @Published private(set) var interimTranscript = ""
    @Published private(set) var dictationDuration: TimeInterval = 0
    @Published private(set) var isHandsFree = false
    /// Final transcript from the most recently completed dictation, set just
    /// before TextInserter runs. Lets sandboxes (e.g. the onboarding "Try it
    /// now" slide) display the result without depending on paste-into-focused-
    /// field, which is fragile when the dictation overlay grabs window focus.
    @Published private(set) var lastFinalTranscript: String?
    @Published var isEnabled = false
    @Published var error: String?

    // MARK: - Settings (persisted via UserDefaults)
    //
    // We use @Published + manual UserDefaults persistence rather than @AppStorage
    // because @AppStorage in an ObservableObject (vs in a SwiftUI View) is known
    // to drop writes that originate from method calls instead of property
    // bindings — every time the user picks a hotkey or toggles "Enable
    // Dictation" we'd lose the value on relaunch. Manual didSet is boring and
    // bulletproof.

    static let hotkeyDefaultsKey = "dictationHotkey"
    static let handsFreeHotkeyDefaultsKey = "dictationHandsFreeHotkey"
    static let aiCleanupDefaultsKey = "dictationAICleanup"
    static let enabledDefaultsKey = "dictationEnabled"

    @Published var hotkeyChoice: String {
        didSet {
            guard hotkeyChoice != oldValue else { return }
            UserDefaults.standard.set(hotkeyChoice, forKey: Self.hotkeyDefaultsKey)
        }
    }

    @Published var handsFreeHotkeyChoice: String {
        didSet {
            guard handsFreeHotkeyChoice != oldValue else { return }
            UserDefaults.standard.set(handsFreeHotkeyChoice, forKey: Self.handsFreeHotkeyDefaultsKey)
        }
    }

    @Published var aiCleanupEnabled: Bool {
        didSet {
            guard aiCleanupEnabled != oldValue else { return }
            UserDefaults.standard.set(aiCleanupEnabled, forKey: Self.aiCleanupDefaultsKey)
        }
    }

    @Published var isFeatureEnabled: Bool {
        didSet {
            guard isFeatureEnabled != oldValue else { return }
            UserDefaults.standard.set(isFeatureEnabled, forKey: Self.enabledDefaultsKey)
            applyHotkeyAvailability()
            if !isFeatureEnabled {
                let vault = sessionConfigVault
                Task { await vault?.clear() }
                Task { await cancelDictation() }
            } else {
                prefetchDictationSessionConfig(reason: "feature_enabled")
            }
        }
    }

    var selectedHotkey: DictationHotkey {
        DictationHotkey(rawValue: hotkeyChoice) ?? .defaultPushToTalk
    }

    /// Optional dedicated hotkey for toggling hands-free mode. Empty string
    /// stored = use legacy double-tap of `selectedHotkey` instead.
    var selectedHandsFreeHotkey: DictationHotkey? {
        guard !handsFreeHotkeyChoice.isEmpty else { return nil }
        return DictationHotkey(rawValue: handsFreeHotkeyChoice)
    }

    // MARK: - Dependencies

    private var apiClient: APIClient?
    private var sessionConfigVault: RealtimeTranscriptionSessionConfigVault?
    private var canStartDictation: (() -> Bool)?
    private var canStartDictationReason: (() -> String)?
    private var cachedSettings: UserSettings?
    private var cachedSettingsLoadedAt: Date?
    private let settingsCacheTTL: TimeInterval = 60
    var historyStore: DictationHistoryStore?
    var dictionaryStore: DictationDictionaryStore?
    var languageStore: DictationLanguageStore?
    let hotkeyManager = GlobalHotkeyManager()

    // MARK: - Instrumentation

    /// Per-press observability session. Tracks signposts + Sentry breadcrumbs.
    /// `nil` outside an active dictation.
    private var instrumentationSession: DictationInstrumentation.Session?

    // MARK: - Overlay

    private var overlayPanel: DictationOverlayPanel?

    // MARK: - Target App (for restoring focus before paste in direct builds)

    private var targetApp: NSRunningApplication?

    // MARK: - Dictation pipeline

    // Provider-backed dictation path for Soniox, Deepgram, and Inworld.
    private var providerSession: (any ProviderSession)?
    private var providerCapture: MicrophoneCapture?
    private var providerAudioTask: Task<Void, Never>?
    private var sessionEventTask: Task<Void, Never>?

    // OpenAI realtime STT path — account settings default to
    // `gpt-realtime-whisper` for dictation.
    private var openAISession: OpenAIRealtimeTranscriptionSession?
    private var openAICapture: MicrophoneCapture?
    private var openAIAudioTask: Task<Void, Never>?

    // ElevenLabs rollback path state — owned only when useElevenLabsForDictation
    // is true. Mirrors the pre-Phase-4 (build ≤56) working path: a fresh
    // MicrophoneCapture per session, NOT the shared AudioEngineHost. The
    // AudioEngineHost.lease() path was Phase 4-new and never validated against
    // ElevenLabs in production — using MicrophoneCapture (which the working
    // pre-Phase-4 dictation used) avoids that incompatibility.
    private var elevenLabsWebSocket: WebSocketManager?
    private var elevenLabsCapture: MicrophoneCapture?
    private var elevenLabsAudioTask: Task<Void, Never>?
    private var elevenLabsEventTask: Task<Void, Never>?

    private var timerTask: Task<Void, Never>?

    // Transcript accumulation (live updates for overlay).
    private var committedTexts: [String] = []
    private var currentInterim = ""
    private var isConfigured = false
    private var deferredStop = false
    private let audioSendCounter = DictationAudioSendCounter()

    // MARK: - Lifecycle

    init() {
        let defaults = UserDefaults.standard
        self.hotkeyChoice = defaults.string(forKey: Self.hotkeyDefaultsKey) ?? DictationHotkey.defaultPushToTalk.rawValue
        self.handsFreeHotkeyChoice = defaults.string(forKey: Self.handsFreeHotkeyDefaultsKey) ?? ""
        // Dictation STT providers already return polished text in the common
        // case. Keep AI cleanup opt-in so dictation stays fast and predictable.
        if defaults.object(forKey: Self.aiCleanupDefaultsKey) == nil {
            self.aiCleanupEnabled = false
        } else {
            self.aiCleanupEnabled = defaults.bool(forKey: Self.aiCleanupDefaultsKey)
        }
        // Same idiom: default ON for fresh installs so the onboarding sandbox
        // (build 74+) can actually fire the hotkey, and so first-launch users
        // get the marquee feature without hunting through Settings. An
        // explicitly-stored `false` (user toggled it off in Settings) stays
        // `false`.
        if defaults.object(forKey: Self.enabledDefaultsKey) == nil {
            self.isFeatureEnabled = true
        } else {
            self.isFeatureEnabled = defaults.bool(forKey: Self.enabledDefaultsKey)
        }
        setupHotkeyCallbacks()
    }

    /// Called when user authenticates and provides the API client used to mint realtime STT sessions.
    func configure(
        apiClient: APIClient,
        canStart: @escaping () -> Bool,
        canStartReason: @escaping () -> String = { "external_gate" }
    ) {
        self.apiClient = apiClient
        self.sessionConfigVault = RealtimeTranscriptionSessionConfigVault { key in
            try await apiClient.createRealtimeTranscriptionSession(
                language: key.language,
                channels: key.channels,
                purpose: key.purpose
            )
        }
        self.canStartDictation = canStart
        self.canStartDictationReason = canStartReason
        isConfigured = true
        applyHotkeyAvailability()
        refreshSettingsAndPrefetch(apiClient: apiClient, reason: "configure")
        log.info("Dictation manager configured")
    }

    /// Called when user logs out
    func disable() {
        isConfigured = false
        canStartDictation = nil
        canStartDictationReason = nil
        applyHotkeyAvailability()
        Task { await cancelDictation() }
        apiClient = nil
        let vault = sessionConfigVault
        sessionConfigVault = nil
        Task { await vault?.clear() }
        cachedSettings = nil
        cachedSettingsLoadedAt = nil
        log.info("Dictation manager disabled")
    }

    func ingestSettings(_ settings: UserSettings) {
        let previousProvider = cachedSettings?.dictationLiveSTTProvider
        let previousModel = cachedSettings?.dictationLiveSTTModel
        cachedSettings = settings
        cachedSettingsLoadedAt = Date()
        aiCleanupEnabled = settings.dictationPostFilterEnabled
        if previousProvider != settings.dictationLiveSTTProvider
            || previousModel != settings.dictationLiveSTTModel {
            let vault = sessionConfigVault
            Task { await vault?.clear() }
        }
        prefetchDictationSessionConfig(reason: "settings_ingested")
    }

    func updateEnabled(_ enabled: Bool) {
        isFeatureEnabled = enabled
    }

    /// Update push-to-talk hotkey from settings
    func updateHotkey(_ hotkey: DictationHotkey) {
        hotkeyChoice = hotkey.rawValue
        hotkeyManager.hotkey = hotkey
        refreshPermissionState()
        log.info("Push-to-talk hotkey updated to \(hotkey.label)")
    }

    /// Update hands-free hotkey from settings. Pass `nil` to fall back to the
    /// legacy double-tap of the push-to-talk key.
    func updateHandsFreeHotkey(_ hotkey: DictationHotkey?) {
        handsFreeHotkeyChoice = hotkey?.rawValue ?? ""
        hotkeyManager.handsFreeHotkey = hotkey
        refreshPermissionState()
    }

    private func setHandsFree(_ active: Bool) {
        isHandsFree = active
        hotkeyManager.isHandsFreeModeActive = active
    }

    func refreshPermissionState() {
        hotkeyManager.refreshAfterPermissionChange()
        applyHotkeyAvailability()
    }

    func clearError() {
        error = nil
    }

    // MARK: - Hotkey Callbacks

    private func setupHotkeyCallbacks() {
        hotkeyManager.onPushToTalkStart = { [weak self] in
            guard let self else { return }
            guard self.isEnabled else {
                log.warning("Dictation hotkey pressed but not enabled (not authenticated?)")
                SentryHelper.addBreadcrumb(
                    category: "dictation.session",
                    message: "hotkey start ignored",
                    level: .warning,
                    data: ["reason": "disabled"]
                )
                return
            }
            guard self.canBeginExternalDictation() else { return }
            guard self.state == .idle else {
                SentryHelper.addBreadcrumb(
                    category: "dictation.session",
                    message: "hotkey start ignored",
                    level: .warning,
                    data: ["reason": "busy", "state": String(describing: self.state)]
                )
                SentryHelper.captureErrorOnce(
                    DictationInstrumentationError.unknown("hotkey start ignored while busy"),
                    fingerprint: "dictation.hotkey_start_ignored.\(String(describing: self.state))",
                    extras: [
                        "stage": "hotkey.start",
                        "state": String(describing: self.state),
                    ]
                )
                return
            }
            self.setHandsFree(false)
            Task { await self.startDictation() }
        }

        hotkeyManager.onPushToTalkStop = { [weak self] in
            guard let self else { return }
            guard !self.isHandsFree else { return } // Don't stop if in hands-free mode
            if self.state == .connecting {
                self.deferredStop = true
                SentryHelper.addBreadcrumb(
                    category: "dictation.session",
                    message: "stop deferred until provider ready",
                    data: ["state": String(describing: self.state)]
                )
            } else if self.state == .listening {
                Task { await self.stopAndInsert() }
            }
        }

        hotkeyManager.onHandsFreeToggle = { [weak self] in
            guard let self else { return }
            guard self.isEnabled else { return }

            if self.state == .listening && self.isHandsFree {
                // Currently in hands-free — stop
                Task { await self.stopAndInsert() }
            } else if self.state == .idle, self.canBeginExternalDictation() {
                // Start hands-free
                self.setHandsFree(true)
                Task { await self.startDictation() }
            }
        }

        hotkeyManager.onSingleTap = {
            // Idle single taps are intentionally ignored. Active hands-free
            // stop is handled on key press inside GlobalHotkeyManager so a
            // slightly long tap cannot become push-to-talk.
        }

        hotkeyManager.onCancelled = { [weak self] in
            guard let self, self.state != .idle else { return }
            Task { await self.cancelDictation() }
        }
    }

    // MARK: - Dictation Flow

    func startDictation() async {
        guard state == .idle else {
            log.warning("Cannot start dictation — state is \(String(describing: self.state))")
            SentryHelper.addBreadcrumb(
                category: "dictation.session",
                message: "start ignored",
                level: .warning,
                data: ["state": String(describing: state)]
            )
            SentryHelper.captureErrorOnce(
                DictationInstrumentationError.unknown("start called while busy"),
                fingerprint: "dictation.start_ignored.\(String(describing: state))",
                extras: [
                    "stage": "start.guard",
                    "state": String(describing: state),
                ]
            )
            return
        }

        guard let apiClient else {
            error = "Not authenticated. Please log in first."
            return
        }
        guard canBeginExternalDictation() else { return }

        SentryHelper.addBreadcrumb(
            category: "dictation.session",
            message: "starting dictation",
            data: ["isHandsFree": isHandsFree]
        )

        // Begin instrumentation as the very first step so every subsequent
        // event is attributed to this session and timed from the hotkey-down
        // moment. `instrumentationSession` lives until cleanup() / cancel().
        let session = DictationInstrumentation.shared.startSession()
        instrumentationSession = session

        // Remember the target app so we can re-focus it before pasting
        targetApp = NSWorkspace.shared.frontmostApplication

        // Check microphone permission — use the canonical macOS API.
        // `AVAudioApplication.requestRecordPermission` silently fails on
        // macOS 26 (Tahoe), which used to leave dictation in a permanently
        // failed state without prompting the user.
        let micGranted: Bool
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            micGranted = true
        case .notDetermined:
            micGranted = await AVCaptureDevice.requestAccess(for: .audio)
        case .denied, .restricted:
            micGranted = false
        @unknown default:
            micGranted = false
        }
        guard micGranted else {
            error = DictationCopy.microphonePermissionDenied(language: LanguageManager.shared.current)
            session.failure(
                DictationInstrumentationError.microphoneDenied,
                extras: ["stage": "permission"]
            )
            instrumentationSession = nil
            return
        }

        error = nil
        committedTexts = []
        currentInterim = ""
        interimTranscript = ""
        dictationDuration = 0
        deferredStop = false
        audioSendCounter.reset()
        setState(.connecting)
        session.event(.providerConnecting, data: ["isHandsFree": isHandsFree])

        // Show overlay
        showOverlay()

        // Play start sound (subtle, non-alarming)
        NSSound(named: NSSound.Name("Morse"))?.play()

        do {
            let settings = try await currentSettings(apiClient: apiClient)
            SentryHelper.addBreadcrumb(
                category: "dictation.session",
                message: "dictation provider selected",
                data: [
                    "provider": settings.dictationLiveSTTProvider,
                    "model": settings.dictationLiveSTTModel,
                ]
            )

            let language = currentDictationLanguage()
            let sessionConfig = try await takeDictationSessionConfig(
                settings: settings,
                language: language,
                session: session,
                apiClient: apiClient
            )

            if sessionConfig.provider == "openai" {
                await startOpenAIDictation(apiClient: apiClient, session: session, sessionConfig: sessionConfig)
                return
            }

            if sessionConfig.provider == "elevenlabs" {
                await startElevenLabsDictation(apiClient: apiClient, session: session, sessionConfig: sessionConfig)
                return
            }

            let keyTerms = dictionaryStore?.vocabularyList ?? []
            let provider = ProviderBackedRealtimeSession(
                config: sessionConfig,
                keyTerms: keyTerms
            )
            providerSession = provider
            session.event(.providerConnecting, data: [
                "provider": sessionConfig.provider,
                "model": sessionConfig.model,
                "language": sessionConfig.language,
                "key_terms_count": keyTerms.count,
            ])
            let stream = provider.events
            sessionEventTask = Task { [weak self] in
                guard let self else { return }
                for await event in stream {
                    await self.handleProviderEvent(event)
                }
            }

            let capture = makeCapture(sampleRate: sessionConfig.sampleRate)
            providerCapture = capture
            try await capture.startRecording()

            let encoder = RealtimePCMEncoder(targetSampleRate: sessionConfig.sampleRate, channels: 1)
            try await provider.open()
            session.event(.providerOpened)

            let audioCounter = audioSendCounter
            providerAudioTask = Task.detached(priority: .userInitiated) { [weak provider, weak capture] in
                guard let provider, let capture else { return }
                var liveSent = 0
                for await buffer in capture.audioBuffers {
                    guard !Task.isCancelled else { return }
                    guard let data = encoder.encode(buffer) else { continue }
                    do {
                        try await provider.send(pcm16: data)
                        liveSent += 1
                        audioCounter.record(bytes: data.count)
                        if liveSent <= 3 || liveSent % 20 == 0 {
                            NSLog("[Dictation/Provider] sent #%d %d bytes provider=%@", liveSent, data.count, sessionConfig.provider)
                        }
                    } catch {
                        NSLog("[Dictation/Provider] send #%d failed provider=%@: %@", liveSent, sessionConfig.provider, String(describing: error))
                        return
                    }
                }
                NSLog("[Dictation/Provider] audio stream ended provider=%@ sent=%d", sessionConfig.provider, liveSent)
            }

            startTimer()
            setState(.listening)
            session.event(.audioFirstChunkSent)

            // Hotkey released during connect — apply now.
            if consumeDeferredStopAction() == .finishAfterReady {
                await stopAndInsert()
            }
        } catch {
            log.error("Failed to start dictation")
            self.error = error.userFacingMessage(context: .dictation)
            instrumentationSession?.failure(error, extras: ["stage": "start"])
            instrumentationSession = nil
            await resetAfterStartFailure()
        }
    }

    func stopAndInsert() async {
        guard state == .listening else {
            SentryHelper.addBreadcrumb(
                category: "dictation.session",
                message: "stop ignored",
                level: .warning,
                data: ["state": String(describing: state)]
            )
            SentryHelper.captureErrorOnce(
                DictationInstrumentationError.unknown("stop called while not listening"),
                fingerprint: "dictation.stop_ignored.\(String(describing: state))",
                extras: [
                    "stage": "stop.guard",
                    "state": String(describing: state),
                ]
            )
            return
        }
        setState(.processing)
        instrumentationSession?.event(.finalizingStarted, data: ["durationMs": Int(dictationDuration * 1000)])

        // Drain the active provider: direct provider session, OpenAI, or
        // ElevenLabs via WebSocketManager.
        await finishProviderAudioPumpBeforeFinalizing()
        let providerSegments = (try? await providerSession?.close(timeout: .seconds(4))) ?? []
        await finishOpenAIAudioPumpBeforeFinalizing()
        let openAIOutcome = try? await openAISession?.close(timeout: .seconds(4))
        if let ws = elevenLabsWebSocket {
            await finishElevenLabsAudioPumpBeforeFinalizing()
            _ = try? await ws.finishStreaming(timeout: .seconds(4))
        }

        // If cancelDictation ran during finalization, bail out cleanly.
        guard state == .processing else { return }

        sessionEventTask?.cancel()
        sessionEventTask = nil
        elevenLabsEventTask?.cancel()
        elevenLabsEventTask = nil
        timerTask?.cancel()
        timerTask = nil

        let openAITranscript = openAIOutcome?
            .map(\.text)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let providerTranscript = providerSegments
            .map(\.text)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let liveTranscript = buildTranscript()
        let trimmedText = RealtimeTranscriptCandidateSelector.select([
            providerTranscript.isEmpty ? nil : providerTranscript,
            openAITranscript,
            liveTranscript,
        ])
        let audioSnapshot = audioSendCounter.snapshot()
        instrumentationSession?.event(.transcriptFinalized, data: [
            "durationMs": Int(dictationDuration * 1000),
            "audioChunksSent": audioSnapshot.chunks,
            "audioBytesSent": audioSnapshot.bytes,
            "providerSegmentCount": providerSegments.count,
            "providerChars": providerTranscript.count,
            "openAIChars": openAITranscript?.count ?? 0,
            "liveChars": liveTranscript.count,
            "selectedChars": trimmedText.count,
        ])

        guard !trimmedText.isEmpty else {
            log.info("No text transcribed — nothing to insert")
            if dictationDuration >= 1.0 {
                instrumentationSession?.failure(
                    DictationInstrumentationError.unknown("no transcript after finalization"),
                    extras: [
                        "stage": "finalize",
                        "durationMs": Int(dictationDuration * 1000),
                        "audioChunksSent": audioSnapshot.chunks,
                        "audioBytesSent": audioSnapshot.bytes,
                        "providerSegmentCount": providerSegments.count,
                    ]
                )
                instrumentationSession = nil
            }
            await cleanup()
            return
        }

        log.info("Transcribed \(trimmedText.count) characters")

        // Apply dictionary replacements
        var textToInsert = dictionaryStore?.applyReplacements(to: trimmedText) ?? trimmedText

        // AI cleanup (optional)
        let rawText = textToInsert
        if aiCleanupEnabled, let apiClient {
            do {
                // Pass the dictionary's vocabulary list so the cleanup pass
                // preserves user-curated spellings exactly (proper nouns,
                // jargon, custom terminology that the LLM might otherwise
                // "correct" away).
                let vocabulary = dictionaryStore?.vocabularyList ?? []
                let cleaned = try await apiClient.cleanupDictation(
                    text: trimmedText,
                    vocabulary: vocabulary
                )
                textToInsert = cleaned
                log.info("AI cleanup: \(trimmedText.count) → \(cleaned.count) chars (vocab=\(vocabulary.count))")
            } catch {
                log.warning("AI cleanup failed, using raw transcript")
                if let apiError = error as? APIError, case .unauthorized = apiError {
                    self.error = apiError.userFacingMessage(context: .dictation)
                }
                // Continue with raw text
            }
        }

        // Publish the final text so observers (onboarding sandbox, future
        // analytics surfaces) receive it independent of TextInserter success.
        // Re-set on every dictation so SwiftUI .onChange fires even when the
        // text is identical to the previous one (we'd want to also use a
        // monotonic counter if we needed strict identity, but for the current
        // sandbox use case the text-change trigger is enough).
        lastFinalTranscript = textToInsert

        // Insert text into target app
        setState(.inserting)
        do {
            try await TextInserter.insert(textToInsert, targetApp: targetApp)
            NSSound(named: NSSound.Name("Pop"))?.play()
        } catch {
            let recoveryURL = try? saveRecoveryText(textToInsert)
            SentryHelper.captureError(
                error,
                extras: [
                    "action": "dictationInsert",
                    "hasRecoveryCopy": recoveryURL != nil,
                ]
            )
            if recoveryURL != nil, let insertionError = error as? TextInsertionError {
                self.error = DictationCopy.recoveryCopyKept(
                    insertionError: insertionError.localizedDescription,
                    language: LanguageManager.shared.current
                )
            } else if recoveryURL != nil {
                self.error = DictationCopy.genericInsertionRecovery(
                    language: LanguageManager.shared.current
                )
            } else {
                self.error = error.userFacingMessage(context: .dictation)
            }
        }

        // Save to history
        historyStore?.add(
            rawText: rawText,
            cleanedText: textToInsert != rawText ? textToInsert : nil,
            durationSeconds: dictationDuration
        )

        await cleanup()
    }

    func cancelDictation() async {
        guard state != .idle else { return }
        log.info("Dictation cancelled")
        if let session = instrumentationSession {
            session.cancel(reason: "user_or_system")
            instrumentationSession = nil
        }

        providerAudioTask?.cancel()
        await providerSession?.cancel()
        await openAISession?.cancel()
        if let ws = elevenLabsWebSocket {
            elevenLabsAudioTask?.cancel()
            await ws.disconnect()
        }
        sessionEventTask?.cancel()
        sessionEventTask = nil
        elevenLabsEventTask?.cancel()
        elevenLabsEventTask = nil
        timerTask?.cancel()
        timerTask = nil

        await cleanup()
    }

    private func finishProviderAudioPumpBeforeFinalizing() async {
        if let capture = providerCapture {
            await waitForFinalCaptureTail()
            await capture.stopRecording()
            providerCapture = nil
        }
        await providerAudioTask?.value
        providerAudioTask = nil
    }

    private func finishOpenAIAudioPumpBeforeFinalizing() async {
        if let capture = openAICapture {
            await waitForFinalCaptureTail()
            await capture.stopRecording()
            openAICapture = nil
        }
        await openAIAudioTask?.value
        openAIAudioTask = nil
    }

    private func finishElevenLabsAudioPumpBeforeFinalizing() async {
        if let capture = elevenLabsCapture {
            await waitForFinalCaptureTail()
            await capture.stopRecording()
            elevenLabsCapture = nil
        }
        await elevenLabsAudioTask?.value
        elevenLabsAudioTask = nil
    }

    private func waitForFinalCaptureTail() async {
        guard !Task.isCancelled else { return }
        try? await Task.sleep(for: DictationFinalizationPolicy.captureTailDelay)
    }

    // MARK: - ElevenLabs rollback path

    private func currentDictationLanguage() -> String {
        if let store = languageStore {
            let tag = store.wireLanguageTag
            return tag.isEmpty ? "multi" : tag
        }
        return UserDefaults.standard.string(forKey: "transcriptionLanguage") ?? "multi"
    }

    private func makeCapture(sampleRate: Int) -> MicrophoneCapture {
        MicrophoneCapture(
            config: AudioCaptureConfig(
                sampleRate: Double(sampleRate),
                channelCount: 1,
                bufferSize: UInt32(max(sampleRate / 10, 1))
            )
        )
    }

    private func dictationSessionConfigKey(language: String? = nil) -> RealtimeTranscriptionSessionConfigVault.Key {
        RealtimeTranscriptionSessionConfigVault.Key(
            language: language ?? currentDictationLanguage(),
            channels: 1,
            purpose: .dictation
        )
    }

    private func prefetchDictationSessionConfig(reason: String) {
        guard isConfigured, isFeatureEnabled, state == .idle, let sessionConfigVault else { return }
        let key = dictationSessionConfigKey()
        Task { await sessionConfigVault.prefetch(for: key) }
        SentryHelper.addBreadcrumb(
            category: "dictation.session",
            message: "realtime config prefetch scheduled",
            data: [
                "reason": reason,
                "language": key.language,
            ]
        )
    }

    private func refreshSettingsAndPrefetch(apiClient: APIClient, reason: String) {
        Task { [weak self] in
            do {
                let settings = try await apiClient.getSettings()
                await MainActor.run {
                    self?.ingestSettings(settings)
                }
            } catch {
                SentryHelper.captureError(error, extras: ["action": "dictationSettingsPrefetch", "reason": reason])
            }
        }
    }

    private func currentSettings(apiClient: APIClient) async throws -> UserSettings {
        if let cachedSettings,
           let cachedSettingsLoadedAt,
           Date().timeIntervalSince(cachedSettingsLoadedAt) < settingsCacheTTL {
            SentryHelper.addBreadcrumb(
                category: "dictation.session",
                message: "settings cache hit",
                data: [
                    "provider": cachedSettings.dictationLiveSTTProvider,
                    "model": cachedSettings.dictationLiveSTTModel,
                ]
            )
            return cachedSettings
        }

        let settings = try await apiClient.getSettings()
        ingestSettings(settings)
        return settings
    }

    private func takeDictationSessionConfig(
        settings: UserSettings,
        language: String,
        session: DictationInstrumentation.Session,
        apiClient: APIClient
    ) async throws -> RealtimeTranscriptionSessionConfig {
        let key = dictationSessionConfigKey(language: language)
        let result: RealtimeTranscriptionSessionConfigVault.TakeResult
        if let sessionConfigVault {
            result = try await sessionConfigVault.take(
                for: key,
                expectedProvider: settings.dictationLiveSTTProvider,
                expectedModel: settings.dictationLiveSTTModel
            )
        } else {
            let config = try await apiClient.createRealtimeTranscriptionSession(
                language: key.language,
                channels: key.channels,
                purpose: key.purpose
            )
            result = RealtimeTranscriptionSessionConfigVault.TakeResult(
                config: config,
                prefetched: false,
                tokenAgeMilliseconds: 0
            )
        }

        session.event(.tokenMinted, data: [
            "provider": result.config.provider,
            "model": result.config.model,
            "prefetchHit": result.prefetched,
            "tokenAgeMs": result.tokenAgeMilliseconds,
        ])
        return result.config
    }

    private func startOpenAIDictation(
        apiClient: APIClient,
        session: DictationInstrumentation.Session,
        sessionConfig: RealtimeTranscriptionSessionConfig
    ) async {
        do {
            guard let urlString = sessionConfig.websocketURL,
                  let url = URL(string: urlString) else {
                throw DictationInstrumentationError.unknown("missing OpenAI websocket URL in session config")
            }

            let provider = OpenAIRealtimeTranscriptionSession(
                websocketURL: url,
                bearerToken: sessionConfig.token,
                model: sessionConfig.model,
                language: sessionConfig.language,
                sampleRate: sessionConfig.sampleRate
            )
            openAISession = provider
            let stream = provider.events
            sessionEventTask = Task { [weak self] in
                guard let self else { return }
                for await event in stream {
                    await self.handleProviderEvent(event)
                }
            }

            session.event(.providerConnecting, data: [
                "provider": "openai",
                "model": sessionConfig.model,
                "language": sessionConfig.language,
            ])

            let capture = makeCapture(sampleRate: sessionConfig.sampleRate)
            openAICapture = capture
            try await capture.startRecording()

            let encoder = RealtimePCMEncoder(targetSampleRate: sessionConfig.sampleRate, channels: 1)
            try await provider.open()

            let audioCounter = audioSendCounter
            openAIAudioTask = Task.detached(priority: .userInitiated) { [weak provider, weak capture] in
                guard let provider, let capture else { return }
                var liveSent = 0
                for await buffer in capture.audioBuffers {
                    guard !Task.isCancelled else { return }
                    guard let data = encoder.encode(buffer) else { continue }
                    do {
                        try await provider.send(pcm16: data)
                        liveSent += 1
                        audioCounter.record(bytes: data.count)
                    } catch {
                        NSLog("[Dictation/OpenAI] send #%d failed: %@", liveSent, String(describing: error))
                        return
                    }
                }
            }

            startTimer()
            setState(.listening)
            session.event(.audioFirstChunkSent)

            if consumeDeferredStopAction() == .finishAfterReady {
                await stopAndInsert()
            }
        } catch {
            log.error("Failed to start OpenAI dictation")
            self.error = error.userFacingMessage(context: .dictation)
            instrumentationSession?.failure(error, extras: ["stage": "start.openai"])
            instrumentationSession = nil
            await resetAfterStartFailure()
        }
    }

    private func startElevenLabsDictation(
        apiClient: APIClient,
        session: DictationInstrumentation.Session,
        sessionConfig: RealtimeTranscriptionSessionConfig
    ) async {
        do {
            // Read from the multi-select language store. wireLanguageTag returns
            // "" for auto-detect (0 or 2+ selections) and the BCP-47 code for
            // a single-language selection.
            let language = sessionConfig.language

            // 1. WebSocketManager.connect(using:) receives the already-minted
            //    config so the hotkey path does not pay a second backend
            //    round-trip. The config contains only a temporary credential;
            //    no provider socket is opened until connect() below.
            //    Per-session keyterms come from the user's dictation
            //    dictionary — every entry biases the recognizer toward
            //    that spelling. Cap is enforced inside WebSocketManager.
            let keyTerms = dictionaryStore?.vocabularyList ?? []
            let ws = WebSocketManager(
                apiClient: apiClient,
                language: language,
                channels: 1,
                purpose: .dictation,
                keyTerms: keyTerms
            )
            elevenLabsWebSocket = ws
            session.event(.providerConnecting, data: [
                "provider": "elevenlabs",
                "key_terms_count": keyTerms.count,
            ])

            let stream = await ws.events
            elevenLabsEventTask = Task { [weak self] in
                guard let self else { return }
                for await event in stream {
                    await self.handleElevenLabsEvent(event)
                }
            }

            // 2. Audio pump — encode each MicrophoneCapture buffer and forward
            //    to ws.sendAudio after the provider socket is open.
            let capture = makeCapture(sampleRate: sessionConfig.sampleRate)
            elevenLabsCapture = capture
            try await capture.startRecording()

            let encoder = RealtimePCMEncoder(targetSampleRate: sessionConfig.sampleRate, channels: 1)
            try await ws.connect(using: sessionConfig)
            session.event(.providerOpened)

            NSLog("[Dictation/EL] audio task starting (MicrophoneCapture)")
            let audioCounter = audioSendCounter
            elevenLabsAudioTask = Task.detached(priority: .userInitiated) { [weak ws, weak capture] in
                guard let ws, let capture else {
                    NSLog("[Dictation/EL] audio task exit — ws or capture nil")
                    return
                }
                var liveSent = 0
                for await buffer in capture.audioBuffers {
                    if Task.isCancelled {
                        NSLog("[Dictation/EL] audio task cancelled (sent=%d)", liveSent)
                        return
                    }
                    guard let data = encoder.encode(buffer) else {
                        NSLog("[Dictation/EL] encode returned nil (frames=%d)", Int(buffer.frameLength))
                        continue
                    }
                    do {
                        try await ws.sendAudio(data: data)
                        liveSent += 1
                        audioCounter.record(bytes: data.count)
                        if liveSent <= 3 || liveSent % 20 == 0 {
                            NSLog("[Dictation/EL] sent #%d %d bytes", liveSent, data.count)
                        }
                    } catch {
                        NSLog("[Dictation/EL] send #%d failed: %@", liveSent, String(describing: error))
                        return
                    }
                }
                NSLog("[Dictation/EL] audio stream ended (sent=%d)", liveSent)
            }

            startTimer()
            setState(.listening)
            session.event(.audioFirstChunkSent)

            // Hotkey released during connect — apply now.
            if consumeDeferredStopAction() == .finishAfterReady {
                await stopAndInsert()
            }
        } catch {
            log.error("Failed to start ElevenLabs dictation")
            self.error = error.userFacingMessage(context: .dictation)
            instrumentationSession?.failure(error, extras: ["stage": "start.elevenlabs"])
            instrumentationSession = nil
            await resetAfterStartFailure()
        }
    }

    private func handleElevenLabsEvent(_ event: WebSocketEvent) async {
        switch event {
        case .connected:
            NSLog("[Dictation/EL] WebSocket connected event")
        case .reconnected:
            NSLog("[Dictation/EL] WebSocket RECONNECTED event")
        case .reconnecting(let attempt, let max):
            NSLog("[Dictation/EL] WebSocket reconnecting %d/%d", attempt, max)
        case .transcript(let segment):
            NSLog("[Dictation/EL] transcript isFinal=%d chars=%d", segment.isFinal ? 1 : 0, segment.text.count)
            if !firstTokenReported {
                firstTokenReported = true
                instrumentationSession?.event(.firstTokenReceived, data: ["isFinal": segment.isFinal])
            }
            if segment.isFinal {
                instrumentationSession?.event(.committedTranscript, data: ["chars": segment.text.count])
                committedTexts.append(segment.text)
                currentInterim = ""
            } else {
                currentInterim = segment.text
            }
            interimTranscript = buildTranscript()
        case .disconnected(let err):
            NSLog("[Dictation/EL] WebSocket DISCONNECTED err=%@", err.map { String(describing: $0) } ?? "clean")
            instrumentationSession?.event(.providerClosed, data: [
                "reason": err.map { String(describing: $0) } ?? "clean",
            ])
            if state == .listening {
                let closeError = NSError(
                    domain: "is.waiwai.computer.dictation",
                    code: 1002,
                    userInfo: [NSLocalizedDescriptionKey: "ElevenLabs WebSocket closed: \(err?.localizedDescription ?? "clean")"]
                )
                SentryHelper.captureError(
                    closeError,
                    extras: [
                        "context": "dictation.elevenlabs.disconnected",
                        "isHandsFree": isHandsFree,
                    ]
                )
                self.error = "Connection to the transcription service was lost. Try again."
                await cancelDictation()
            }
        case .reconnectionFailed(let err):
            log.warning("ElevenLabs reconnection failed: \(err?.localizedDescription ?? "unknown", privacy: .public)")
        }
    }

    // MARK: - Private

    private func setState(_ newState: State) {
        withAnimation(.easeInOut(duration: 0.15)) {
            state = newState
        }
    }

    private func consumeDeferredStopAction() -> DeferredDictationStopPolicy.Action {
        let action = DeferredDictationStopPolicy.action(
            deferredStop: deferredStop,
            isHandsFree: isHandsFree
        )
        if action == .finishAfterReady {
            deferredStop = false
            SentryHelper.addBreadcrumb(
                category: "dictation.session",
                message: "deferred stop applied",
                data: ["state": String(describing: state)]
            )
        }
        return action
    }

    private func cleanup() async {
        sessionEventTask?.cancel()
        sessionEventTask = nil
        timerTask?.cancel()
        timerTask = nil

        let activeProviderSession = providerSession
        providerSession = nil
        providerAudioTask?.cancel()
        providerAudioTask = nil
        await activeProviderSession?.cancel()
        if let capture = providerCapture {
            await capture.stopRecording()
            providerCapture = nil
        }

        let activeOpenAISession = openAISession
        openAISession = nil
        await activeOpenAISession?.cancel()
        deferredStop = false
        firstTokenReported = false

        openAIAudioTask?.cancel()
        openAIAudioTask = nil
        if let capture = openAICapture {
            await capture.stopRecording()
            openAICapture = nil
        }

        // Tear down ElevenLabs path resources (no-op if not in use).
        elevenLabsAudioTask?.cancel()
        elevenLabsAudioTask = nil
        elevenLabsEventTask?.cancel()
        elevenLabsEventTask = nil
        if let capture = elevenLabsCapture {
            await capture.stopRecording()
            elevenLabsCapture = nil
        }
        elevenLabsWebSocket = nil

        targetApp = nil
        setState(.idle)
        setHandsFree(false)
        hideOverlay()

        // Treat reaching idle without a prior failure() / cancel() as success.
        // Failure paths nil out the session above to avoid double-counting.
        if let session = instrumentationSession {
            session.succeed()
            instrumentationSession = nil
        }

        prefetchDictationSessionConfig(reason: "idle_after_session")
    }

    private func resetAfterStartFailure() async {
        await cleanup()
    }

    private func startTimer() {
        timerTask?.cancel()
        timerTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { break }
                await MainActor.run {
                    self?.dictationDuration += 1
                }
            }
        }
    }

    // MARK: - Provider Events (Inworld)

    /// Track whether the first transcript token has arrived this session so
    /// we can emit a `firstTokenReceived` instrumentation event at the
    /// correct moment (used for `arm → first_token` latency in Sentry).
    private var firstTokenReported = false

    private func handleProviderEvent(_ event: TranscriptionEvent) async {
        switch event {
        case .opened:
            instrumentationSession?.event(.providerOpened)
        case .interim(let text, _):
            if !firstTokenReported {
                firstTokenReported = true
                instrumentationSession?.event(.firstTokenReceived, data: ["isFinal": false])
            }
            currentInterim = text
            interimTranscript = buildTranscript()
        case .committed(let segment):
            if !firstTokenReported {
                firstTokenReported = true
                instrumentationSession?.event(.firstTokenReceived, data: ["isFinal": true])
            }
            instrumentationSession?.event(.committedTranscript, data: ["chars": segment.text.count])
            committedTexts.append(segment.text)
            currentInterim = ""
            interimTranscript = buildTranscript()
        case .voiceProfile:
            break
        case .providerWarning(let providerError):
            instrumentationSession?.event(.providerWarning, data: [
                "fingerprint": providerError.fingerprint
            ])
            // In hands-free mode the user is explicitly waiting — pauses are
            // expected, transient hiccups are recoverable. Only hard-fail for
            // errors that genuinely cannot be retried within the same
            // session: bad token, hit billing wall, model misconfigured,
            // or the per-session time limit was reached. Everything else
            // (insufficientAudioActivity, rateLimited, chunkSizeExceeded,
            // commitThrottled, malformedFrame, transcriberInternal — most
            // notably the `default` mapping for unknown Inworld codes) is
            // surfaced as a hint but the overlay stays open and the audio
            // pump keeps trying. PTT still fails-fast across the board
            // because the user is actively holding the key and a frozen
            // overlay would be confusing.
            if state == .listening {
                if isHandsFree {
                    let isUnrecoverable: Bool
                    switch providerError {
                    case .authError, .quotaExceeded, .unsupportedModel, .sessionTimeLimitExceeded:
                        isUnrecoverable = true
                    default:
                        isUnrecoverable = false
                    }
                    if !isUnrecoverable {
                        self.error = userFacingMessage(for: providerError)
                        log.info("Hands-free: provider warning '\(providerError.fingerprint, privacy: .public)' surfaced, session kept alive")
                        // Surface to Sentry — without this, the only signal
                        // is a breadcrumb that's never transmitted (Sentry
                        // only sends breadcrumbs when an exception is captured).
                        SentryHelper.captureError(
                            providerError,
                            extras: [
                                "context": "dictation.providerWarning.recovered",
                                "fingerprint": providerError.fingerprint,
                                "isHandsFree": true,
                            ]
                        )
                        return
                    }
                }
                self.error = userFacingMessage(for: providerError)
                log.info("Cancelling dictation — provider warning fingerprint=\(providerError.fingerprint, privacy: .public)")
                // Capture to Sentry — providerWarning previously only added a
                // breadcrumb that Sentry never transmits without a parent
                // exception. This call makes the issue visible in production.
                SentryHelper.captureError(
                    providerError,
                    extras: [
                        "context": "dictation.providerWarning.fatal",
                        "fingerprint": providerError.fingerprint,
                        "isHandsFree": isHandsFree,
                        "userFacing": userFacingMessage(for: providerError),
                    ]
                )
                await cancelDictation()
            }
        case .closed(let reason):
            instrumentationSession?.event(.providerClosed, data: [
                "reason": String(describing: reason)
            ])
            // Both serverError and networkLost mean the WebSocket is dead —
            // no point keeping the overlay up while the audio pump fails
            // every send. clientRequested is OUR own close call so we don't
            // act on it (cleanup() is already running).
            if state == .listening {
                switch reason {
                case .serverError, .networkLost, .serverEndOfStream, .sessionTimeLimitExceeded:
                    self.error = "Connection to the transcription service was lost. Try again."
                    log.info("Cancelling dictation — provider closed reason=\(String(describing: reason), privacy: .public)")
                    let closeError = NSError(
                        domain: "is.waiwai.computer.dictation",
                        code: 1001,
                        userInfo: [NSLocalizedDescriptionKey: "Provider closed unexpectedly: \(reason)"]
                    )
                    SentryHelper.captureError(
                        closeError,
                        extras: [
                            "context": "dictation.provider.closed",
                            "reason": String(describing: reason),
                            "isHandsFree": isHandsFree,
                        ]
                    )
                    await cancelDictation()
                case .clientRequested:
                    break
                }
            }
        case .usage(let seconds):
            instrumentationSession?.event(.providerClosed, data: [
                "promptedSeconds": seconds
            ])
        }
    }

    private func userFacingMessage(for error: ProviderError) -> String {
        DictationCopy.providerError(error, language: LanguageManager.shared.current)
    }

    private func buildTranscript() -> String {
        let committed = committedTexts.joined(separator: " ")
        if currentInterim.isEmpty {
            return committed
        } else if committed.isEmpty {
            return currentInterim
        } else {
            return committed + " " + currentInterim
        }
    }

    private func canBeginExternalDictation() -> Bool {
        guard let canStartDictation else {
            SentryHelper.addBreadcrumb(
                category: "dictation.session",
                message: "external dictation denied",
                level: .warning,
                data: ["reason": "not_configured"]
            )
            return false
        }
        guard canStartDictation() else {
            let reason = canStartDictationReason?() ?? "external_gate"
            SentryHelper.addBreadcrumb(
                category: "dictation.session",
                message: "external dictation denied",
                level: .warning,
                data: ["reason": reason]
            )
            SentryHelper.captureErrorOnce(
                DictationInstrumentationError.unknown("external dictation gate denied"),
                fingerprint: "dictation.external_gate_denied.\(reason)",
                extras: [
                    "stage": "hotkey.external_gate",
                    "reason": reason,
                    "state": String(describing: state),
                ]
            )
            return false
        }
        return true
    }

    private func applyHotkeyAvailability() {
        hotkeyManager.hotkey = selectedHotkey
        hotkeyManager.handsFreeHotkey = selectedHandsFreeHotkey
        let shouldEnable = isConfigured && isFeatureEnabled
        isEnabled = shouldEnable
        if shouldEnable {
            hotkeyManager.start()
        } else {
            hotkeyManager.stop()
        }
    }

    private func saveRecoveryText(_ text: String) throws -> URL? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let base = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = base
            .appendingPathComponent("WaiComputer", isDirectory: true)
            .appendingPathComponent("DictationRecovery", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        let fileName = "dictation-\(formatter.string(from: Date()).replacingOccurrences(of: ":", with: "-"))-\(UUID().uuidString.prefix(8)).txt"
        let url = directory.appendingPathComponent(fileName)
        try trimmed.write(to: url, atomically: true, encoding: .utf8)
        return url
    }

    // MARK: - Overlay

    private func showOverlay() {
        if overlayPanel == nil {
            overlayPanel = DictationOverlayPanel()
        }
        let view = DictationOverlayView(manager: self)
        overlayPanel?.setContent(view)
        overlayPanel?.showAnimated()
    }

    private func hideOverlay() {
        overlayPanel?.hideAnimated()
        overlayPanel = nil
    }
}
