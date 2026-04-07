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
        case .rightOption: return "Right Option (⌥)"
        case .leftOption: return "Left Option (⌥)"
        case .rightCommand: return "Right Command (⌘)"
        case .fn: return "Fn (Globe)"
        case .controlOption: return "Control + Option (⌃⌥)"
        }
    }

    var shortLabel: String {
        switch self {
        case .rightOption: return "⌥ (Right)"
        case .leftOption: return "⌥ (Left)"
        case .rightCommand: return "⌘ (Right)"
        case .fn: return "Fn"
        case .controlOption: return "⌃⌥"
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

/// Monitors global keyboard events to detect dictation hotkey presses.
/// Supports push-to-talk (hold) and hands-free (double-tap toggle).
@MainActor
final class GlobalHotkeyManager: ObservableObject {
    /// Whether the hotkey is currently being held down
    @Published private(set) var isHotkeyHeld = false

    /// Callbacks
    var onPushToTalkStart: (() -> Void)?
    var onPushToTalkStop: (() -> Void)?
    var onHandsFreeToggle: (() -> Void)?
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

    // Event monitors
    private var globalFlagsMonitor: Any?
    private var localFlagsMonitor: Any?
    private var globalKeyMonitor: Any?
    private var localKeyMonitor: Any?

    private var isRunning = false

    func start() {
        guard !isRunning else { return }
        isRunning = true

        // Monitor modifier key changes (global — when our app is NOT focused)
        globalFlagsMonitor = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
            DispatchQueue.main.async { self?.handleFlagsChanged(event) }
        }

        // Monitor modifier key changes (local — when our app IS focused)
        localFlagsMonitor = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
            DispatchQueue.main.async { self?.handleFlagsChanged(event) }
            return event
        }

        // Monitor key presses to detect when hotkey is used as a modifier for other shortcuts
        globalKeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] _ in
            DispatchQueue.main.async {
                guard let self, self.isHotkeyHeld else { return }
                self.otherKeyPressed = true
            }
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

        if let m = globalFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = localFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = globalKeyMonitor { NSEvent.removeMonitor(m) }
        if let m = localKeyMonitor { NSEvent.removeMonitor(m) }
        globalFlagsMonitor = nil
        localFlagsMonitor = nil
        globalKeyMonitor = nil
        localKeyMonitor = nil

        log.info("Global hotkey monitoring stopped")
    }

    // MARK: - Event Handling

    private func handleFlagsChanged(_ event: NSEvent) {
        let isTargetKey = isHotkeyEvent(event)

        if isTargetKey && !isHotkeyHeld {
            // Key pressed
            hotkeyDown()
        } else if !isTargetKey && isHotkeyHeld {
            // Key released
            hotkeyUp()
        }
    }

    private func isHotkeyEvent(_ event: NSEvent) -> Bool {
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)

        switch hotkey {
        case .rightOption:
            return event.keyCode == UInt16(kVK_RightOption) && flags.contains(.option)
        case .leftOption:
            return event.keyCode == UInt16(kVK_Option) && flags.contains(.option)
        case .rightCommand:
            return event.keyCode == UInt16(kVK_RightCommand) && flags.contains(.command)
        case .fn:
            return flags.contains(.function)
        case .controlOption:
            return flags.contains(.control) && flags.contains(.option)
        }
    }

    private func hotkeyDown() {
        isHotkeyHeld = true
        hotkeyDownTime = Date()
        otherKeyPressed = false

        // Start a hold timer — if still held after threshold, it's push-to-talk
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
            // Was in push-to-talk — stop or cancel depending on whether it turned into a modifier.
            isInPushToTalk = false
            if otherKeyPressed {
                log.info("Push-to-talk cancelled after modifier use")
                onCancelled?()
            } else {
                log.info("Push-to-talk stopped (held \(String(format: "%.2f", holdDuration))s)")
                onPushToTalkStop?()
            }
        } else if !otherKeyPressed && holdDuration < holdThreshold {
            // Quick tap — check for double-tap (hands-free toggle)
            if let lastTap = lastTapTime,
               Date().timeIntervalSince(lastTap) < doubleTapInterval {
                lastTapTime = nil
                log.info("Double-tap detected — hands-free toggle")
                onHandsFreeToggle?()
            } else {
                lastTapTime = Date()
            }
        } else if otherKeyPressed {
            // Used as modifier for another shortcut — ignore
            onCancelled?()
        }

        hotkeyDownTime = nil
        otherKeyPressed = false
    }

    deinit {
        if let m = globalFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = localFlagsMonitor { NSEvent.removeMonitor(m) }
        if let m = globalKeyMonitor { NSEvent.removeMonitor(m) }
        if let m = localKeyMonitor { NSEvent.removeMonitor(m) }
    }
}
