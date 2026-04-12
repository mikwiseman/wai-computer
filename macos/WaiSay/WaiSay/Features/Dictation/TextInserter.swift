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
/// and simulating Cmd+V via CGEvent.post().
///
/// CGEvent.post() works in sandboxed apps with a limited "PostEvent" TCC privilege
/// (shown as Accessibility in System Settings). The system auto-prompts when needed.
/// This is the same approach used by Wispr Flow, Raycast, and TextExpander.
enum TextInserter {

    /// Insert text into the currently active application.
    /// Saves clipboard, copies text, simulates Cmd+V, then restores clipboard.
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

        // Simulate Cmd+V via CGEvent.post (works in sandbox with PostEvent privilege)
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
        let source = CGEventSource(stateID: .hidSystemState)

        // Key code for 'V' is 9
        let vKeyCode: CGKeyCode = 9

        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: false)
        else {
            log.error("Failed to create CGEvent for paste simulation")
            throw TextInsertionError.pasteSimulationFailed
        }

        // Clear all modifier flags first, then set only Command
        // This prevents conflicts with the dictation hotkey modifier keys
        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand

        keyDown.post(tap: .cghidEventTap)
        keyUp.post(tap: .cghidEventTap)
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
