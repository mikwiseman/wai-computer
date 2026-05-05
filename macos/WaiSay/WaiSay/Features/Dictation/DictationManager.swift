import Foundation
import AVFoundation
import SwiftUI
import os
import WaiSayKit

private let log = Logger(subsystem: "com.waisay.app", category: "dictation")

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
    @Published var isEnabled = false
    @Published var error: String?

    // MARK: - Settings (persisted via UserDefaults)

    @AppStorage("dictationHotkey") var hotkeyChoice: String = DictationHotkey.rightOption.rawValue
    @AppStorage("dictationAICleanup") var aiCleanupEnabled: Bool = true
    @AppStorage("dictationEnabled") private var dictationEnabledPreference: Bool = false

    var selectedHotkey: DictationHotkey {
        DictationHotkey(rawValue: hotkeyChoice) ?? .rightOption
    }

    var isFeatureEnabled: Bool {
        dictationEnabledPreference
    }

    // MARK: - Dependencies

    private var apiClient: APIClient?
    private var canStartDictation: (() -> Bool)?
    var historyStore: DictationHistoryStore?
    var dictionaryStore: DictationDictionaryStore?
    let hotkeyManager = GlobalHotkeyManager()

    // MARK: - Overlay

    private var overlayPanel: DictationOverlayPanel?

    // MARK: - Target App (for restoring focus before paste in direct builds)

    private var targetApp: NSRunningApplication?

    // MARK: - Audio & Transcription

    private var audioCapture: MicrophoneCapture?
    private var audioEncoder: AudioEncoder?
    private var webSocket: WebSocketManager?
    private var audioTask: Task<Void, Never>?
    private var transcriptTask: Task<Void, Never>?
    private var timerTask: Task<Void, Never>?

    // Transcript accumulation
    private var committedTexts: [String] = []
    private var currentInterim = ""
    private var isConfigured = false
    private var pendingPushToTalkStop = false

    // MARK: - Lifecycle

    init() {
        setupHotkeyCallbacks()
    }

    /// Called when user authenticates and provides the API client used to mint realtime STT sessions.
    func configure(apiClient: APIClient, canStart: @escaping () -> Bool) {
        self.apiClient = apiClient
        self.canStartDictation = canStart
        isConfigured = true
        applyHotkeyAvailability()
        log.info("Dictation manager configured")
    }

    /// Called when user logs out
    func disable() {
        isConfigured = false
        canStartDictation = nil
        applyHotkeyAvailability()
        Task { await cancelDictation() }
        apiClient = nil
        log.info("Dictation manager disabled")
    }

    func updateEnabled(_ enabled: Bool) {
        dictationEnabledPreference = enabled
        applyHotkeyAvailability()
        if !enabled {
            Task { await cancelDictation() }
        }
    }

    /// Update hotkey from settings
    func updateHotkey(_ hotkey: DictationHotkey) {
        hotkeyChoice = hotkey.rawValue
        hotkeyManager.hotkey = hotkey
        refreshPermissionState()
        log.info("Hotkey updated to \(hotkey.label)")
    }

    func refreshPermissionState() {
        hotkeyManager.refreshAfterPermissionChange()
        applyHotkeyAvailability()
    }

    // MARK: - Hotkey Callbacks

    private func setupHotkeyCallbacks() {
        hotkeyManager.onPushToTalkStart = { [weak self] in
            guard let self else { return }
            guard self.isEnabled else {
                log.warning("Dictation hotkey pressed but not enabled (not authenticated?)")
                return
            }
            guard self.canBeginExternalDictation() else { return }
            guard self.state == .idle else { return }
            self.isHandsFree = false
            Task { await self.startDictation() }
        }

        hotkeyManager.onPushToTalkStop = { [weak self] in
            guard let self else { return }
            guard !self.isHandsFree else { return } // Don't stop if in hands-free mode
            if self.state == .connecting {
                self.pendingPushToTalkStop = true
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
                self.isHandsFree = true
                Task { await self.startDictation() }
            }
        }

        hotkeyManager.onSingleTap = { [weak self] in
            guard let self else { return }
            // Single tap stops hands-free recording (like Wispr Flow)
            if self.state == .listening && self.isHandsFree {
                Task { await self.stopAndInsert() }
            }
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
            return
        }

        guard let apiClient else {
            error = "Not authenticated. Please log in first."
            return
        }
        guard canBeginExternalDictation() else { return }

        // Remember the target app so we can re-focus it before pasting
        targetApp = NSWorkspace.shared.frontmostApplication

        // Check microphone permission
        let micGranted = await AVAudioApplication.requestRecordPermission()
        guard micGranted else {
            error = "Microphone permission denied."
            return
        }

        error = nil
        committedTexts = []
        currentInterim = ""
        interimTranscript = ""
        dictationDuration = 0
        pendingPushToTalkStop = false
        setState(.connecting)

        // Show overlay
        showOverlay()

        // Play start sound (subtle, non-alarming)
        NSSound(named: NSSound.Name("Morse"))?.play()

        do {
            // Set up microphone capture
            let capture = MicrophoneCapture()
            audioCapture = capture
            try await capture.startRecording()

            // Set up provider-backed realtime transcription.
            let language = UserDefaults.standard.string(forKey: "transcriptionLanguage") ?? "multi"
            let ws = WebSocketManager(apiClient: apiClient, language: language, channels: 1)
            webSocket = ws

            // Start receiving transcript events BEFORE connecting
            let eventStream = await ws.events
            transcriptTask = Task { [weak self] in
                guard let self else { return }
                for await event in eventStream {
                    await self.handleWebSocketEvent(event)
                }
            }

            // Connect
            try await ws.connect()

            // Set up audio encoding pipeline
            let encoder = AudioEncoder(channels: 1)
            audioEncoder = encoder

            // Stream audio to the configured transcription provider.
            audioTask = Task.detached(priority: .userInitiated) {
                for await buffer in capture.audioBuffers {
                    if let data = encoder.encode(buffer) {
                        do {
                            try await ws.sendAudio(data: data)
                        } catch {
                            log.error("Failed to send dictation audio")
                            return
                        }
                    }
                }
            }

            // Start duration timer
            startTimer()
            setState(.listening)
            if pendingPushToTalkStop && !isHandsFree {
                pendingPushToTalkStop = false
                await stopAndInsert()
            }

        } catch {
            log.error("Failed to start dictation")
            self.error = error.userFacingMessage(context: .dictation)
            await resetAfterStartFailure()
        }
    }

    func stopAndInsert() async {
        guard state == .listening else { return }
        setState(.processing)

        // Stop audio capture
        await audioCapture?.stopRecording()
        _ = await audioTask?.result
        audioTask = nil

        let didFinalize = await finishStreaming()

        // If cancelDictation ran during finalization (e.g. WebSocket disconnect), bail out
        guard state == .processing else { return }

        // Collect final segments
        let segments = await webSocket?.collectedSegments ?? []

        // Stop transcript listener and WebSocket
        transcriptTask?.cancel()
        transcriptTask = nil
        await webSocket?.disconnect()
        webSocket = nil

        // Stop timer
        timerTask?.cancel()
        timerTask = nil

        // Build final text — prefer segments, fall back to local accumulation
        let finalText = finalTranscriptText(from: segments, didFinalize: didFinalize)

        let trimmedText = finalText.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !trimmedText.isEmpty else {
            log.info("No text transcribed — nothing to insert")
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
                let cleaned = try await apiClient.cleanupDictation(text: trimmedText)
                textToInsert = cleaned
                log.info("AI cleanup: \(trimmedText.count) → \(cleaned.count) chars")
            } catch {
                log.warning("AI cleanup failed, using raw transcript")
                if let apiError = error as? APIError, case .unauthorized = apiError {
                    self.error = apiError.userFacingMessage(context: .dictation)
                }
                // Continue with raw text
            }
        }

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
                self.error = "\(insertionError.localizedDescription) A recovery copy was kept on this Mac."
            } else if recoveryURL != nil {
                self.error = "We couldn't insert the dictated text into the current app. A recovery copy was kept on this Mac."
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

        await audioCapture?.stopRecording()
        audioTask?.cancel()
        audioTask = nil
        transcriptTask?.cancel()
        transcriptTask = nil
        timerTask?.cancel()
        timerTask = nil
        await webSocket?.disconnect()
        webSocket = nil

        await cleanup()
    }

    // MARK: - Private

    private func setState(_ newState: State) {
        withAnimation(.easeInOut(duration: 0.15)) {
            state = newState
        }
    }

    private func cleanup() async {
        audioCapture = nil
        audioEncoder = nil
        pendingPushToTalkStop = false

        targetApp = nil
        setState(.idle)
        isHandsFree = false
        hideOverlay()
    }

    private func resetAfterStartFailure() async {
        audioTask?.cancel()
        audioTask = nil
        transcriptTask?.cancel()
        transcriptTask = nil
        timerTask?.cancel()
        timerTask = nil
        await audioCapture?.stopRecording()
        audioCapture = nil
        audioEncoder = nil
        let ws = webSocket
        webSocket = nil
        await ws?.disconnect()
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

    // MARK: - WebSocket Events

    private func handleWebSocketEvent(_ event: WebSocketEvent) async {
        switch event {
        case .connected:
            break
        case .transcript(let segment):
            if segment.isFinal {
                committedTexts.append(segment.text)
                currentInterim = ""
            } else {
                currentInterim = segment.text
            }
            interimTranscript = buildTranscript()
        case .disconnected(let err):
            if let err, state == .listening {
                log.error("WebSocket disconnected during dictation")
                if (try? saveRecoveryText(buildTranscript())) != nil {
                    error = "Connection was interrupted. A recovery copy of your dictated text was kept on this Mac."
                } else {
                    error = err.userFacingMessage(context: .dictation)
                }
                await cancelDictation()
            }
        case .reconnecting:
            break // Dictation sessions are short — reconnection handled by WebSocketManager
        case .reconnected:
            break
        case .reconnectionFailed(let err):
            if state == .listening {
                log.error("WebSocket reconnection failed during dictation")
                if (try? saveRecoveryText(buildTranscript())) != nil {
                    error = "Connection was interrupted. A recovery copy of your dictated text was kept on this Mac."
                } else {
                    error = err?.userFacingMessage(context: .dictation)
                        ?? "We couldn't keep dictation connected. Check your internet connection and try again."
                }
                await cancelDictation()
            }
        }
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
        guard let canStartDictation else { return false }
        return canStartDictation()
    }

    private func finalTranscriptText(
        from segments: [LiveTranscriptSegment],
        didFinalize: Bool
    ) -> String {
        let remoteTranscript = segments
            .map(\.text)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")

        let localTranscript = buildTranscript().trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedInterim = currentInterim.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !remoteTranscript.isEmpty else { return localTranscript }
        guard !localTranscript.isEmpty else { return remoteTranscript }

        if remoteTranscript == localTranscript {
            return remoteTranscript
        }

        if !trimmedInterim.isEmpty && remoteTranscript.hasSuffix(trimmedInterim) {
            return remoteTranscript
        }

        if !trimmedInterim.isEmpty && localTranscript.hasPrefix(remoteTranscript) {
            return localTranscript
        }

        if !didFinalize && localTranscript.count >= remoteTranscript.count {
            return localTranscript
        }

        return remoteTranscript.count >= localTranscript.count ? remoteTranscript : localTranscript
    }

    private func applyHotkeyAvailability() {
        hotkeyManager.hotkey = selectedHotkey
        let shouldEnable = isConfigured && dictationEnabledPreference
        isEnabled = shouldEnable
        if shouldEnable {
            hotkeyManager.start()
        } else {
            hotkeyManager.stop()
        }
    }

    private func finishStreaming() async -> Bool {
        guard let webSocket else { return true }
        do {
            return try await webSocket.finishStreaming(timeout: .seconds(5))
        } catch {
            log.error("Failed to finalize dictation stream")
            return false
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
            .appendingPathComponent("WaiSay", isDirectory: true)
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
