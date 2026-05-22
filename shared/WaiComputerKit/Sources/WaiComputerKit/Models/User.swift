import Foundation

/// User model
public struct User: Codable, Identifiable, Sendable {
    public let id: String
    public let email: String
    public let createdAt: Date
    public let hasPassword: Bool
    public let region: String

    public init(
        id: String,
        email: String,
        createdAt: Date,
        hasPassword: Bool = true,
        region: String = "global"
    ) {
        self.id = id
        self.email = email
        self.createdAt = createdAt
        self.hasPassword = hasPassword
        self.region = region
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case email
        case createdAt = "created_at"
        case hasPassword = "has_password"
        case region
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        email = try container.decode(String.self, forKey: .email)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        hasPassword = try container.decodeIfPresent(Bool.self, forKey: .hasPassword) ?? true
        region = try container.decodeIfPresent(String.self, forKey: .region) ?? "global"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(email, forKey: .email)
        try container.encode(createdAt, forKey: .createdAt)
        try container.encode(hasPassword, forKey: .hasPassword)
        try container.encode(region, forKey: .region)
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
public enum LegalDocumentVersions {
    public static let terms = "2026-05-22"
    public static let privacy = "2026-05-22"
}

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
    public let region: String?
    public let acceptedLegalTerms: Bool
    public let legalTermsVersion: String
    public let legalPrivacyVersion: String

    public init(
        email: String,
        password: String,
        region: String? = nil,
        acceptedLegalTerms: Bool,
        legalTermsVersion: String = LegalDocumentVersions.terms,
        legalPrivacyVersion: String = LegalDocumentVersions.privacy
    ) {
        self.email = email
        self.password = password
        self.region = region
        self.acceptedLegalTerms = acceptedLegalTerms
        self.legalTermsVersion = legalTermsVersion
        self.legalPrivacyVersion = legalPrivacyVersion
    }

    private enum CodingKeys: String, CodingKey {
        case email
        case password
        case region
        case acceptedLegalTerms = "accepted_legal_terms"
        case legalTermsVersion = "legal_terms_version"
        case legalPrivacyVersion = "legal_privacy_version"
    }
}

public struct MagicLinkRequest: Codable, Sendable {
    public let email: String
    public let client: String?
    public let region: String?
    public let acceptedLegalTerms: Bool?
    public let legalTermsVersion: String?
    public let legalPrivacyVersion: String?

    public init(
        email: String,
        client: String? = nil,
        region: String? = nil,
        acceptedLegalTerms: Bool? = nil,
        legalTermsVersion: String? = nil,
        legalPrivacyVersion: String? = nil
    ) {
        self.email = email
        self.client = client
        self.region = region
        self.acceptedLegalTerms = acceptedLegalTerms
        self.legalTermsVersion = legalTermsVersion
        self.legalPrivacyVersion = legalPrivacyVersion
    }

    private enum CodingKeys: String, CodingKey {
        case email
        case client
        case region
        case acceptedLegalTerms = "accepted_legal_terms"
        case legalTermsVersion = "legal_terms_version"
        case legalPrivacyVersion = "legal_privacy_version"
    }
}

public struct PasswordResetRequest: Codable, Sendable {
    public let email: String
    public let locale: String?

    public init(email: String, locale: String? = nil) {
        self.email = email
        self.locale = locale
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
    public let region: String

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        defaultLanguage = try container.decode(String.self, forKey: .defaultLanguage)
        summaryLanguage = try container.decode(String.self, forKey: .summaryLanguage)
        summaryStyle = try container.decode(String.self, forKey: .summaryStyle)
        summaryInstructions = try container.decodeIfPresent(String.self, forKey: .summaryInstructions)

        dictationLiveSTTProvider = try container.decode(String.self, forKey: .dictationLiveSTTProvider)
        dictationLiveSTTModel = try container.decode(String.self, forKey: .dictationLiveSTTModel)
        recordingLiveSTTProvider = try container.decode(String.self, forKey: .recordingLiveSTTProvider)
        recordingLiveSTTModel = try container.decode(String.self, forKey: .recordingLiveSTTModel)
        fileSTTProvider = try container.decode(String.self, forKey: .fileSTTProvider)
        fileSTTModel = try container.decode(String.self, forKey: .fileSTTModel)
        dictationPostFilterEnabled = try container.decode(Bool.self, forKey: .dictationPostFilterEnabled)
        dictationPostFilterProvider = try container.decode(String.self, forKey: .dictationPostFilterProvider)
        dictationPostFilterModel = try container.decode(String.self, forKey: .dictationPostFilterModel)
        region = try container.decodeIfPresent(String.self, forKey: .region) ?? "global"
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
        case region
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
    public var region: String?

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
        dictationPostFilterModel: String? = nil,
        region: String? = nil
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
        self.region = region
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
        case region
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

// MARK: - Telegram

public struct TelegramLinkStatus: Codable, Sendable {
    public let linked: Bool
    public let botUsername: String
    public let telegramUserID: Int?
    public let username: String?
    public let firstName: String?
    public let lastName: String?
    public let linkedAt: Date?

    private enum CodingKeys: String, CodingKey {
        case linked
        case botUsername = "bot_username"
        case telegramUserID = "telegram_user_id"
        case username
        case firstName = "first_name"
        case lastName = "last_name"
        case linkedAt = "linked_at"
    }
}

public struct TelegramPairing: Codable, Sendable {
    public let botUsername: String
    public let deepLink: String
    public let webLink: String
    public let expiresAt: Date

    private enum CodingKeys: String, CodingKey {
        case botUsername = "bot_username"
        case deepLink = "deep_link"
        case webLink = "web_link"
        case expiresAt = "expires_at"
    }
}

public struct TelegramLinkCodeClaimRequest: Codable, Sendable {
    public let code: String

    public init(code: String) {
        self.code = code
    }
}
