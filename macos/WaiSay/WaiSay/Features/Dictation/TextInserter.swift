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
            return "Failed to insert dictated text into the active app."
        }
    }
}

/// Inserts text into the currently focused application by copying to clipboard
/// and simulating Cmd+V via AppleScript (System Events).
///
/// Uses Automation permission (com.apple.security.automation.apple-events) which
/// works in sandboxed apps and triggers a one-time system prompt automatically.
/// No manual Accessibility setup required.
enum TextInserter {

    /// Insert text into the currently active application.
    /// Saves clipboard, copies text, simulates Cmd+V via AppleScript, then restores clipboard.
    static func insert(_ text: String) async throws {
        guard !text.isEmpty else {
            log.warning("Attempted to insert empty text")
            throw TextInsertionError.emptyText
        }

        log.info("Inserting \(text.count) characters into active app")

        // Save current clipboard
        let pasteboard = NSPasteboard.general
        let snapshot = saveClipboard(pasteboard)

        // Set our text on the clipboard
        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else {
            throw TextInsertionError.clipboardWriteFailed
        }
        let insertedChangeCount = pasteboard.changeCount

        // Small delay to ensure clipboard is ready
        try? await Task.sleep(for: .milliseconds(50))

        // Simulate Cmd+V via AppleScript (Automation permission — auto-prompted in sandbox)
        try simulatePaste()

        // Wait for paste to complete, then restore clipboard
        try? await Task.sleep(for: .milliseconds(300))
        restoreClipboard(
            pasteboard,
            snapshot: snapshot,
            insertedChangeCount: insertedChangeCount
        )

        log.info("Text inserted successfully")
    }

    // MARK: - Private

    private static func simulatePaste() throws {
        let script = NSAppleScript(source: """
            tell application "System Events"
                keystroke "v" using command down
            end tell
            """)

        var errorInfo: NSDictionary?
        script?.executeAndReturnError(&errorInfo)

        if let errorInfo {
            let message = errorInfo[NSAppleScript.errorMessage] as? String ?? "Unknown error"
            log.error("AppleScript paste failed: \(message)")
            throw TextInsertionError.pasteSimulationFailed
        }
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
        guard pasteboard.changeCount == insertedChangeCount else {
            log.info("Skipping clipboard restore because clipboard changed after dictation paste")
            return
        }

        pasteboard.clearContents()
        guard !snapshot.wasEmpty else { return }

        for item in snapshot.items {
            pasteboard.setData(item.data, forType: item.type)
        }
    }
}
