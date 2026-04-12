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

/// Inserts text into the currently focused application by copying to clipboard
/// and simulating Cmd+V. Uses CGEvent.post (hidSystemState) with AppleScript fallback.
enum TextInserter {

    // MARK: - Permission Checks

    /// Check if PostEvent permission is granted (for CGEvent.post)
    static var hasPostEventPermission: Bool {
        CGPreflightPostEventAccess()
    }

    /// Request PostEvent permission — triggers system TCC prompt
    static func requestPostEventPermission() {
        CGRequestPostEventAccess()
    }

    // MARK: - Insert

    /// Insert text into the currently active application.
    static func insert(_ text: String) async throws {
        guard !text.isEmpty else {
            throw TextInsertionError.emptyText
        }

        NSLog("[TextInserter] Inserting %d chars. PostEvent=%d", text.count, hasPostEventPermission ? 1 : 0)

        // Save current clipboard
        let pasteboard = NSPasteboard.general
        let snapshot = saveClipboard(pasteboard)

        // Set our text on the clipboard
        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else {
            throw TextInsertionError.clipboardWriteFailed
        }
        let insertedChangeCount = pasteboard.changeCount

        // Wait for hotkey modifiers to fully release
        await waitForModifierRelease()

        // Try paste methods
        var pasted = false

        // Method 1: CGEvent.post — only if PostEvent TCC is granted
        if hasPostEventPermission {
            NSLog("[TextInserter] Trying CGEvent.post (hidSystemState)...")
            pasted = simulatePasteCGEvent()
            NSLog("[TextInserter] CGEvent.post done")
        }

        // Method 2: AppleScript System Events — fallback
        if !pasted {
            NSLog("[TextInserter] Trying AppleScript fallback...")
            pasted = simulatePasteAppleScript()
            NSLog("[TextInserter] AppleScript result: %d", pasted ? 1 : 0)
        }

        if !pasted {
            NSLog("[TextInserter] ALL paste methods failed — text on clipboard")
            // Don't restore clipboard — user can manually ⌘V
            throw TextInsertionError.pasteSimulationFailed
        }

        // Wait for target app to process the paste
        try? await Task.sleep(for: .milliseconds(300))

        // Restore original clipboard
        restoreClipboard(pasteboard, snapshot: snapshot, insertedChangeCount: insertedChangeCount)

        NSLog("[TextInserter] Success")
    }

    // MARK: - Modifier Release

    /// Poll until all modifier keys are released (max 500ms).
    /// Prevents hotkey modifier (e.g. Right Command) from contaminating Cmd+V.
    private static func waitForModifierRelease() async {
        let modifierMask: CGEventFlags = [.maskCommand, .maskControl, .maskAlternate, .maskShift]

        for _ in 0..<50 { // 50 × 10ms = 500ms max
            let currentFlags = CGEventSource.flagsState(.hidSystemState)
            if currentFlags.intersection(modifierMask).isEmpty {
                NSLog("[TextInserter] Modifiers released")
                return
            }
            try? await Task.sleep(for: .milliseconds(10))
        }
        NSLog("[TextInserter] Modifier release timeout — proceeding anyway")
    }

    // MARK: - Paste Methods

    /// CGEvent.post with hidSystemState — used by Wispr Flow, Raycast, TextExpander
    private static func simulatePasteCGEvent() -> Bool {
        let source = CGEventSource(stateID: .hidSystemState)
        let vKeyCode: CGKeyCode = 9 // 'V' key

        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: false)
        else {
            NSLog("[TextInserter] Failed to create CGEvent")
            return false
        }

        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand

        keyDown.post(tap: .cghidEventTap)
        keyUp.post(tap: .cghidEventTap)
        return true
    }

    /// AppleScript System Events keystroke — fallback when CGEvent.post is not available
    private static func simulatePasteAppleScript() -> Bool {
        let script = NSAppleScript(source: """
            tell application "System Events"
                keystroke "v" using command down
            end tell
            """)

        var errorInfo: NSDictionary?
        script?.executeAndReturnError(&errorInfo)

        if let errorInfo {
            let message = errorInfo[NSAppleScript.errorMessage] as? String ?? "Unknown"
            NSLog("[TextInserter] AppleScript error: %@", message)
            return false
        }
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
