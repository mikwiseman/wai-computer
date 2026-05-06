import Cocoa
import Carbon
import IOKit.hid
import ApplicationServices
import os

private let log = Logger(subsystem: "com.waisay.app", category: "hotkey")

enum MacPrivacySettings {
    static func openMicrophone() {
        openPrivacyPane("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
    }

    static func openInputMonitoring() {
        openPrivacyPane("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")
    }

    static func openAccessibility() {
        openPrivacyPane("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
    }

    static func restartForPermissionRefresh() {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        configuration.createsNewApplicationInstance = true

        NSWorkspace.shared.openApplication(at: Bundle.main.bundleURL, configuration: configuration) { _, error in
            if let error {
                log.error("Failed to relaunch WaiSay after permission change: \(error.localizedDescription, privacy: .public)")
                return
            }
            NSApp.terminate(nil)
        }
    }

    static var permissionRestartHint: String {
        "WaiSay is enabled in System Settings — restart so macOS applies the permission to this running app."
    }

    static var duplicatePermissionHint: String {
        "If WaiSay appears more than once in the list, keep only the installed copy enabled (remove old rows with the minus button)."
    }

    private static func openPrivacyPane(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        NSWorkspace.shared.open(url)
    }
}

enum MacInputPermission {
    /// Live state of an input-related TCC permission for the running process.
    ///
    /// macOS caches the answer to `CGPreflight*` and `IOHIDCheckAccess` at the
    /// kernel level. After a user toggles a permission in System Settings the
    /// cached answer can lag reality for the lifetime of the running process.
    /// Functional probes (`CGEvent.tapCreate(.listenOnly)`, `AXIsProcessTrusted`)
    /// reflect the *effective* grant for this process and disambiguate between
    /// "really granted" and "preflight is still lying".
    enum Status: Equatable {
        /// Preflight + functional probe both agree — the permission works now.
        case granted
        /// No grant is recorded — the user has not yet enabled it (or denied it).
        case denied
        /// Cached APIs say granted but a live probe fails — typically because the
        /// user toggled the permission in System Settings while the app was
        /// running (or the entry in TCC is stale after a re-sign / path change).
        /// Restarting the app is the only reliable fix.
        case staleNeedsRestart
    }

    /// `true` when running inside an App Sandbox container.
    ///
    /// Apple confirms that `CGEventTap` with `.listenOnly` + Input Monitoring
    /// permission *is* compatible with the App Sandbox (since macOS 10.15) —
    /// it's the path WaiSay uses for the global dictation hotkey on the App
    /// Store / TestFlight build. So the probe should work in both channels.
    /// We keep a sandbox flag only as a *fallback*: if the probe ever fails
    /// despite preflight saying granted, in a sandboxed build we trust the
    /// preflight cache rather than push the user into a permanent
    /// "Restart Required" state, since some sandbox edge cases can interfere
    /// with the probe in ways that don't reflect the live tap.
    static let isSandboxed: Bool = {
        ProcessInfo.processInfo.environment["APP_SANDBOX_CONTAINER_ID"] != nil
    }()

    // MARK: - Listen events (Input Monitoring)

    static func listenEventStatus() -> Status {
        let preflight = CGPreflightListenEventAccess()
        let iohid = IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) == kIOHIDAccessTypeGranted

        guard preflight || iohid else {
            return .denied
        }

        // Try the functional probe first — it's authoritative when it succeeds.
        if canCreateListenOnlyTap() {
            return .granted
        }

        // Probe failed even though the preflight cache claims the permission is
        // granted. In a non-sandboxed build (Direct DMG) this is a real stale
        // TCC entry — the user toggled the permission while the app was running
        // or the bundle was re-signed. A restart is the only reliable fix.
        // In a sandboxed build (App Store / TestFlight) sandbox boundaries can
        // cause the probe to fail spuriously even when the live tap installed
        // by `installEventTapIfPossible` succeeds, so we fall back to trusting
        // preflight to avoid a permanent "Restart Required" loop.
        if isSandboxed {
            log.info("Listen-event probe failed in sandbox — trusting preflight cache")
            return .granted
        }
        return .staleNeedsRestart
    }

    static var hasListenEventAccess: Bool {
        listenEventStatus() == .granted
    }

    @discardableResult
    static func requestListenEventAccess() -> Bool {
        if listenEventStatus() == .granted {
            return true
        }

        log.info("Requesting Input Monitoring listen-event access")
        if CGRequestListenEventAccess() {
            return true
        }

        return IOHIDRequestAccess(kIOHIDRequestTypeListenEvent)
    }

    /// Functional probe: install a listen-only event tap and immediately disable
    /// + invalidate it. Returns `true` only if the kernel actually let us see
    /// events. This is the same trick used by other dictation utilities to
    /// detect stale TCC grants.
    private static func canCreateListenOnlyTap() -> Bool {
        let mask: CGEventMask = (1 << CGEventType.flagsChanged.rawValue)
        let probe = CGEvent.tapCreate(
            tap: .cghidEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: mask,
            callback: { _, _, event, _ in Unmanaged.passUnretained(event) },
            userInfo: nil
        )
        guard let probe else { return false }
        CGEvent.tapEnable(tap: probe, enable: false)
        CFMachPortInvalidate(probe)
        return true
    }

    // MARK: - Post events (Accessibility)

    static func postEventStatus() -> Status {
        let axTrusted = AXIsProcessTrusted()
        if axTrusted {
            return .granted
        }

        // AX is the live source of truth for the Accessibility / post-event
        // permission. If the kernel cache disagrees, the entry exists but is
        // stale — typically the user toggled it while the app was running, or
        // the bundle was re-signed and the cdhash drifted.
        let preflight = CGPreflightPostEventAccess()
        let iohid = IOHIDCheckAccess(kIOHIDRequestTypePostEvent) == kIOHIDAccessTypeGranted
        if preflight || iohid {
            return .staleNeedsRestart
        }

        return .denied
    }

    static var hasPostEventAccess: Bool {
        postEventStatus() == .granted
    }

    @discardableResult
    static func requestPostEventAccess() -> Bool {
        if postEventStatus() == .granted {
            return true
        }

        log.info("Requesting Accessibility/post-event access")
        if CGRequestPostEventAccess() {
            return true
        }

        return IOHIDRequestAccess(kIOHIDRequestTypePostEvent)
    }
}

// MARK: - Hotkey Configuration

enum DictationHotkey: String, CaseIterable, Identifiable {
    case rightOption = "right_option"
    case leftOption = "left_option"
    case rightCommand = "right_command"
    case fn = "fn"
    case controlOption = "control_option"

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
/// All builds use a listen-only CGEventTap so dictation can start while WaiSay
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
    var hotkey: DictationHotkey = .rightOption {
        didSet { log.info("Hotkey changed to \(self.hotkey.label)") }
    }

