import Cocoa
import Carbon
import os

private let log = Logger(subsystem: "com.waisay.app", category: "hotkey")

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
/// is running in the background. The App Store build still delivers dictated
/// text via the clipboard only; simulated paste remains direct-distribution only.
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
        CGPreflightListenEventAccess()
    }

    /// Request Input Monitoring permission — shows the system prompt
    static func requestInputMonitoringPermission() {
        CGRequestListenEventAccess()
    }

    func start() {
        guard !isRunning else { return }
        isRunning = true

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

        if let tap {
            eventTap = tap
            let source = CFMachPortCreateRunLoopSource(nil, tap, 0)
            runLoopSource = source
            CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
            CGEvent.tapEnable(tap: tap, enable: true)
            log.info("CGEventTap started (\(self.hotkey.label))")
        } else {
            log.warning("Failed to create CGEventTap — Input Monitoring permission may be missing")
        }

        localFlagsMonitor = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
            DispatchQueue.main.async { self?.handleFlagsChanged(keyCode: event.keyCode, flags: event.modifierFlags) }
            return event
        }
        localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            DispatchQueue.main.async {
                guard let self, self.isHotkeyHeld else { return }
                self.otherKeyPressed = true
            }
            return event
        }

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

    return nil // listenOnly — return nil
}
