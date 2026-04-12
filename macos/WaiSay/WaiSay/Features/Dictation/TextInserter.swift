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

/// Inserts text into the currently focused application using AppleScript System Events.
///
/// In a sandboxed app (required for TestFlight), CGEvent.post() silently fails
/// because PostEvent TCC cannot be granted. AppleScript with automation.apple-events
/// entitlement is the only reliable method for sandbox.
enum TextInserter {

    /// Insert text into the currently active application.
    static func insert(_ text: String) async throws {
        guard !text.isEmpty else {
            throw TextInsertionError.emptyText
        }

        NSLog("[TextInserter] Inserting %d chars", text.count)

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

        // Paste via AppleScript System Events — the only method that works in sandbox
        NSLog("[TextInserter] Pasting via AppleScript...")
        let success = simulatePasteAppleScript()
        NSLog("[TextInserter] AppleScript result: %d", success ? 1 : 0)

        if !success {
            NSLog("[TextInserter] Paste failed — text left on clipboard")
            // Don't restore clipboard so user can ⌘V manually
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
    private static func waitForModifierRelease() async {
        let modifierMask: CGEventFlags = [.maskCommand, .maskControl, .maskAlternate, .maskShift]

        for _ in 0..<50 {
            let currentFlags = CGEventSource.flagsState(.hidSystemState)
            if currentFlags.intersection(modifierMask).isEmpty {
                NSLog("[TextInserter] Modifiers released")
                return
            }
            try? await Task.sleep(for: .milliseconds(10))
        }
        NSLog("[TextInserter] Modifier release timeout — proceeding anyway")
    }

    // MARK: - Paste via AppleScript

    /// Uses System Events to simulate Cmd+V. Requires:
    /// - Entitlement: com.apple.security.automation.apple-events
    /// - Info.plist: NSAppleEventsUsageDescription
    /// macOS auto-prompts "WaiSay wants to control System Events" on first use.
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