    /// How long the key must be held before starting push-to-talk (ms)
    private let holdThreshold: TimeInterval = 0.25

    // State tracking
    private var hotkeyDownTime: Date?
    private var otherKeyPressed = false
    private var isInPushToTalk = false
    private var holdTimer: DispatchWorkItem?

    // Double-tap detection
    private var lastTapTime: Date?
    private let doubleTapInterval: TimeInterval = 0.4

    // CGEventTap resources for global hold-to-talk monitoring.
    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?

    // Local monitors for app-focused keyboard handling.
    private var localFlagsMonitor: Any?
    private var localKeyMonitor: Any?

    private var isRunning = false

    // MARK: - Input Monitoring Permission

    /// Check if Input Monitoring permission is granted
    static var hasInputMonitoringPermission: Bool {
        MacInputPermission.hasListenEventAccess
    }

    /// Request Input Monitoring permission — shows the system prompt
    @discardableResult
    static func requestInputMonitoringPermission() -> Bool {
        MacInputPermission.requestListenEventAccess()
    }

    func start() {
        if isRunning {
            installEventTapIfPossible()
            return
        }

        isRunning = true
        installEventTapIfPossible()

        installLocalMonitorsIfNeeded()

        log.info("Global hotkey monitoring started (\(self.hotkey.label))")
    }

    func stop() {
        guard isRunning else { return }
        isRunning = false
        holdTimer?.cancel()
        holdTimer = nil

        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
            if let source = runLoopSource {
                CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes)
            }
        }
        eventTap = nil
        runLoopSource = nil

