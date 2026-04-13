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

/// Inserts text into the target application via clipboard + simulated Cmd+V.
/// Uses CGEvent.post with combinedSessionState + cgSessionEventTap —
/// the same approach as Maccy (sandboxed Mac App Store clipboard manager).
enum TextInserter {

    /// Insert text into the target application.
    static func insert(_ text: String, targetApp: NSRunningApplication?) async throws {
        guard !text.isEmpty else {
            throw TextInsertionError.emptyText
        }

        // Save current clipboard
        let pasteboard = NSPasteboard.general
        let snapshot = saveClipboard(pasteboard)

        // Set our text on the clipboard
        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else {
            throw TextInsertionError.clipboardWriteFailed
        }
        let insertedChangeCount = pasteboard.changeCount

        // Activate target app
        if let target = targetApp {
            target.activate()
            try? await Task.sleep(for: .milliseconds(200))
        }

        // Wait for hotkey modifiers to release
        await waitForModifierRelease()

        // Simulate Cmd+V
        simulatePaste()

        // Wait for paste to process, then restore clipboard
        try? await Task.sleep(for: .milliseconds(300))
        restoreClipboard(pasteboard, snapshot: snapshot, insertedChangeCount: insertedChangeCount)
    }

    // MARK: - Private

    private static func waitForModifierRelease() async {
        let modifiers: CGEventFlags = [.maskCommand, .maskControl, .maskAlternate, .maskShift]
        for _ in 0..<50 {
            if CGEventSource.flagsState(.combinedSessionState).intersection(modifiers).isEmpty {
                return
            }
            try? await Task.sleep(for: .milliseconds(10))
        }
    }

    private static func simulatePaste() {
        let source = CGEventSource(stateID: .combinedSessionState)
        source?.setLocalEventsFilterDuringSuppressionState(
            [.permitLocalMouseEvents, .permitSystemDefinedEvents],
            state: .eventSuppressionStateSuppressionInterval
        )

        let vKey: CGKeyCode = 9
        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: vKey, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: source, virtualKey: vKey, keyDown: false)
        else { return }

        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand
        keyDown.post(tap: .cgSessionEventTap)
        keyUp.post(tap: .cgSessionEventTap)
    }

    // MARK: - Clipboard

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
