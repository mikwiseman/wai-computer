import Cocoa
import Carbon
import os

private let log = Logger(subsystem: "com.waisay.app", category: "textinserter")

enum TextInsertionError: LocalizedError {
    case emptyText
    case accessibilityRequired
    case clipboardWriteFailed
    case pasteSimulationFailed

    var errorDescription: String? {
        switch self {
        case .emptyText:
            return "No text to insert."
        case .accessibilityRequired:
            return "Accessibility permission is required to insert dictated text."
        case .clipboardWriteFailed:
            return "Failed to prepare dictated text for insertion."
        case .pasteSimulationFailed:
            return "Failed to insert dictated text into the active app."
        }
    }
}

/// Inserts text into the currently focused application by copying to clipboard
/// and simulating Cmd+V. Preserves the user's original clipboard contents.
enum TextInserter {

    // MARK: - Public

    /// Check if accessibility access is granted (required for CGEvent posting)
    static var hasAccessibilityPermission: Bool {
        AXIsProcessTrusted()
    }

    /// Request accessibility permission by opening System Settings.
    /// `AXIsProcessTrustedWithOptions` with the prompt flag no longer shows
    /// a meaningful dialog on modern macOS — open Settings directly instead.
    static func requestAccessibilityPermission() {
        // Trigger the system prompt first (adds the app to the list if not there yet)
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        AXIsProcessTrustedWithOptions(options)

        // Then open System Settings > Privacy > Accessibility so the user can toggle it on
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }

    /// Insert text into the currently active application.
    /// Saves clipboard, copies text, simulates Cmd+V, then restores clipboard.
    static func insert(_ text: String) async throws {
        guard !text.isEmpty else {
            log.warning("Attempted to insert empty text")
            throw TextInsertionError.emptyText
        }

        guard hasAccessibilityPermission else {
            log.error("Accessibility permission not granted — cannot insert text")
            requestAccessibilityPermission()
            throw TextInsertionError.accessibilityRequired
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

        // Simulate Cmd+V
        try simulatePaste()

        // Wait for paste to complete, then restore clipboard
        try? await Task.sleep(for: .milliseconds(200))
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
