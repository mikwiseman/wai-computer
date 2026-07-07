import AppKit
import ApplicationServices
import Foundation
import WaiComputerKit

enum DictationContextCollector {
    private static let contextAroundLimit = 800
    private static let selectedTextLimit = 2_000

    static func collect(
        targetApp: NSRunningApplication?,
        includeTextbox: Bool
    ) -> DictationCleanupContext? {
        let app = targetApp.map { app in
            DictationCleanupAppContext(
                name: cleaned(app.localizedName, limit: 120),
                bundleID: cleaned(app.bundleIdentifier, limit: 200),
                category: appCategory(
                    bundleID: app.bundleIdentifier,
                    name: app.localizedName
                )
            )
        }

        let textbox = includeTextbox
            ? focusedTextboxContext(targetApp: targetApp)
            : nil

        guard app != nil || textbox != nil else { return nil }
        return DictationCleanupContext(app: app, textbox: textbox)
    }

    static func appCategory(bundleID: String?, name: String?) -> String {
        let bundle = (bundleID ?? "").lowercased()
        let appName = (name ?? "").lowercased()

        if bundle.contains("com.apple.mail")
            || bundle.contains("com.microsoft.outlook")
            || appName.contains("superhuman") {
            return "email"
        }

        if bundle.contains("slack")
            || bundle.contains("telegram")
            || bundle.contains("discord")
            || bundle.contains("messages")
            || bundle.contains("whatsapp")
            || appName.contains("slack")
            || appName.contains("telegram")
            || appName.contains("discord")
            || appName.contains("messages")
            || appName.contains("whatsapp") {
            return "chat"
        }

        if appName == "x"
            || appName.contains("twitter")
            || appName.contains("linkedin")
            || appName.contains("instagram")
            || appName.contains("facebook")
            || appName.contains("threads") {
            return "social"
        }

        if bundle.contains("chatgpt")
            || bundle.contains("claude")
            || bundle.contains("perplexity")
            || appName.contains("chatgpt")
            || appName.contains("claude")
            || appName.contains("gemini")
            || appName.contains("perplexity") {
            return "ai"
        }

        if bundle.contains("xcode")
            || bundle.contains("jetbrains")
            || bundle.contains("vscode")
            || bundle.contains("cursor")
            || bundle.contains("terminal")
            || bundle.contains("iterm")
            || bundle.contains("warp")
            || bundle.contains("github")
            || appName.contains("xcode")
            || appName.contains("cursor")
            || appName.contains("visual studio code")
            || appName.contains("terminal")
            || appName.contains("iterm")
            || appName.contains("warp")
            || appName.contains("github desktop") {
            return "engineering"
        }

        if bundle.contains("linear")
            || bundle.contains("jira")
            || bundle.contains("trello")
            || bundle.contains("asana")
            || bundle.contains("clickup")
            || appName.contains("linear")
            || appName.contains("jira")
            || appName.contains("trello")
            || appName.contains("asana")
            || appName.contains("clickup")
            || appName.contains("monday") {
            return "project_management"
        }

        if bundle.contains("notes")
            || bundle.contains("textedit")
            || bundle.contains("notion")
            || bundle.contains("obsidian")
            || appName.contains("notes")
            || appName.contains("textedit")
            || appName.contains("notion")
            || appName.contains("obsidian")
            || appName.contains("bear")
            || appName.contains("craft") {
            return "writing"
        }

        if bundle.contains("safari")
            || bundle.contains("chrome")
            || bundle.contains("firefox")
            || bundle.contains("brave")
            || bundle.contains("microsoft.edgemac")
            || appName.contains("safari")
            || appName.contains("chrome")
            || appName.contains("firefox")
            || appName.contains("brave")
            || appName.contains("arc")
            || appName.contains("edge") {
            return "browser"
        }

        return "other"
    }

