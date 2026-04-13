import Cocoa
import os

private let log = Logger(subsystem: "com.waisay.app", category: "textinserter")

enum TextInsertionError: LocalizedError {
    case emptyText
    case clipboardWriteFailed
    case pasteSimulationFailed

    var errorDescription: String? {
        switch self {
        case .emptyText:
            return "No text to insert."
        case .clipboardWriteFailed:
            return "Failed to prepare dictated text for insertion."
        case .pasteSimulationFailed:
            return "Could not paste text. It's been copied to your clipboard — press ⌘V to paste manually."
        }
    }
}

/// Inserts text into the currently focused application.
/// Uses two approaches in cascade:
/// 1. CGEvent.post (Maccy approach — proven in sandboxed App Store apps)
/// 2. AppleScript System Events (fallback)
enum TextInserter {

    // MARK: - Pre-authorize

    /// Call once (e.g. from Settings) to trigger the System Events consent prompt
    /// before the user starts dictating. This avoids a surprise prompt mid-dictation.
    static func preAuthorizeSystemEvents() {
        let script = NSAppleScript(source: """
            tell application "System Events"
                return name of first process whose frontmost is true
            end tell
            """)
        var errorInfo: NSDictionary?
        script?.executeAndReturnError(&errorInfo)
        // We don't care about the result — just need to trigger the TCC prompt
    }

    // MARK: - Insert

    /// Insert text into the target application.
    /// `targetApp` should be the app that was frontmost when dictation started.
    static func insert(_ text: String, targetApp: NSRunningApplication?) async throws {
        guard !text.isEmpty else {
            throw TextInsertionError.emptyText
        }

        NSLog("[TextInserter] Inserting %d chars into %@", text.count, targetApp?.localizedName ?? "unknown")

        // Save current clipboard
        let pasteboard = NSPasteboard.general
        let snapshot = saveClipboard(pasteboard)

        // Set our text on the clipboard
        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else {
            throw TextInsertionError.clipboardWriteFailed
        }
        let insertedChangeCount = pasteboard.changeCount

        // Activate target app and wait for focus to settle
        if let target = targetApp {
            NSLog("[TextInserter] Activating %@", target.localizedName ?? "?")
            target.activate()
            try? await Task.sleep(for: .milliseconds(300))
        }

        // Wait for hotkey modifiers to fully release
        await waitForModifierRelease()

        // Method 1: CGEvent.post — Maccy approach (combinedSessionState + cgSessionEventTap)
        NSLog("[TextInserter] Trying CGEvent.post (Maccy approach)...")
        var pasted = simulatePasteCGEvent()

        // Method 2: AppleScript fallback
        if !pasted {
            NSLog("[TextInserter] CGEvent failed, trying AppleScript...")
            pasted = simulatePasteAppleScript()
        }

        NSLog("[TextInserter] Paste result: %d", pasted ? 1 : 0)

        if !pasted {
            // Leave text on clipboard for manual ⌘V
            throw TextInsertionError.pasteSimulationFailed
        }

        // Wait for target app to process the paste
        try? await Task.sleep(for: .milliseconds(300))

        // Restore original clipboard
        restoreClipboard(pasteboard, snapshot: snapshot, insertedChangeCount: insertedChangeCount)
    }

    // MARK: - Modifier Release

    /// Poll until all modifier keys are released (max 500ms).
    private static func waitForModifierRelease() async {
        let modifierMask: CGEventFlags = [.maskCommand, .maskControl, .maskAlternate, .maskShift]
        for _ in 0..<50 {
            let flags = CGEventSource.flagsState(.combinedSessionState)
            if flags.intersection(modifierMask).isEmpty {
                NSLog("[TextInserter] Modifiers clear")
                return
            }
            try? await Task.sleep(for: .milliseconds(10))
        }
        NSLog("[TextInserter] Modifier timeout — proceeding")
    }

    // MARK: - Paste Methods

    /// Maccy approach — proven in sandboxed Mac App Store apps.
    /// Uses .combinedSessionState + .cgSessionEventTap (NOT .hidSystemState + .cghidEventTap)
    private static func simulatePasteCGEvent() -> Bool {
        let source = CGEventSource(stateID: .combinedSessionState)

        // Suppress local events during paste to avoid interference
        source?.setLocalEventsFilterDuringSuppressionState(
            [.permitLocalMouseEvents, .permitSystemDefinedEvents],
            state: .eventSuppressionStateSuppressionInterval
        )

        let vKeyCode: CGKeyCode = 9 // 'V' key

        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: false)
        else {
            NSLog("[TextInserter] CGEvent creation failed")
            return false
        }

        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand

        keyDown.post(tap: .cgSessionEventTap)
        keyUp.post(tap: .cgSessionEventTap)

        NSLog("[TextInserter] CGEvent.post done (session tap)")
        return true
    }

    /// AppleScript fallback — uses System Events keystroke
    private static func simulatePasteAppleScript() -> Bool {
        let script = NSAppleScript(source: """
            tell application "System Events"
                keystroke "v" using command down
            end tell
            """)

        var errorInfo: NSDictionary?
        script?.executeAndReturnError(&errorInfo)

        if let errorInfo {
            let msg = errorInfo[NSAppleScript.errorMessage] as? String ?? "Unknown"
            NSLog("[TextInserter] AppleScript error: %@", msg)
            return false
        }
        NSLog("[TextInserter] AppleScript paste done")
        return true
    }

    // MARK: - Clipboard Save/Restore

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