        if let m = localFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = localKeyMonitor { NSEvent.removeMonitor(m) }
        localFlagsMonitor = nil
        localKeyMonitor = nil

        log.info("Hotkey monitoring stopped")
    }

    // MARK: - Event Handling

    /// Called from CGEventTap callback (on main thread)
    func handleCGEvent(type: CGEventType, event: CGEvent) {
        if type == .flagsChanged {
            let keyCode = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
            let nsFlags = NSEvent.ModifierFlags(rawValue: UInt(event.flags.rawValue))
            handleFlagsChanged(keyCode: keyCode, flags: nsFlags)
        } else if type == .keyDown {
            if isHotkeyHeld {
                otherKeyPressed = true
            }
        }
    }

    func reenableEventTapIfNeeded() {
        guard let eventTap else { return }
        CGEvent.tapEnable(tap: eventTap, enable: true)
        log.info("CGEventTap re-enabled after system disable")
    }

    func refreshAfterPermissionChange() {
        guard isRunning else { return }
        installEventTapIfPossible()
    }

    private func installEventTapIfPossible() {
        guard eventTap == nil else { return }
        guard Self.hasInputMonitoringPermission else {
            log.warning("Input Monitoring permission missing; global event tap not installed")
            return
        }

        // Create CGEventTap for global monitoring (requires Input Monitoring, not Accessibility)
        let eventMask: CGEventMask = (1 << CGEventType.flagsChanged.rawValue) | (1 << CGEventType.keyDown.rawValue)

        let refcon = Unmanaged.passUnretained(self).toOpaque()
        let tap = CGEvent.tapCreate(
            tap: .cghidEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: eventMask,
            callback: globalEventCallback,
            userInfo: refcon
        )

        guard let tap else {
            log.warning("Failed to create CGEventTap despite Input Monitoring preflight success")
            return
        }

        eventTap = tap
        let source = CFMachPortCreateRunLoopSource(nil, tap, 0)
        runLoopSource = source
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
        log.info("CGEventTap started (\(self.hotkey.label))")
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
        let isTargetKey = isHotkeyEvent(keyCode: keyCode, flags: flags)

        if isTargetKey && !isHotkeyHeld {
            hotkeyDown()
        } else if !isTargetKey && isHotkeyHeld {
            hotkeyUp()
        }
    }

    private func isHotkeyEvent(keyCode: UInt16, flags: NSEvent.ModifierFlags) -> Bool {
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

    private func hotkeyDown() {
        isHotkeyHeld = true
        hotkeyDownTime = Date()
        otherKeyPressed = false

        holdTimer?.cancel()
        let timer = DispatchWorkItem { [weak self] in
            guard let self else { return }
            DispatchQueue.main.async {
                guard self.isHotkeyHeld, !self.otherKeyPressed else { return }
                self.isInPushToTalk = true
                log.info("Push-to-talk started")
                self.onPushToTalkStart?()
            }
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
            } else {
                log.info("Push-to-talk stopped (held \(String(format: "%.2f", holdDuration))s)")
                onPushToTalkStop?()
            }
        } else if !otherKeyPressed && holdDuration < holdThreshold {
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
        } else if otherKeyPressed {
            onCancelled?()
        }

        hotkeyDownTime = nil
        otherKeyPressed = false
    }

    deinit {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }
        if let m = localFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = localKeyMonitor { NSEvent.removeMonitor(m) }
    }
}

// MARK: - CGEventTap Callback (C function)

private func globalEventCallback(
    proxy: CGEventTapProxy,
    type: CGEventType,
    event: CGEvent,
    refcon: UnsafeMutableRawPointer?
) -> Unmanaged<CGEvent>? {
    guard let refcon else { return nil }

    // Handle tap disabled by system (re-enable)
    if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
        let manager = Unmanaged<GlobalHotkeyManager>.fromOpaque(refcon).takeUnretainedValue()
        DispatchQueue.main.async {
            manager.reenableEventTapIfNeeded()
        }
        return Unmanaged.passUnretained(event)
    }

    let manager = Unmanaged<GlobalHotkeyManager>.fromOpaque(refcon).takeUnretainedValue()
    DispatchQueue.main.async {
        manager.handleCGEvent(type: type, event: event)
    }

    return Unmanaged.passUnretained(event)
}
