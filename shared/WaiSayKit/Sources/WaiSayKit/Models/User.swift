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

    private enum CodingKeys: String, CodingKey {
        case defaultLanguage = "default_language"
        case summaryLanguage = "summary_language"
        case summaryStyle = "summary_style"
        case summaryInstructions = "summary_instructions"
    }
}

/// Request to PATCH /api/settings
public struct UpdateSettingsRequest: Codable, Sendable {
    public var defaultLanguage: String?
    public var summaryLanguage: String?
    public var summaryStyle: String?
    public var summaryInstructions: String?

    public init(
        defaultLanguage: String? = nil,
        summaryLanguage: String? = nil,
        summaryStyle: String? = nil,
        summaryInstructions: String? = nil
    ) {
        self.defaultLanguage = defaultLanguage
        self.summaryLanguage = summaryLanguage
        self.summaryStyle = summaryStyle
        self.summaryInstructions = summaryInstructions
    }

    private enum CodingKeys: String, CodingKey {
        case defaultLanguage = "default_language"
        case summaryLanguage = "summary_language"
        case summaryStyle = "summary_style"
        case summaryInstructions = "summary_instructions"
    }
}
