import Cocoa
import Carbon
import IOKit.hid
import ApplicationServices
import os

private let log = Logger(subsystem: "is.waiwai.computer.app", category: "hotkey")

enum MacPrivacySettings {
    static func openMicrophone() {
        openPrivacyPane("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
    }

    static func openAccessibility() {
        openPrivacyPane("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
    }

    static func openSystemAudio() {
        openPrivacyPane("x-apple.systempreferences:com.apple.preference.security?Privacy_AudioCapture")
    }

    static func restartForPermissionRefresh() {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        configuration.createsNewApplicationInstance = true

        NSWorkspace.shared.openApplication(at: Bundle.main.bundleURL, configuration: configuration) { _, error in
            if let error {
                log.error("Failed to relaunch WaiComputer after permission change: \(error.localizedDescription, privacy: .public)")
                return
            }
            NSApp.terminate(nil)
        }
    }

    static var permissionRestartHint: String {
        "WaiComputer is enabled in System Settings — restart so macOS applies the permission to this running app."
    }

    static var duplicatePermissionHint: String {
        "If WaiComputer appears more than once in the list, keep only the installed copy enabled (remove old rows with the minus button)."
    }

    private static func openPrivacyPane(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        NSWorkspace.shared.open(url)
    }
}

enum MacInputPermission {
    /// Live state of the Accessibility TCC permission for the running process.
    ///
    /// We use Accessibility for two capabilities: (a) global modifier-key
    /// hotkey detection via `NSEvent.addGlobalMonitorForEvents`, and (b)
    /// posting ⌘V via `CGEvent.post` for automatic paste. Both are governed
    /// by the single "Accessibility" entry in System Settings → Privacy &
    /// Security on macOS 11+, mirroring how Wispr Flow / Raycast operate.
    /// Input Monitoring is no longer required.
    enum Status: Equatable {
        case granted
        case denied
        case staleNeedsRestart
    }

    // MARK: - Accessibility (global hotkey monitor + event posting)

    static func accessibilityStatus() -> Status {
        AXIsProcessTrusted() ? .granted : .denied
    }

    static var hasAccessibilityAccess: Bool {
        AXIsProcessTrusted()
    }

    @discardableResult
    static func requestAccessibilityAccess() -> Bool {
        if AXIsProcessTrusted() { return true }
        log.info("Requesting Accessibility via AXIsProcessTrustedWithOptions(prompt: true)")
        let options: CFDictionary = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    // Aliases for the previous post-event-only naming. CGEvent.post is now
    // governed by the same Accessibility TCC service so the underlying
    // implementation is identical.
    static var hasPostEventAccess: Bool { hasAccessibilityAccess }
    @discardableResult
    static func requestPostEventAccess() -> Bool { requestAccessibilityAccess() }
    static func postEventStatus() -> Status { accessibilityStatus() }

    // MARK: - Recovery utilities

    /// Reveal the running app bundle in Finder so the user can drag it onto
    /// the "+" button in System Settings → Privacy & Security to create a
    /// fresh TCC entry tied to the current cdhash. Works without any
    /// entitlement and is the recommended recovery when `CGRequestListenEventAccess`
    /// has gone silent because of a prior denied decision in `TCC.db`.
    static func revealAppInFinder() {
        NSWorkspace.shared.activateFileViewerSelecting([Bundle.main.bundleURL])
    }

    /// One-time cleanup of legacy TCC entries accumulated during the
    /// sandboxed → non-sandboxed migration and entitlement flips that preceded
    /// 1.0.6-46. Each architectural change produced a slightly different
    /// designated requirement, so TCC stored multiple distinct grant entries
    /// for `is.waiwai.computer`, none of which match the current binary's csreq.
    /// Result: onboarding asks for permissions even though Settings shows
    /// "WaiComputer" appearing twice with toggles enabled.
    ///
    /// macOS does not expose an API to inspect TCC.db (SIP-protected), but
    /// `tccutil reset <service> <bundle-id>` clears all entries for our
    /// bundle without sudo. After clearing, fresh prompts in onboarding work
    /// cleanly and the new entries are recorded with the current (now
    /// stable from 1.0.6-46+) designated requirement. Subsequent Sparkle
    /// updates with the same DR preserve the grant naturally — exactly how
    /// Wispr Flow / Raycast / VoiceInk behave.
    ///
    /// Runs at most once (UserDefaults flag). Per-service: only resets
    /// permissions that currently appear ungranted, so a partially-valid
    /// state (e.g., Microphone granted but Accessibility stale) does not
    /// force an unnecessary re-grant of the working permission.
    ///
    /// Relaunch dance: after `tccutil reset`, the running process keeps
    /// stale state in IOHID/CG that swallows subsequent prompts —
    /// `CGRequestListenEventAccess`/`CGRequestPostEventAccess` silently
    /// return false instead of triggering a fresh dialog (only modern
    /// `AVAudioApplication.requestRecordPermission` re-prompts cleanly).
    /// To make Input Monitoring and Accessibility prompts work after the
    /// reset, we relaunch the app — same pattern Sparkle uses post-install.
    /// Returns `true` if a relaunch is required; the caller is responsible
    /// for triggering it before SwiftUI mounts.
    @MainActor
    @discardableResult
    static func performOneTimeLegacyTCCMigrationIfNeeded(microphoneGranted: Bool) -> Bool {
        // Bumped to V3: pre-V3 builds required both Input Monitoring and
        // Accessibility; we now only require Accessibility (NSEvent global
        // monitor + CGEvent.post are governed by the same TCC service on
        // macOS 11+). The migration always cleans the orphaned ListenEvent
        // entry from prior installs so System Settings → Privacy & Security
        // → Input Monitoring stops showing a stale WaiComputer row.
        let key = "waicomputerTCCLegacyMigrationV3Done"
        guard !UserDefaults.standard.bool(forKey: key) else { return false }

        let accessibilityGranted = AXIsProcessTrusted()

        guard let bundleId = Bundle.main.bundleIdentifier else {
            UserDefaults.standard.set(true, forKey: key)
            return false
        }

        // Always clear the legacy ListenEvent row (we no longer use it).
        // Reset Microphone / Accessibility only if currently denied — keeping
        // valid grants intact when Sparkle updates a user from a working
        // post-V2 state.
        var servicesToReset = ["ListenEvent"]
        if !microphoneGranted { servicesToReset.append("Microphone") }
        if !accessibilityGranted { servicesToReset.append("Accessibility") }

        log.info("TCC legacy migration V3: clearing services [\(servicesToReset.joined(separator: ","), privacy: .public)] on \(bundleId, privacy: .public)")

        var didActuallyReset = false
        for service in servicesToReset {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/tccutil")
            process.arguments = ["reset", service, bundleId]
            do {
                try process.run()
                process.waitUntilExit()
                if process.terminationStatus == 0 {
                    didActuallyReset = true
                } else {
                    log.warning("tccutil reset \(service, privacy: .public) returned \(process.terminationStatus)")
                }
            } catch {
                log.error("tccutil reset \(service, privacy: .public) threw: \(error.localizedDescription, privacy: .public)")
            }
        }

        UserDefaults.standard.set(true, forKey: key)
        // Relaunch only if Mic or Accessibility was reset — the legacy
        // ListenEvent reset on its own does not affect any running API.
        let appLevelReset = !microphoneGranted || !accessibilityGranted
        return didActuallyReset && appLevelReset
    }

    /// Spawn a fresh instance of the running app and terminate the current
    /// process. Used after `performOneTimeLegacyTCCMigrationIfNeeded` returns
    /// `true` so post-reset permission prompts are not swallowed by stale
    /// IOHID/CG handles in the existing process.
    @MainActor
    static func relaunchAfterTCCMigration() {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        configuration.createsNewApplicationInstance = true
        NSWorkspace.shared.openApplication(at: Bundle.main.bundleURL, configuration: configuration) { _, error in
            if let error {
                log.error("Relaunch after TCC migration failed: \(error.localizedDescription, privacy: .public). Continuing without relaunch.")
                return
            }
            DispatchQueue.main.async {
                NSApp.terminate(nil)
            }
        }
    }

    /// Reset TCC entries for this app's bundle id across the permissions we
    /// use today (Accessibility, Microphone, AudioCapture) plus the legacy ListenEvent
    /// service that earlier WaiComputer versions required for `CGEventTap`.
    /// Cleaning ListenEvent here removes the orphaned WaiComputer row from
    /// System Settings → Privacy & Security → Input Monitoring on machines
    /// that were upgraded from a pre-NSEvent-monitor build.
    @discardableResult
    static func resetTCCEntries() -> Bool {
        guard let bundleId = Bundle.main.bundleIdentifier else { return false }
        var allOK = true
        for service in ["ListenEvent", "Accessibility", "Microphone", "AudioCapture"] {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/tccutil")
            process.arguments = ["reset", service, bundleId]
            do {
                try process.run()
                process.waitUntilExit()
                if process.terminationStatus != 0 {
                    log.warning("tccutil reset \(service, privacy: .public) returned \(process.terminationStatus)")
                    allOK = false
                }
            } catch {
                log.error("tccutil reset \(service, privacy: .public) threw: \(error.localizedDescription, privacy: .public)")
                allOK = false
            }
        }
        return allOK
    }

    /// One-time cleanup of orphaned TCC entries that survived the
    /// `is.waiwai.say` → `is.waiwai.computer` rebrand. Sparkle replaces the
    /// .app at the existing install location, but TCC entries are keyed by
    /// bundle ID — so users who installed under the WaiSay name keep ghost
    /// "WaiSay.app" rows in System Settings → Privacy & Security long after
    /// the app is renamed. Those rows can't be granted to the new bundle
    /// (different bundle ID, different csreq), they only confuse the user.
    ///
    /// `tccutil reset <service> <bundle-id>` clears the entries for the
    /// supplied bundle ID without sudo. Runs at most once; safe to call
    /// repeatedly because subsequent calls become no-ops via the
    /// UserDefaults flag.
    static func cleanupLegacyWaiSayTCCIfNeeded() {
        let flagKey = "waicomputerLegacyWaiSayTCCCleanupDone"
        guard !UserDefaults.standard.bool(forKey: flagKey) else { return }

        let legacyBundleId = "is.waiwai.say"
        guard Bundle.main.bundleIdentifier == "is.waiwai.computer" else {
            // Only the production WaiComputer build should clean up — the
            // .dev/.tests/.uitests bundles never owned these entries.
            UserDefaults.standard.set(true, forKey: flagKey)
            return
        }

        log.info("Cleaning up orphaned legacy TCC entries for \(legacyBundleId, privacy: .public)")
        for service in ["ListenEvent", "Accessibility", "Microphone", "AudioCapture"] {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/tccutil")
            process.arguments = ["reset", service, legacyBundleId]
            do {
                try process.run()
                process.waitUntilExit()
                // Exit code 0 means an entry existed and was reset; non-zero
                // typically means "no such entry" which is also fine. Either
                // way the user-visible orphan row goes away if it was there.
            } catch {
                log.warning("tccutil reset \(service, privacy: .public) \(legacyBundleId, privacy: .public) threw: \(error.localizedDescription, privacy: .public)")
            }
        }

        UserDefaults.standard.set(true, forKey: flagKey)
    }
}

// MARK: - Hotkey Configuration

enum DeferredDictationStopPolicy {
    enum Action: Equatable {
        case continueListening
        case finishAfterReady
    }

    static func action(deferredStop: Bool, isHandsFree: Bool) -> Action {
        guard deferredStop, !isHandsFree else { return .continueListening }
        return .finishAfterReady
    }
}

enum DictationFinalizationPolicy {
    /// Keep capture alive briefly after the user releases push-to-talk.
    ///
    /// AVAudioEngine taps deliver audio in chunks. If we stop the engine
    /// immediately on key-up, the last syllables can still be sitting in the
    /// current tap buffer and never reach the realtime STT provider.
    static let captureTailDelay: Duration = .milliseconds(450)
}

enum DictationHotkey: String, CaseIterable, Identifiable {
    case rightOption = "right_option"
    case leftOption = "left_option"
    case rightCommand = "right_command"
    case fn = "fn"
    case controlOption = "control_option"

    static let defaultPushToTalk: DictationHotkey = .rightCommand

    var id: String { rawValue }

    var label: String {
        switch self {
        case .rightOption: return "Right Option (\u{2325})"
        case .leftOption: return "Left Option (\u{2325})"
        case .rightCommand: return "Right Command (\u{2318})"
        case .fn: return "Fn (Globe)"
        case .controlOption: return "Control + Option (\u{2303}\u{2325})"
        }
    }

    var shortLabel: String {
        switch self {
        case .rightOption: return "\u{2325} (Right)"
        case .leftOption: return "\u{2325} (Left)"
        case .rightCommand: return "\u{2318} (Right)"
        case .fn: return "Fn"
        case .controlOption: return "\u{2303}\u{2325}"
        }
    }

    /// The keyCode of the modifier key (from Carbon/Events.h)
    var keyCode: UInt16 {
        switch self {
        case .rightOption: return UInt16(kVK_RightOption)
        case .leftOption: return UInt16(kVK_Option)
        case .rightCommand: return UInt16(kVK_RightCommand)
        case .fn: return 63 // kVK_Function
        case .controlOption: return UInt16(kVK_Option) // primary key is option
        }
    }

    /// Modifier flags to check for combo hotkeys (controlOption)
    var requiredFlags: NSEvent.ModifierFlags? {
        switch self {
        case .controlOption: return [.control, .option]
        default: return nil
        }
    }
}

// MARK: - GlobalHotkeyManager

/// Monitors the dictation hotkey.
///
/// All builds use a listen-only CGEventTap so dictation can start while WaiComputer
/// is running in the background. Text insertion is clipboard-first and then
/// posts Cmd+V when the user grants macOS post-event permission.
@MainActor
final class GlobalHotkeyManager: ObservableObject {
    /// Whether the hotkey is currently being held down
    @Published private(set) var isHotkeyHeld = false

    /// Callbacks
    var onPushToTalkStart: (() -> Void)?
    var onPushToTalkStop: (() -> Void)?
    var onHandsFreeToggle: (() -> Void)?
    var onSingleTap: (() -> Void)?
    var onCancelled: (() -> Void)?

    /// Configuration
    var hotkey: DictationHotkey = .defaultPushToTalk {
        didSet { log.info("Hotkey changed to \(self.hotkey.label)") }
    }

    /// Optional separate hotkey that toggles hands-free mode on a single tap.
    /// When `nil`, hands-free still works via double-tap of `hotkey` (legacy).
    var handsFreeHotkey: DictationHotkey? {
        didSet { log.info("Hands-free hotkey: \(self.handsFreeHotkey?.label ?? "double-tap of push-to-talk")") }
    }

    private var handsFreeKeyHeld = false

    /// How long the key must be held before starting push-to-talk.
    ///
    /// Keep this below the threshold where the hotkey feels laggy, but above a
    /// quick tap so double-tap hands-free remains reliable.
    private let holdThreshold: TimeInterval = 0.08

    // State tracking
    private var hotkeyDownTime: Date?
    private var otherKeyPressed = false
    private var isInPushToTalk = false
    private var holdTimer: DispatchWorkItem?

    // Double-tap detection
    private var lastTapTime: Date?
    private let doubleTapInterval: TimeInterval = 0.4

    // NSEvent global monitor (Accessibility-gated) — sees keystrokes in
    // OTHER apps. Read-only by Apple's design; for modifier-key push-to-talk
    // we only need detection, not consumption. Replaces the previous
    // CGEventTap path which required the separate Input Monitoring TCC
    // permission.
    private var globalFlagsMonitor: Any?
    private var globalKeyMonitor: Any?

    // Local monitors for app-focused keyboard handling (no permission
    // required — receive only events delivered to our process).
    private var localFlagsMonitor: Any?
    private var localKeyMonitor: Any?

    private var isRunning = false

    // MARK: - Accessibility Permission

    /// Check if Accessibility permission is granted (covers both global
    /// keyboard monitoring and CGEvent.post for ⌘V paste).
    static var hasAccessibilityPermission: Bool {
        MacInputPermission.hasAccessibilityAccess
    }

    /// Request Accessibility permission — shows the system prompt and/or
    /// opens System Settings → Privacy & Security → Accessibility.
    @discardableResult
    static func requestAccessibilityPermission() -> Bool {
        MacInputPermission.requestAccessibilityAccess()
    }

    func start() {
        if isRunning {
            installGlobalMonitorIfPossible()
            return
        }

        isRunning = true
        installGlobalMonitorIfPossible()

        installLocalMonitorsIfNeeded()

        log.info("Global hotkey monitoring started (\(self.hotkey.label))")
    }

    func stop() {
        guard isRunning else { return }
        isRunning = false
        holdTimer?.cancel()
        holdTimer = nil

        if let m = globalFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = globalKeyMonitor { NSEvent.removeMonitor(m) }
        if let m = localFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = localKeyMonitor { NSEvent.removeMonitor(m) }
        globalFlagsMonitor = nil
        globalKeyMonitor = nil
        localFlagsMonitor = nil
        localKeyMonitor = nil

        log.info("Hotkey monitoring stopped")
    }

    func refreshAfterPermissionChange() {
        guard isRunning else { return }
        installGlobalMonitorIfPossible()
    }

    private func installGlobalMonitorIfPossible() {
        guard globalFlagsMonitor == nil else { return }
        guard Self.hasAccessibilityPermission else {
            log.warning("Accessibility permission missing; global hotkey monitor not installed")
            return
        }

        // .flagsChanged covers all modifier-only hotkeys (rightOption, fn, etc).
        globalFlagsMonitor = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
            DispatchQueue.main.async {
                self?.handleFlagsChanged(keyCode: event.keyCode, flags: event.modifierFlags)
            }
        }

        // .keyDown so we can mark "another key was pressed during the hold"
        // and abort push-to-talk (user typed a real shortcut, not dictation).
        globalKeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] _ in
            DispatchQueue.main.async {
                guard let self, self.isHotkeyHeld else { return }
                self.otherKeyPressed = true
            }
        }

        log.info("Global key monitor installed (\(self.hotkey.label))")
    }

