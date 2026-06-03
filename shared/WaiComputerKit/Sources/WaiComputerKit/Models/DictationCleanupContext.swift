import Foundation

public struct DictationCleanupContext: Encodable, Sendable {
    public let app: DictationCleanupAppContext?
    public let textbox: DictationCleanupTextboxContext?

    public init(
        app: DictationCleanupAppContext? = nil,
        textbox: DictationCleanupTextboxContext? = nil
    ) {
        self.app = app
        self.textbox = textbox
    }
}

public struct DictationCleanupAppContext: Encodable, Sendable {
    public let name: String?
    public let bundleID: String?
    public let category: String?

    public init(
        name: String? = nil,
        bundleID: String? = nil,
        category: String? = nil
    ) {
        self.name = name
        self.bundleID = bundleID
        self.category = category
    }

    private enum CodingKeys: String, CodingKey {
        case name
        case bundleID = "bundle_id"
        case category
    }
}

public struct DictationCleanupTextboxContext: Encodable, Sendable {
    public let beforeText: String?
    public let selectedText: String?
    public let afterText: String?

    public init(
        beforeText: String? = nil,
        selectedText: String? = nil,
        afterText: String? = nil
    ) {
        self.beforeText = beforeText
        self.selectedText = selectedText
        self.afterText = afterText
    }

    private enum CodingKeys: String, CodingKey {
        case beforeText = "before_text"
        case selectedText = "selected_text"
        case afterText = "after_text"
    }
}
