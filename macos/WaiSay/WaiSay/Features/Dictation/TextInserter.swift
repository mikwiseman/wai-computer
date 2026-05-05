import Cocoa
import os

private let log = Logger(subsystem: "com.waisay.app", category: "textinserter")

enum TextInsertionError: LocalizedError {
    case emptyText
    case clipboardWriteFailed
    case eventPostingPermissionDenied
    case pasteSimulationFailed
    case modifierStuck

    var errorDescription: String? {
        switch self {
        case .emptyText:
            return "No text to insert."
        case .clipboardWriteFailed:
            return "Failed to prepare dictated text for insertion."
        case .eventPostingPermissionDenied:
            return "WaiSay needs permission to paste into other apps. The text is on your clipboard — grant Paste permission in Settings and try again."
        case .pasteSimulationFailed:
            return "Could not paste text. It's been copied to your clipboard — press ⌘V to paste manually."
        case .modifierStuck:
            return "Keyboard modifier keys were still pressed. Text is on the clipboard — press ⌘V to paste."
        }
    }
}

/// Inserts text into the target application via clipboard + simulated Cmd+V.
///
/// Uses `CGEvent.post` with `combinedSessionState` + `cgSessionEventTap`.
/// macOS protects this separately from listen-only Input Monitoring, so missing
/// event-posting permission is reported before we attempt the paste.
///
/// On any failure the text stays on the clipboard so the user can paste
/// manually with ⌘V, and the error surfaces a message that says exactly that.
enum TextInserter {
    static var supportsAutomaticPaste: Bool {
        return true
    }

    static var hasEventPostingPermission: Bool {
        guard supportsAutomaticPaste else { return false }
        return MacInputPermission.hasPostEventAccess
    }

    @discardableResult
    static func requestEventPostingPermission() -> Bool {
        guard supportsAutomaticPaste else { return false }
        return MacInputPermission.requestPostEventAccess()
    }

    static func openEventPostingSettings() {
        MacPrivacySettings.openAccessibility()
    }

    /// Insert `text` into `targetApp`. If `targetApp` is nil, paste goes to the
    /// currently frontmost app.
    ///
    /// Throws `TextInsertionError` on predictable failure modes; the clipboard
    /// still holds the text so the user can ⌘V manually.
    static func insert(_ text: String, targetApp: NSRunningApplication?) async throws {
        guard !text.isEmpty else {
            throw TextInsertionError.emptyText
        }

        let pasteboard = NSPasteboard.general

        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else {
            log.error("Clipboard write failed for \(text.count, privacy: .public)-char payload")
            throw TextInsertionError.clipboardWriteFailed
        }

        // Re-focus the app that had focus when the hotkey was pressed.
        // If activation fails, we still fall through so the user ends up with
        // the text on their clipboard and a clear instruction to paste manually.
        let activated = activateTarget(targetApp)
        if !activated {
            log.warning("Target app activation reported unsuccessful; pasting into frontmost")
        }

        // Give AppKit a beat to apply the activation before posting keystrokes.
        try? await Task.sleep(for: .milliseconds(200))

        // Wait for the hotkey modifiers to release so ⌘V is interpreted as
        // plain ⌘V, not ⌥⌘V / ⇧⌘V / etc.
        if await !waitForModifierRelease() {
            log.warning("Modifier keys still held after 500ms — skipping paste")
            throw TextInsertionError.modifierStuck
        }

        guard supportsAutomaticPaste else {
            log.info("Dictated text copied to clipboard; automatic paste is unavailable in this build")
            return
        }

        try simulatePaste()
        log.info("Dictated text inserted and left on clipboard")
    }

    // MARK: - Private

    /// Re-focus `target`. Returns true if the app is now active (or becomes
    /// active within a short window), false otherwise.
    private static func activateTarget(_ target: NSRunningApplication?) -> Bool {
        guard let target else { return true }
        if target.isActive { return true }

        if #available(macOS 14.0, *) {
            return target.activate()
        } else {
            return target.activate(options: .activateIgnoringOtherApps)
        }
    }

    /// Poll `CGEventSource.flagsState` until no modifier is pressed or 500ms
    /// elapses. Returns true on a clean release, false on timeout.
    private static func waitForModifierRelease() async -> Bool {
        let modifiers: CGEventFlags = [.maskCommand, .maskControl, .maskAlternate, .maskShift]
        for _ in 0..<50 {
            let current = CGEventSource.flagsState(.combinedSessionState)
            if current.intersection(modifiers).isEmpty {
                return true
            }
            try? await Task.sleep(for: .milliseconds(10))
        }
        return false
    }

    /// Post a synthesised ⌘V to the session event tap. Throws on failure so the
    /// caller can surface the manual-paste fallback message.
    private static func simulatePaste() throws {
        guard supportsAutomaticPaste else {
            throw TextInsertionError.eventPostingPermissionDenied
        }

        guard hasEventPostingPermission || requestEventPostingPermission() else {
            log.warning("Event posting permission missing — cannot simulate paste")
            throw TextInsertionError.eventPostingPermissionDenied
        }

        guard let source = CGEventSource(stateID: .combinedSessionState) else {
            throw TextInsertionError.pasteSimulationFailed
        }

        // Suppress local mouse events for the duration of the paste so the user
        // doesn't accidentally redirect focus mid-keystroke.
        source.setLocalEventsFilterDuringSuppressionState(
            [.permitLocalMouseEvents, .permitSystemDefinedEvents],
            state: .eventSuppressionStateSuppressionInterval
        )

        // `V` on US layout. The session event tap remaps this for other layouts.
        let vKey: CGKeyCode = 9
        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: vKey, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: source, virtualKey: vKey, keyDown: false)
        else {
            throw TextInsertionError.pasteSimulationFailed
        }

        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand
        keyDown.post(tap: .cgSessionEventTap)
        keyUp.post(tap: .cgSessionEventTap)
    }
}