    private func installLocalMonitorsIfNeeded() {
        if localFlagsMonitor == nil {
            localFlagsMonitor = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
                DispatchQueue.main.async { self?.handleFlagsChanged(keyCode: event.keyCode, flags: event.modifierFlags) }
                return event
            }
        }

        if localKeyMonitor == nil {
            localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                DispatchQueue.main.async {
                    guard let self, self.isHotkeyHeld else { return }
                    self.otherKeyPressed = true
                }
                return event
            }
        }
    }

    private func handleFlagsChanged(keyCode: UInt16, flags: NSEvent.ModifierFlags) {
        // 1. If a dedicated hands-free hotkey is configured and is being
        //    pressed, fire onHandsFreeToggle on the press (not on hold).
        //    Distinct from push-to-talk: single press = toggle.
        if let handsFreeHotkey, handsFreeHotkey != hotkey {
            let pressed = isHotkeyEvent(
                keyCode: keyCode,
                flags: flags,
                hotkey: handsFreeHotkey
            )
            if pressed && !handsFreeKeyHeld {
                handsFreeKeyHeld = true
                log.info("Hands-free hotkey pressed — toggling")
                onHandsFreeToggle?()
                return
            } else if !pressed && handsFreeKeyHeld {
                handsFreeKeyHeld = false
                return
            }
        }

        // 2. Push-to-talk hotkey
        let isTargetKey = isHotkeyEvent(keyCode: keyCode, flags: flags)
        if isTargetKey && !isHotkeyHeld {
            hotkeyDown()
        } else if !isTargetKey && isHotkeyHeld {
            hotkeyUp()
        }
    }

    private func isHotkeyEvent(
        keyCode: UInt16,
        flags: NSEvent.ModifierFlags,
        hotkey: DictationHotkey
    ) -> Bool {
        let clean = flags.intersection(.deviceIndependentFlagsMask)
        switch hotkey {
        case .rightOption:
            return keyCode == UInt16(kVK_RightOption) && clean.contains(.option)
        case .leftOption:
            return keyCode == UInt16(kVK_Option) && clean.contains(.option)
        case .rightCommand:
            return keyCode == UInt16(kVK_RightCommand) && clean.contains(.command)
        case .fn:
            return clean.contains(.function)
        case .controlOption:
            return clean.contains(.control) && clean.contains(.option)
        }
    }

    private func isHotkeyEvent(keyCode: UInt16, flags: NSEvent.ModifierFlags) -> Bool {
        isHotkeyEvent(keyCode: keyCode, flags: flags, hotkey: hotkey)
    }

    private func hotkeyDown() {
        isHotkeyHeld = true
        hotkeyDownTime = Date()
        otherKeyPressed = false

        holdTimer?.cancel()
        isInPushToTalk = false

        let timer = DispatchWorkItem { [weak self] in
            guard let self else { return }
            guard self.isHotkeyHeld, !self.otherKeyPressed, !self.isInPushToTalk else { return }
            self.isInPushToTalk = true
            log.info("Push-to-talk started")
            self.onPushToTalkStart?()
        }
        holdTimer = timer
        DispatchQueue.main.asyncAfter(deadline: .now() + holdThreshold, execute: timer)
    }

    private func hotkeyUp() {
        isHotkeyHeld = false
        holdTimer?.cancel()
        holdTimer = nil

        let holdDuration = hotkeyDownTime.map { Date().timeIntervalSince($0) } ?? 0

        if isInPushToTalk {
            isInPushToTalk = false
            if otherKeyPressed {
                log.info("Push-to-talk cancelled after modifier use")
                onCancelled?()
            } else if holdDuration >= holdThreshold {
                log.info("Push-to-talk stopped (held \(String(format: "%.2f", holdDuration))s)")
                onPushToTalkStop?()
            } else {
                log.info("Push-to-talk cancelled before hold threshold")
                onCancelled?()
                registerTap()
            }
        } else if !otherKeyPressed && holdDuration < holdThreshold {
            registerTap()
        } else if otherKeyPressed {
            onCancelled?()
        }

        hotkeyDownTime = nil
        otherKeyPressed = false
    }

    private func registerTap() {
        if let lastTap = lastTapTime,
           Date().timeIntervalSince(lastTap) < doubleTapInterval {
            lastTapTime = nil
            log.info("Double-tap detected — hands-free toggle")
            onHandsFreeToggle?()
        } else {
            lastTapTime = Date()
            log.info("Single tap")
            onSingleTap?()
        }
    }

    #if DEBUG
    func testingPressHotkey() {
        hotkeyDown()
    }

    func testingReleaseHotkey() {
        hotkeyUp()
    }

    func testingHandleFlagsChanged(keyCode: UInt16, flags: NSEvent.ModifierFlags) {
        handleFlagsChanged(keyCode: keyCode, flags: flags)
    }
    #endif

    deinit {
        if let m = globalFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = globalKeyMonitor { NSEvent.removeMonitor(m) }
        if let m = localFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = localKeyMonitor { NSEvent.removeMonitor(m) }
    }
}
