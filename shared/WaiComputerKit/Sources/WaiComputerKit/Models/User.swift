import Foundation

/// User model
public struct User: Codable, Identifiable, Sendable {
    public let id: String
    public let email: String
    public let createdAt: Date

    public init(id: String, email: String, createdAt: Date) {
        self.id = id
        self.email = email
        self.createdAt = createdAt
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case email
        case createdAt = "created_at"
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