    private static func focusedTextboxContext(
        targetApp: NSRunningApplication?
    ) -> DictationCleanupTextboxContext? {
        guard MacInputPermission.hasAccessibilityAccess else { return nil }
        let systemWide = AXUIElementCreateSystemWide()
        // Bound the synchronous AX round-trip: this runs on the dictation
        // start path (@MainActor), and a busy target app's AX server can
        // otherwise block the hotkey for seconds (the default AX messaging
        // timeout). Mirrors DictationEditWatcher's 0.5 s bound.
        AXUIElementSetMessagingTimeout(systemWide, 0.5)
        guard let focusedValue = copyAttribute(
            systemWide,
            kAXFocusedUIElementAttribute
        ) else { return nil }
        guard CFGetTypeID(focusedValue) == AXUIElementGetTypeID() else { return nil }
        let element = focusedValue as! AXUIElement

        if let targetApp, !focusedElement(element, belongsTo: targetApp) {
            return nil
        }

        let value = stringAttribute(element, kAXValueAttribute)
        let selectedText = stringAttribute(element, kAXSelectedTextAttribute)
        let selectedRange = rangeAttribute(element, kAXSelectedTextRangeAttribute)

        if let value, let selectedRange {
            return textboxContext(
                fullText: value,
                selectedText: selectedText,
                selectedRange: selectedRange
            )
        }

        guard value != nil || selectedText != nil else { return nil }
        return DictationCleanupTextboxContext(
            beforeText: cleaned(value, limit: contextAroundLimit, fromEnd: true),
            selectedText: cleaned(selectedText, limit: selectedTextLimit),
            afterText: nil
        )
    }

    private static func textboxContext(
        fullText: String,
        selectedText: String?,
        selectedRange: CFRange
    ) -> DictationCleanupTextboxContext? {
        let nsText = fullText as NSString
        guard nsText.length > 0 else {
            return DictationCleanupTextboxContext(
                beforeText: nil,
                selectedText: cleaned(selectedText, limit: selectedTextLimit),
                afterText: nil
            )
        }

        let location = max(0, min(selectedRange.location, nsText.length))
        let length = max(0, min(selectedRange.length, nsText.length - location))
        let end = location + length
        let rangeSelectedText = length > 0
            ? nsText.substring(with: NSRange(location: location, length: length))
            : nil

        let before = nsText.substring(to: location)
        let after = nsText.substring(from: end)
        return DictationCleanupTextboxContext(
            beforeText: cleaned(before, limit: contextAroundLimit, fromEnd: true),
            selectedText: cleaned(selectedText ?? rangeSelectedText, limit: selectedTextLimit),
            afterText: cleaned(after, limit: contextAroundLimit)
        )
    }

    private static func focusedElement(
        _ element: AXUIElement,
        belongsTo targetApp: NSRunningApplication
    ) -> Bool {
        var pid: pid_t = 0
        guard AXUIElementGetPid(element, &pid) == .success else { return false }
        return pid == targetApp.processIdentifier
    }

    private static func copyAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> CFTypeRef? {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        guard result == .success else { return nil }
        return value
    }

    private static func stringAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> String? {
        copyAttribute(element, attribute) as? String
    }

    private static func rangeAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> CFRange? {
        guard let rawValue = copyAttribute(element, attribute) else { return nil }
        guard CFGetTypeID(rawValue) == AXValueGetTypeID() else { return nil }
        let value = rawValue as! AXValue
        guard AXValueGetType(value) == .cfRange else { return nil }
        var range = CFRange()
        guard AXValueGetValue(value, .cfRange, &range) else { return nil }
        guard range.location >= 0, range.length >= 0 else { return nil }
        return range
    }

    private static func cleaned(
        _ value: String?,
        limit: Int,
        fromEnd: Bool = false
    ) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        guard trimmed.count > limit else { return trimmed }
        if fromEnd {
            return String(trimmed.suffix(limit))
        }
        return String(trimmed.prefix(limit))
    }
}
