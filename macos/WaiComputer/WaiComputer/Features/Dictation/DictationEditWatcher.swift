import AppKit
import ApplicationServices
import WaiComputerKit
import os

/// Watches the text field we pasted dictation into and, once the user settles,
/// diffs what we wrote against what they kept — feeding repeated corrections to
/// the `DictionaryLearningEngine`. This is the Wispr Flow / Typeless mechanism:
/// "monitor the text box where it pastes text to detect edits."
///
/// Reuses the Accessibility trust the app already holds for paste insertion, so
/// no new permission. Privacy: it skips native secure text fields
/// (NSSecureTextField); web/Electron password fields aren't always AX-flagged as
/// secure, but the watcher only arms after WE paste dictated text in dictation
/// mode and the read value never leaves on-device diffing. It never persists the
/// field's surrounding text — only the engine's extracted token pairs survive —
/// and is gated by a Settings toggle.
@MainActor
final class DictationEditWatcher {
    private let log = Logger(subsystem: "is.waiwai.computer.app", category: "dictation-edit-watcher")
    private let engine: DictionaryLearningEngine

    /// UserDefaults key for the Settings toggle (default ON when unset).
    static let enabledDefaultsKey = "dictationLearnFromEdits"

    /// Master gate (Settings → "Suggest dictionary words from my edits").
    var isEnabled: Bool {
        UserDefaults.standard.object(forKey: Self.enabledDefaultsKey) as? Bool ?? true
    }

    /// Seconds to wait after a paste before reading the field back. The read is
    /// also forced early when the next dictation starts or focus leaves the app.
    private let settleDelay: Duration = .seconds(8)
    /// Don't attribute edits inside very large documents — too ambiguous, and we
    /// shouldn't pull big text blobs into memory.
    private let maxFieldLength = 20_000

    private struct PendingCapture {
        let element: AXUIElement
        let produced: String
        let snapshot: String
        let language: String?
    }

    private var pending: PendingCapture?
    private var settleTask: Task<Void, Never>?
    private var workspaceObserver: NSObjectProtocol?

    init(engine: DictionaryLearningEngine) {
        self.engine = engine
        observeAppSwitches()
    }

    deinit {
        if let workspaceObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(workspaceObserver)
        }
    }

    /// Call right after a successful paste with the text we inserted. Snapshots
    /// the focused field and schedules a settle read.
    func noteInsertion(produced: String, language: String?) {
        guard isEnabled else { return }
        let trimmed = produced.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard AXIsProcessTrusted() else { return }
        guard let element = focusedElement() else { return }
        guard !isSecureField(element) else {
            log.debug("Skipping edit capture: focused field is secure")
            return
        }
        guard let value = stringValue(of: element), value.count <= maxFieldLength else { return }

        pending = PendingCapture(element: element, produced: trimmed, snapshot: value, language: language)
        scheduleSettle()
    }

    /// Force the pending settle read now (next dictation starting, app switch).
    func flush() {
        performSettle()
    }

    // MARK: - Settle

    private func scheduleSettle() {
        settleTask?.cancel()
        let delay = settleDelay
        settleTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            self?.performSettle()
        }
    }

    private func performSettle() {
        settleTask?.cancel()
        settleTask = nil
        guard let capture = pending else { return }
        pending = nil

        guard let current = stringValue(of: capture.element), current.count <= maxFieldLength else { return }
        // Nothing changed since the paste ⇒ nothing to learn.
        guard current != capture.snapshot else { return }

        engine.observeEdit(produced: capture.produced, edited: current, language: capture.language)
    }

    // MARK: - Accessibility

    private func focusedElement() -> AXUIElement? {
        let system = AXUIElementCreateSystemWide()
        // Bound AX messaging so a slow/unresponsive app can't hang the main thread.
        AXUIElementSetMessagingTimeout(system, 0.5)
        var ref: CFTypeRef?
        let err = AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &ref)
        guard err == .success, let ref, CFGetTypeID(ref) == AXUIElementGetTypeID() else { return nil }
        return (ref as! AXUIElement)
    }

    private func stringValue(of element: AXUIElement) -> String? {
        var ref: CFTypeRef?
        let err = AXUIElementCopyAttributeValue(element, kAXValueAttribute as CFString, &ref)
        guard err == .success, let value = ref as? String else { return nil }
        return value
    }

    private func isSecureField(_ element: AXUIElement) -> Bool {
        var roleRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleRef) == .success,
           let role = roleRef as? String, role == "AXSecureTextField" {
            return true
        }
        var subroleRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXSubroleAttribute as CFString, &subroleRef) == .success,
           let subrole = subroleRef as? String, subrole == (kAXSecureTextFieldSubrole as String) {
            return true
        }
        return false
    }

    // MARK: - App-switch settle

    private func observeAppSwitches() {
        workspaceObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            // Focus moved to another app — the edit is likely done.
            Task { @MainActor in self?.performSettle() }
        }
    }
}
