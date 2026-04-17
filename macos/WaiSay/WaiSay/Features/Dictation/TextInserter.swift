import Cocoa
import os

private let log = Logger(subsystem: "com.waisay.app", category: "textinserter")

enum TextInsertionError: LocalizedError {
    case emptyText
    case clipboardWriteFailed
    case pasteSimulationFailed
    case modifierStuck

    var errorDescription: String? {
        switch self {
        case .emptyText:
            return "No text to insert."
        case .clipboardWriteFailed:
            return "Failed to prepare dictated text for insertion."
        case .pasteSimulationFailed:
            return "Could not paste text. It's been copied to your clipboard — press ⌘V to paste manually."
        case .modifierStuck:
            return "Keyboard modifier keys were still pressed. Text is on the clipboard — press ⌘V to paste."
        }
    }
}

/// Inserts text into the target application via clipboard + simulated Cmd+V.
///
/// Uses `CGEvent.post` with `combinedSessionState` + `cgSessionEventTap` — the
/// same approach as Maccy (a sandboxed Mac App Store clipboard manager). This
/// avoids `AppleScript`/`System Events`, which the App Sandbox blocks without a
/// `scripting-targets` entitlement for `com.apple.systemevents`.
///
/// On any failure the text stays on the clipboard so the user can paste
/// manually with ⌘V, and the error surfaces a message that says exactly that.
enum TextInserter {

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
        let snapshot = saveClipboard(pasteboard)

        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else {
            log.error("Clipboard write failed for \(text.count, privacy: .public)-char payload")
            throw TextInsertionError.clipboardWriteFailed
        }
        let insertedChangeCount = pasteboard.changeCount

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

        do {
            try simulatePaste()
        } catch {
            log.error("Paste simulation failed")
            throw TextInsertionError.pasteSimulationFailed
        }

        // Wait for the destination app to consume the paste, then restore the
        // prior clipboard contents if we still own the pasteboard.
        try? await Task.sleep(for: .milliseconds(300))
        restoreClipboard(pasteboard, snapshot: snapshot, insertedChangeCount: insertedChangeCount)
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

    // MARK: - Clipboard snapshot & restore

    private struct ClipboardItem {
        let type: NSPasteboard.PasteboardType
        let data: Data
    }

    private struct ClipboardSnapshot {
        let items: [ClipboardItem]
        let wasEmpty: Bool
    }

    private static func saveClipboard(_ pasteboard: NSPasteboard) -> ClipboardSnapshot {
        var items: [ClipboardItem] = []
        guard let types = pasteboard.types else {
            return ClipboardSnapshot(items: [], wasEmpty: true)
        }
        for type in types {
            if let data = pasteboard.data(forType: type) {
                items.append(ClipboardItem(type: type, data: data))
            }
        }
        return ClipboardSnapshot(items: items, wasEmpty: items.isEmpty)
    }

    /// Restore the previous clipboard contents only if nothing else wrote to
    /// the pasteboard in the meantime. If someone else (e.g. a clipboard
    /// manager) captured our dictated text, leave it alone.
    private static func restoreClipboard(
        _ pasteboard: NSPasteboard,
        snapshot: ClipboardSnapshot,
        insertedChangeCount: Int
    ) {
        guard pasteboard.changeCount == insertedChangeCount else { return }
        pasteboard.clearContents()
        guard !snapshot.wasEmpty else { return }
        for item in snapshot.items {
            pasteboard.setData(item.data, forType: item.type)
        }
    }
}
