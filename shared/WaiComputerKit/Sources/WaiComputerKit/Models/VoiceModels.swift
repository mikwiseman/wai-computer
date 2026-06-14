import Foundation

public enum RealtimeVoiceMode: String, Codable, Sendable {
    case conversation
    case recording
}

public enum RealtimeTranscriptionPurpose: String, Codable, Sendable, Hashable {
    case recording
    case dictation
}

public struct RealtimeTranscriptionReplacement: Codable, Sendable, Hashable {
    public let find: String
    public let replace: String

    public init(find: String, replace: String) {
        self.find = find
        self.replace = replace
    }
}

public struct CreateRealtimeTranscriptionSessionRequest: Codable, Sendable {
    public let language: String
    public let channels: Int
    public let purpose: RealtimeTranscriptionPurpose
    public let keyterms: [String]
    public let replacements: [RealtimeTranscriptionReplacement]

    public init(
        language: String = "multi",
        channels: Int = 1,
        purpose: RealtimeTranscriptionPurpose = .recording,
        keyterms: [String] = [],
        replacements: [RealtimeTranscriptionReplacement] = []
    ) {
        self.language = language
        self.channels = channels
        self.purpose = purpose
        self.keyterms = keyterms
        self.replacements = replacements
    }
}

public struct RealtimeTranscriptionSessionConfig: Codable, Sendable {
    public let provider: String
    public let token: String
    public let expiresInSeconds: Int
    public let sampleRate: Int
    public let audioFormat: String
    public let language: String
    public let channels: Int
    public let model: String
    public let keepAliveIntervalSeconds: Int?
    public let commitStrategy: String?
    public let noVerbatim: Bool?
    public let websocketURL: String?
    public let authScheme: String?

    enum CodingKeys: String, CodingKey {
        case provider
        case token
        case expiresInSeconds = "expires_in_seconds"
        case sampleRate = "sample_rate"
        case audioFormat = "audio_format"
        case language
        case channels
        case model
        case keepAliveIntervalSeconds = "keep_alive_interval_seconds"
        case commitStrategy = "commit_strategy"
        case noVerbatim = "no_verbatim"
        case websocketURL = "websocket_url"
        case authScheme = "auth_scheme"
    }

    public init(
        provider: String,
        token: String,
        expiresInSeconds: Int,
        sampleRate: Int,
        audioFormat: String,
        language: String,
        channels: Int,
        model: String,
        keepAliveIntervalSeconds: Int? = nil,
        commitStrategy: String? = nil,
        noVerbatim: Bool? = nil,
        websocketURL: String? = nil,
        authScheme: String? = nil
    ) {
        self.provider = provider
        self.token = token
        self.expiresInSeconds = expiresInSeconds
        self.sampleRate = sampleRate
        self.audioFormat = audioFormat
        self.language = language
        self.channels = channels
        self.model = model
        self.keepAliveIntervalSeconds = keepAliveIntervalSeconds
        self.commitStrategy = commitStrategy
        self.noVerbatim = noVerbatim
        self.websocketURL = websocketURL
        self.authScheme = authScheme
    }
}

public struct CreateRealtimeVoiceSessionRequest: Codable, Sendable {
    public let mode: RealtimeVoiceMode
    public let modelId: String?
    public let includeConversationId: Bool
    public let branchId: String?
    public let environment: String?

    public init(
        mode: RealtimeVoiceMode = .conversation,
        modelId: String? = nil,
        includeConversationId: Bool = false,
        branchId: String? = nil,
        environment: String? = nil
    ) {
        self.mode = mode
        self.modelId = modelId
        self.includeConversationId = includeConversationId
        self.branchId = branchId
        self.environment = environment
    }

    enum CodingKeys: String, CodingKey {
        case mode
        case modelId = "agent_id"
        case includeConversationId = "include_conversation_id"
        case branchId = "branch_id"
        case environment
    }
}

public struct RealtimeVoiceSession: Codable, Sendable {
    public let provider: String
    public let mode: String
    public let agentId: String
    public let signedURL: String
    public let expiresInSeconds: Int
    public let environment: String?
    public let branchId: String?

    enum CodingKeys: String, CodingKey {
        case provider
        case mode
        case agentId = "agent_id"
        case signedURL = "signed_url"
        case expiresInSeconds = "expires_in_seconds"
        case environment
        case branchId = "branch_id"
    }
}
