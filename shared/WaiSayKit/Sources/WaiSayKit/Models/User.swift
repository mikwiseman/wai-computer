import Foundation

/// User model
public struct User: Codable, Identifiable, Sendable {
    public let id: String
    public let email: String
    public let createdAt: Date
    public let hasPassword: Bool

    public init(id: String, email: String, createdAt: Date, hasPassword: Bool = true) {
        self.id = id
        self.email = email
        self.createdAt = createdAt
        self.hasPassword = hasPassword
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case email
        case createdAt = "created_at"
        case hasPassword = "has_password"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        email = try container.decode(String.self, forKey: .email)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        hasPassword = try container.decodeIfPresent(Bool.self, forKey: .hasPassword) ?? true
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(email, forKey: .email)
        try container.encode(createdAt, forKey: .createdAt)
        try container.encode(hasPassword, forKey: .hasPassword)
    }
}

/// Authentication response with access + refresh tokens
public struct AuthResponse: Codable, Sendable {
    public let accessToken: String
    public let refreshToken: String?
    public let tokenType: String

    private enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
    }
}

/// Request to refresh tokens
public struct RefreshTokenRequest: Codable, Sendable {
    public let refreshToken: String

    public init(refreshToken: String) {
        self.refreshToken = refreshToken
    }

    private enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

/// Request to logout with optional refresh token revocation
public struct LogoutRequest: Codable, Sendable {
    public let refreshToken: String?

    public init(refreshToken: String?) {
        self.refreshToken = refreshToken
    }

    private enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

/// Auth request payloads
public struct LoginRequest: Codable, Sendable {
    public let email: String
    public let password: String

    public init(email: String, password: String) {
        self.email = email
        self.password = password
    }
}

public struct RegisterRequest: Codable, Sendable {
    public let email: String
    public let password: String

    public init(email: String, password: String) {
        self.email = email
        self.password = password
    }
}

public struct MagicLinkRequest: Codable, Sendable {
    public let email: String
    public let client: String?

    public init(email: String, client: String? = nil) {
        self.email = email
        self.client = client
    }
}

public struct VerifyMagicLinkRequest: Codable, Sendable {
    public let token: String

    public init(token: String) {
        self.token = token
    }
}

public struct ChangePasswordRequest: Codable, Sendable {
    public let currentPassword: String
    public let newPassword: String

    public init(currentPassword: String, newPassword: String) {
        self.currentPassword = currentPassword
        self.newPassword = newPassword
    }

    private enum CodingKeys: String, CodingKey {
        case currentPassword = "current_password"
        case newPassword = "new_password"
    }
}

// MARK: - Settings

/// Response from GET /api/settings
public struct UserSettings: Codable, Sendable {
    public let defaultLanguage: String
    public let summaryLanguage: String
    public let summaryStyle: String
    public let summaryInstructions: String?
    public let dictationLiveSTTProvider: String
    public let dictationLiveSTTModel: String
    public let recordingLiveSTTProvider: String
    public let recordingLiveSTTModel: String
    public let fileSTTProvider: String
    public let fileSTTModel: String
    public let dictationPostFilterEnabled: Bool
    public let dictationPostFilterProvider: String
    public let dictationPostFilterModel: String

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        defaultLanguage = try container.decode(String.self, forKey: .defaultLanguage)
        summaryLanguage = try container.decode(String.self, forKey: .summaryLanguage)
        summaryStyle = try container.decode(String.self, forKey: .summaryStyle)
        summaryInstructions = try container.decodeIfPresent(String.self, forKey: .summaryInstructions)

        // Compatibility for clients briefly ahead of the production API. If the
        // server omits account-level transcription preferences, stay on the
        // legacy provider that the old backend can actually service.
        dictationLiveSTTProvider = try container.decodeIfPresent(
            String.self,
            forKey: .dictationLiveSTTProvider
        ) ?? "elevenlabs"
        dictationLiveSTTModel = try container.decodeIfPresent(
            String.self,
            forKey: .dictationLiveSTTModel
        ) ?? "scribe_v2_realtime"
        recordingLiveSTTProvider = try container.decodeIfPresent(
            String.self,
            forKey: .recordingLiveSTTProvider
        ) ?? "elevenlabs"
        recordingLiveSTTModel = try container.decodeIfPresent(
            String.self,
            forKey: .recordingLiveSTTModel
        ) ?? "scribe_v2_realtime"
        fileSTTProvider = try container.decodeIfPresent(String.self, forKey: .fileSTTProvider) ?? "elevenlabs"
        fileSTTModel = try container.decodeIfPresent(String.self, forKey: .fileSTTModel) ?? "scribe_v2"
        dictationPostFilterEnabled = try container.decodeIfPresent(
            Bool.self,
            forKey: .dictationPostFilterEnabled
        ) ?? true
        dictationPostFilterProvider = try container.decodeIfPresent(
            String.self,
            forKey: .dictationPostFilterProvider
        ) ?? "anthropic"
        dictationPostFilterModel = try container.decodeIfPresent(
            String.self,
            forKey: .dictationPostFilterModel
        ) ?? "claude-haiku-4-5-20251001"
    }

