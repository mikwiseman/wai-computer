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

    @discardableResult
    func record(bytes byteCount: Int, chunks chunkCount: Int = 1) -> (chunks: Int, bytes: Int) {
        lock.lock()
        chunks += chunkCount
        bytes += byteCount
        let snapshot = (chunks, bytes)
        lock.unlock()
        return snapshot
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
    private static let liveSTTProvider = "deepgram"
    private static let liveSTTModel = "nova-3"
    private static let liveSTTSampleRate = 16_000
    private static let startupAudioMaxBufferedBytes = liveSTTSampleRate * 2 * 30

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
                sessionConfigPrefetchRefreshTask?.cancel()
                sessionConfigPrefetchRefreshTask = nil
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

    // Provider-backed realtime dictation path.
    private var providerSession: (any ProviderSession)?
    /// Lease on the shared, pre-warmed `AudioEngineHost`. Replaces the
    /// per-press `MicrophoneCapture` we used until Mac build 161, which
    /// degraded the macOS HAL after 3-5 dictation cycles
    /// (kAudioUnitErr_FailedInitialization or silent buffers) — the latent
    /// "starts then immediately stops" bug. With AudioEngineHost the engine
    /// starts ONCE for the lifetime of the dictation feature, and per-press
    /// sessions just attach a buffer fan-out via `lease()`.
    private var activeAudioLease: AudioEngineHost.Lease?
    private var providerAudioTask: Task<Void, Never>?
    private var sessionEventTask: Task<Void, Never>?

    private var timerTask: Task<Void, Never>?
    private var sessionConfigPrefetchRefreshTask: Task<Void, Never>?
    private let sessionConfigPrefetchRefreshInterval: Duration = .seconds(20)
    // Bound idle prewarming so an idle client can't mint realtime tokens forever
    // (cost-runaway guard). 15 x 20s = ~5 min of warm-token upkeep after activity;
    // after that we stop until the next dictation / config change re-prefetches.
    private let sessionConfigPrefetchMaxIdleRefreshes = 15

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
        prefetchDictationSessionConfig(reason: "configure")
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
        sessionConfigPrefetchRefreshTask?.cancel()
        sessionConfigPrefetchRefreshTask = nil
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
        if DictationSessionConfigInvalidationPolicy.shouldClearVault(
            previousProvider: previousProvider,
            previousModel: previousModel,
            nextProvider: settings.dictationLiveSTTProvider,
            nextModel: settings.dictationLiveSTTModel
        ) {
            let vault = sessionConfigVault
            Task { await vault?.clear() }
        }
        prefetchDictationSessionConfig(reason: "settings_ingested")
    }

    func prefetchSessionConfigForCurrentLanguage(reason: String) {
        prefetchDictationSessionConfig(reason: reason)
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
            // Clear any stale deferred-stop SYNCHRONOUSLY before we Task the
            // start. A subsequent onPushToTalkStop (fired before startDictation
            // executes setState(.connecting)) is then free to set the flag
            // again and have it honoured at the .listening transition.
            self.deferredStop = false
            self.setHandsFree(false)
            Task { await self.startDictation() }
        }

        hotkeyManager.onPushToTalkStop = { [weak self] in
            guard let self else { return }
            let policyState: PushToTalkStopState
            switch self.state {
            case .idle: policyState = .idle
            case .connecting: policyState = .connecting
            case .listening: policyState = .listening
            case .processing, .inserting: policyState = .finalizing
            }
            switch PushToTalkStopPolicy.resolve(state: policyState, isHandsFree: self.isHandsFree) {
            case .finishNow:
                Task { await self.stopAndInsert() }
            case .deferUntilReady:
                // .idle: onPushToTalkStart Task hasn't yet executed
                // setState(.connecting). .connecting: WS handshake / REST
                // mint in flight. Either way the start path picks this up
                // the moment state transitions to .listening.
                self.deferredStop = true
                SentryHelper.addBreadcrumb(
                    category: "dictation.session",
                    message: "stop deferred until provider ready",
                    data: ["state": String(describing: self.state)]
                )
            case .doNothing:
                break
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
        // NOTE: do NOT reset `deferredStop` here. The onPushToTalkStart
        // callback already cleared it synchronously before scheduling this
        // Task; resetting here would race against an onPushToTalkStop that
        // fired during the .notDetermined permission grant await above.
        // cleanup()/cancelDictation() also clear it on every exit path.
        audioSendCounter.reset()
        setState(.connecting)
        sessionConfigPrefetchRefreshTask?.cancel()
        sessionConfigPrefetchRefreshTask = nil
        session.event(.providerConnecting, data: ["isHandsFree": isHandsFree])

        // Show overlay
        showOverlay()

        // Play start sound (subtle, non-alarming)
        NSSound(named: NSSound.Name("Morse"))?.play()

        do {
            // Acquire an exclusive lease on the shared pre-warmed engine.
            // `prewarm()` is idempotent and was already invoked the first
            // time the user enabled the hotkey; the call here is the safety
            // net for cold-launch dictation before the eager prewarm Task
            // has run.
            try await AudioEngineHost.shared.prewarm()
            let lease = try await AudioEngineHost.shared.lease()
            activeAudioLease = lease
            let startupAudioBuffer = DictationStartupAudioBuffer(
                maxBufferedBytes: Self.startupAudioMaxBufferedBytes
            )
            let encoder = RealtimePCMEncoder(
                targetSampleRate: Self.liveSTTSampleRate,
                channels: 1
            )
            let audioCounter = audioSendCounter
            let liveProvider = Self.liveSTTProvider
            providerAudioTask = Task.detached(priority: .userInitiated) { [weak self, startupAudioBuffer, lease, session, liveProvider] in
                var liveSent = 0

                func pump(_ buffer: AVAudioPCMBuffer) async -> Bool {
                    guard !Task.isCancelled else { return false }
                    guard let data = encoder.encode(buffer) else { return true }
                    do {
                        let result = try await startupAudioBuffer.append(data)
                        if case .sent(let bytes) = result {
                            liveSent += 1
                            let snapshot = audioCounter.record(bytes: bytes)
                            if snapshot.chunks == 1 {
                                session.event(.audioFirstChunkSent, data: [
                                    "provider": liveProvider,
                                    "bytes": bytes,
                                    "startupBuffered": false,
                                ])
                            }
                            if liveSent <= 3 || liveSent % 20 == 0 {
                                NSLog("[Dictation/Provider] sent #%d %d bytes provider=%@", liveSent, bytes, liveProvider)
                            }
                        }
                        return true
                    } catch {
                        NSLog("[Dictation/Provider] startup audio send failed provider=%@: %@", liveProvider, String(describing: error))
                        let manager = self
                        await MainActor.run {
                            guard let manager else { return }
                            manager.error = error.userFacingMessage(context: .dictation)
                            manager.instrumentationSession?.failure(error, extras: ["stage": "startup_audio"])
                            manager.instrumentationSession = nil
                            Task { await manager.cancelDictation() }
                        }
                        return false
                    }
                }

                // Flush the 500 ms pre-roll captured BEFORE the hotkey press
                // first. This is the marquee win of the AudioEngineHost
                // pattern — a user who starts speaking the same instant
                // they press the hotkey still gets a complete transcript.
                for buffer in lease.preRoll {
                    let ok = await pump(buffer)
                    if !ok { return }
                }
                // Then drain live buffers until the lease is released by the
                // main flow (finishProviderAudioPumpBeforeFinalizing) or
                // cleanup() — both finish the underlying continuation.
                for await buffer in lease.buffers {
                    let ok = await pump(buffer)
                    if !ok { return }
                }
                NSLog("[Dictation/Provider] lease stream ended provider=%@ sent=%d preRollCount=%d", liveProvider, liveSent, lease.preRoll.count)
            }
            session.event(.audioLeaseAcquired, data: [
                "sampleRate": Self.liveSTTSampleRate,
                "startupBuffered": true,
                "preRollBuffers": lease.preRoll.count,
                "engineHost": true,
            ])

            refreshSettingsAndPrefetchIfNeeded(apiClient: apiClient, reason: "start")

            let language = currentDictationLanguage()
            let sessionConfig = try await takeDictationSessionConfig(
                language: language,
                session: session,
                apiClient: apiClient
            )
            guard state == .connecting else {
                await startupAudioBuffer.close()
                return
            }

            guard sessionConfig.provider == Self.liveSTTProvider else {
                throw ProviderError.unsupportedModel(sessionConfig.provider)
            }
            guard sessionConfig.model == Self.liveSTTModel else {
                throw ProviderError.unsupportedModel(sessionConfig.model)
            }
            guard sessionConfig.sampleRate == Self.liveSTTSampleRate else {
                throw ProviderError.transcriberInternal(
                    message: "Deepgram realtime session returned unsupported sample_rate=\(sessionConfig.sampleRate)"
                )
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

            try await provider.open()
            guard state == .connecting else {
                await startupAudioBuffer.close()
                return
            }
            let startupFlush = try await startupAudioBuffer.startStreaming(to: provider)
            if startupFlush.bytes > 0 {
                let snapshot = audioCounter.record(
                    bytes: startupFlush.bytes,
                    chunks: startupFlush.chunks
                )
                if snapshot.chunks == startupFlush.chunks {
                    session.event(.audioFirstChunkSent, data: [
                        "provider": sessionConfig.provider,
                        "bytes": startupFlush.bytes,
                        "startupBuffered": true,
                        "startupBufferedChunks": startupFlush.chunks,
                    ])
                }
            }
            session.event(.providerOpened, data: [
                "startupBufferedBytes": startupFlush.bytes,
                "startupBufferedChunks": startupFlush.chunks,
            ])

            startTimer()
            setState(.listening)

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

        // Drain the active provider before choosing the best final transcript.
        await finishProviderAudioPumpBeforeFinalizing()
        let providerSegments = (try? await providerSession?.close(timeout: .seconds(4))) ?? []

        // If cancelDictation ran during finalization, bail out cleanly.
        guard state == .processing else { return }

        sessionEventTask?.cancel()
        sessionEventTask = nil
        timerTask?.cancel()
        timerTask = nil

        let providerTranscript = providerSegments
            .map(\.text)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let liveTranscript = buildTranscript()
        let trimmedText = RealtimeTranscriptCandidateSelector.select([
            providerTranscript.isEmpty ? nil : providerTranscript,
            liveTranscript,
        ])
        let audioSnapshot = audioSendCounter.snapshot()
        instrumentationSession?.event(.transcriptFinalized, data: [
            "durationMs": Int(dictationDuration * 1000),
            "audioChunksSent": audioSnapshot.chunks,
            "audioBytesSent": audioSnapshot.bytes,
            "providerSegmentCount": providerSegments.count,
            "providerChars": providerTranscript.count,
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
        let rawText = dictionaryStore?.applyReplacements(to: trimmedText) ?? trimmedText

        // AI cleanup (optional). If enabled, cleanup is part of the requested
        // output contract: failure is surfaced instead of silently inserting
        // raw text that the user explicitly asked us to post-process.
        let cleanupEnabled = aiCleanupEnabled
        var cleanedText: String?
        var cleanupError: Error?
        if cleanupEnabled {
            if let apiClient {
                do {
                    // Pass the dictionary's vocabulary list so the cleanup pass
                    // preserves user-curated spellings exactly (proper nouns,
                    // jargon, custom terminology that the LLM might otherwise
                    // "correct" away).
                    let vocabulary = dictionaryStore?.vocabularyList ?? []
                    cleanedText = try await apiClient.cleanupDictation(
                        text: rawText,
                        vocabulary: vocabulary
                    )
                    log.info("AI cleanup: \(rawText.count) → \(cleanedText?.count ?? 0) chars (vocab=\(vocabulary.count))")
                } catch {
                    cleanupError = error
                }
            } else {
                cleanupError = NSError(
                    domain: "is.waiwai.computer.dictation.cleanup",
                    code: 2,
                    userInfo: [NSLocalizedDescriptionKey: "AI cleanup is enabled but the API client is unavailable."]
                )
            }
        }

        let textToInsert: String
        do {
            textToInsert = try DictationCleanupPolicy.textToInsert(
                rawText: rawText,
                cleanupEnabled: cleanupEnabled,
                cleanedText: cleanedText,
                cleanupError: cleanupError
            )
        } catch {
            log.error("AI cleanup failed")
            self.error = error.userFacingMessage(context: .dictation)
            instrumentationSession?.failure(error, extras: [
                "stage": "cleanup",
                "rawChars": rawText.count,
            ])
            instrumentationSession = nil
            SentryHelper.captureError(error, extras: [
                "context": "dictation.cleanup",
                "rawChars": rawText.count,
            ])
            await cleanup()
            return
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
        sessionEventTask?.cancel()
        sessionEventTask = nil
        timerTask?.cancel()
        timerTask = nil

        await cleanup()
    }

    private func finishProviderAudioPumpBeforeFinalizing() async {
        if let lease = activeAudioLease {
            await waitForFinalCaptureTail()
            await AudioEngineHost.shared.release(lease)
            activeAudioLease = nil
        }
        await providerAudioTask?.value
        providerAudioTask = nil
    }

    private func waitForFinalCaptureTail() async {
        guard !Task.isCancelled else { return }
        try? await Task.sleep(for: DictationFinalizationPolicy.captureTailDelay)
    }

    private func currentDictationLanguage() -> String {
        DictationLanguageSelectionPolicy.providerLanguage(store: languageStore)
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
        scheduleDictationSessionConfigRefresh(for: key)
        SentryHelper.addBreadcrumb(
            category: "dictation.session",
            message: "realtime config prefetch scheduled",
            data: [
                "reason": reason,
                "language": key.language,
            ]
        )
    }

    private func scheduleDictationSessionConfigRefresh(
        for key: RealtimeTranscriptionSessionConfigVault.Key
    ) {
        sessionConfigPrefetchRefreshTask?.cancel()
        let interval = sessionConfigPrefetchRefreshInterval
        let maxRefreshes = sessionConfigPrefetchMaxIdleRefreshes
        sessionConfigPrefetchRefreshTask = Task { [weak self] in
            var refreshes = 0
            while !Task.isCancelled {
                do {
                    try await Task.sleep(for: interval)
                } catch {
                    return
                }

                // Stop minting once the idle prewarm window elapses. This prevents
                // a stuck/idle client from re-minting realtime tokens indefinitely.
                refreshes += 1
                if refreshes > maxRefreshes {
                    return
                }

                let shouldContinue = await MainActor.run { () -> Bool in
                    guard let self,
                          self.isConfigured,
                          self.isFeatureEnabled,
                          self.state == .idle,
                          let sessionConfigVault = self.sessionConfigVault else {
                        return false
                    }

                    let currentKey = self.dictationSessionConfigKey()
                    guard currentKey == key else {
                        self.prefetchDictationSessionConfig(reason: "language_changed")
                        return false
                    }

                    Task { await sessionConfigVault.prefetch(for: currentKey) }
                    SentryHelper.addBreadcrumb(
                        category: "dictation.session",
                        message: "realtime config prefetch refreshed",
                        data: ["language": currentKey.language]
                    )
                    return true
                }

                if !shouldContinue {
                    return
                }
            }
        }
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

    private func refreshSettingsAndPrefetchIfNeeded(apiClient: APIClient, reason: String) {
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
            return
        }

        refreshSettingsAndPrefetch(apiClient: apiClient, reason: reason)
    }

    private func takeDictationSessionConfig(
        language: String,
        session: DictationInstrumentation.Session,
        apiClient: APIClient
    ) async throws -> RealtimeTranscriptionSessionConfig {
        let key = dictationSessionConfigKey(language: language)
        let result: RealtimeTranscriptionSessionConfigVault.TakeResult
        if let sessionConfigVault {
            result = try await sessionConfigVault.take(
                for: key,
                expectedProvider: Self.liveSTTProvider,
                expectedModel: Self.liveSTTModel
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
        sessionConfigPrefetchRefreshTask?.cancel()
        sessionConfigPrefetchRefreshTask = nil

        let activeProviderSession = providerSession
        providerSession = nil
        providerAudioTask?.cancel()
        providerAudioTask = nil
        await activeProviderSession?.cancel()
        if let lease = activeAudioLease {
            await AudioEngineHost.shared.release(lease)
            activeAudioLease = nil
        }

        deferredStop = false
        firstTokenReported = false

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

    // MARK: - Provider Events

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
            // commitThrottled, malformedFrame, transcriberInternal, or other
            // provider-internal warnings) is surfaced as a hint but the
            // overlay stays open and the audio pump keeps trying. PTT still
            // fails-fast across the board
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
            // serverError / networkLost / serverEndOfStream / sessionTimeLimitExceeded
            // all mean the WebSocket is dead. We MUST act on these in both
            // .listening AND .connecting: previously a close fired during the
            // handshake window was silently swallowed (the guard required
            // .listening), state then transitioned to .listening over a dead
            // socket, the next audio send threw inside the detached audio
            // pump, and the only user-visible signal was the overlay flashing
            // and vanishing — the "dictation starts then immediately stops"
            // bug. .clientRequested is our own close call so we still ignore
            // it (cleanup() is already running).
            switch reason {
            case .serverError, .networkLost, .serverEndOfStream, .sessionTimeLimitExceeded:
                guard state == .listening || state == .connecting else { break }
                self.error = "Connection to the transcription service was lost. Try again."
                log.info("Cancelling dictation — provider closed state=\(String(describing: self.state), privacy: .public) reason=\(String(describing: reason), privacy: .public)")
                let closeError = NSError(
                    domain: "is.waiwai.computer.dictation",
                    code: 1001,
                    userInfo: [NSLocalizedDescriptionKey: "Provider closed unexpectedly: \(reason)"]
                )
                SentryHelper.captureError(
                    closeError,
                    extras: [
                        "context": "dictation.provider.closed",
                        "state": String(describing: state),
                        "reason": String(describing: reason),
                        "isHandsFree": isHandsFree,
                    ]
                )
                await cancelDictation()
            case .clientRequested:
                break
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
            // Eagerly pre-warm the shared engine so the first hotkey press
            // doesn't pay the ~300-800 ms engine.start() + Bluetooth HFP
            // profile-switch cost mid-dictation. prewarm() is idempotent
            // and async; the lazy fallback in startDictation handles cold
            // launches where this hasn't completed yet. Failures are
            // surfaced via the host's own error path and the lazy
            // prewarm in startDictation will throw with a user-visible
            // message.
            Task {
                do {
                    try await AudioEngineHost.shared.prewarm()
                    log.info("AudioEngineHost prewarmed for dictation")
                } catch {
                    log.warning("AudioEngineHost prewarm failed: \(error.localizedDescription, privacy: .public)")
                }
            }
        } else {
            hotkeyManager.stop()
            // Release the shared engine when dictation is disabled so we
            // don't hold the mic indefinitely (also: gives MacRecordingViewModel
            // exclusive access to the input device when the user only uses
            // full recordings, not dictation).
            Task {
                await AudioEngineHost.shared.teardown()
            }
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