    private enum CodingKeys: String, CodingKey {
        case defaultLanguage = "default_language"
        case summaryLanguage = "summary_language"
        case summaryStyle = "summary_style"
        case summaryInstructions = "summary_instructions"
        case dictationLiveSTTProvider = "dictation_live_stt_provider"
        case dictationLiveSTTModel = "dictation_live_stt_model"
        case recordingLiveSTTProvider = "recording_live_stt_provider"
        case recordingLiveSTTModel = "recording_live_stt_model"
        case fileSTTProvider = "file_stt_provider"
        case fileSTTModel = "file_stt_model"
        case dictationPostFilterEnabled = "dictation_post_filter_enabled"
        case dictationPostFilterProvider = "dictation_post_filter_provider"
        case dictationPostFilterModel = "dictation_post_filter_model"
    }
}

/// Request to PATCH /api/settings
public struct UpdateSettingsRequest: Codable, Sendable {
    public var defaultLanguage: String?
    public var summaryLanguage: String?
    public var summaryStyle: String?
    public var summaryInstructions: String?
    public var dictationLiveSTTProvider: String?
    public var dictationLiveSTTModel: String?
    public var recordingLiveSTTProvider: String?
    public var recordingLiveSTTModel: String?
    public var fileSTTProvider: String?
    public var fileSTTModel: String?
    public var dictationPostFilterEnabled: Bool?
    public var dictationPostFilterProvider: String?
    public var dictationPostFilterModel: String?

    public init(
        defaultLanguage: String? = nil,
        summaryLanguage: String? = nil,
        summaryStyle: String? = nil,
        summaryInstructions: String? = nil,
        dictationLiveSTTProvider: String? = nil,
        dictationLiveSTTModel: String? = nil,
        recordingLiveSTTProvider: String? = nil,
        recordingLiveSTTModel: String? = nil,
        fileSTTProvider: String? = nil,
        fileSTTModel: String? = nil,
        dictationPostFilterEnabled: Bool? = nil,
        dictationPostFilterProvider: String? = nil,
        dictationPostFilterModel: String? = nil
    ) {
        self.defaultLanguage = defaultLanguage
        self.summaryLanguage = summaryLanguage
        self.summaryStyle = summaryStyle
        self.summaryInstructions = summaryInstructions
        self.dictationLiveSTTProvider = dictationLiveSTTProvider
        self.dictationLiveSTTModel = dictationLiveSTTModel
        self.recordingLiveSTTProvider = recordingLiveSTTProvider
        self.recordingLiveSTTModel = recordingLiveSTTModel
        self.fileSTTProvider = fileSTTProvider
        self.fileSTTModel = fileSTTModel
        self.dictationPostFilterEnabled = dictationPostFilterEnabled
        self.dictationPostFilterProvider = dictationPostFilterProvider
        self.dictationPostFilterModel = dictationPostFilterModel
    }

    private enum CodingKeys: String, CodingKey {
        case defaultLanguage = "default_language"
        case summaryLanguage = "summary_language"
        case summaryStyle = "summary_style"
        case summaryInstructions = "summary_instructions"
        case dictationLiveSTTProvider = "dictation_live_stt_provider"
        case dictationLiveSTTModel = "dictation_live_stt_model"
        case recordingLiveSTTProvider = "recording_live_stt_provider"
        case recordingLiveSTTModel = "recording_live_stt_model"
        case fileSTTProvider = "file_stt_provider"
        case fileSTTModel = "file_stt_model"
        case dictationPostFilterEnabled = "dictation_post_filter_enabled"
        case dictationPostFilterProvider = "dictation_post_filter_provider"
        case dictationPostFilterModel = "dictation_post_filter_model"
    }
}

public struct TranscriptionModelOption: Codable, Sendable, Identifiable, Hashable {
    public let provider: String
    public let model: String
    public let label: String
    public let description: String

    public var id: String { "\(provider):\(model)" }

    public init(provider: String, model: String, label: String, description: String) {
        self.provider = provider
        self.model = model
        self.label = label
        self.description = description
    }
}

public struct TranscriptionOptions: Codable, Sendable {
    public let dictationLiveSTT: [TranscriptionModelOption]
    public let recordingLiveSTT: [TranscriptionModelOption]
    public let fileSTT: [TranscriptionModelOption]
    public let dictationPostFilter: [TranscriptionModelOption]

    public init(
        dictationLiveSTT: [TranscriptionModelOption],
        recordingLiveSTT: [TranscriptionModelOption],
        fileSTT: [TranscriptionModelOption],
        dictationPostFilter: [TranscriptionModelOption]
    ) {
        self.dictationLiveSTT = dictationLiveSTT
        self.recordingLiveSTT = recordingLiveSTT
        self.fileSTT = fileSTT
        self.dictationPostFilter = dictationPostFilter
    }

    private enum CodingKeys: String, CodingKey {
        case dictationLiveSTT = "dictation_live_stt"
        case recordingLiveSTT = "recording_live_stt"
        case fileSTT = "file_stt"
        case dictationPostFilter = "dictation_post_filter"
    }
}
