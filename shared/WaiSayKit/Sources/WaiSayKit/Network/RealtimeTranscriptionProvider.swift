import Foundation

/// Provider-agnostic interface for realtime speech-to-text. The dictation
/// flow uses this lower-level provider abstraction for direct Inworld
/// sessions, while recording and account-selected live transcription use
/// `WebSocketManager` because the backend already returns a provider-specific
/// realtime session.
public protocol RealtimeTranscriptionProvider: Sendable {
    var name: String { get }
    func openSession(
        model: String,
        language: String?,
        sampleRate: Int
    ) async throws -> any ProviderSession
}

public protocol ProviderSession: Actor {
    var events: AsyncStream<TranscriptionEvent> { get }
    func send(pcm16: Data) async throws
    func endTurn() async throws
    func close(timeout: Duration) async throws -> [LiveTranscriptSegment]
    func cancel() async
}

public enum TranscriptionEvent: @unchecked Sendable {
    case opened(sessionId: String)
    case interim(text: String, language: String?)
    case committed(LiveTranscriptSegment)
    case voiceProfile(VoiceProfile)
    case providerWarning(ProviderError)
    case usage(promptedSeconds: Double)
    case closed(reason: ProviderCloseReason)
}

public struct VoiceProfile: Sendable, Equatable {
    public let age: String?
    public let pitch: String?
    public let emotion: String?
    public let vocalStyle: String?
    public let accent: String?

    public init(age: String?, pitch: String?, emotion: String?, vocalStyle: String?, accent: String?) {
        self.age = age
        self.pitch = pitch
        self.emotion = emotion
        self.vocalStyle = vocalStyle
        self.accent = accent
    }
}

public enum ProviderCloseReason: Sendable, Equatable {
    case clientRequested
    case serverEndOfStream
    case serverError(code: Int)
    case networkLost
    case sessionTimeLimitExceeded
}

/// Typed errors propagated from the provider layer. Recovery is local to
/// the session — auth_error triggers a single token refresh + retry, every
/// other error fails fast (no provider switching, no silent fallbacks).
public enum ProviderError: Error, Sendable, Equatable {
    case authError(server: String?)
    case quotaExceeded
    case rateLimited(retryAfterMs: Int?)
    case insufficientAudioActivity
    case sessionTimeLimitExceeded
    case chunkSizeExceeded
    case commitThrottled
    case unsupportedModel(String)
    case transcriberInternal(message: String)
    case malformedFrame(rawType: String)

    public var fingerprint: String {
        switch self {
        case .authError: return "provider.auth_error"
        case .quotaExceeded: return "provider.quota_exceeded"
        case .rateLimited: return "provider.rate_limited"
        case .insufficientAudioActivity: return "provider.insufficient_audio_activity"
        case .sessionTimeLimitExceeded: return "provider.session_time_limit"
        case .chunkSizeExceeded: return "provider.chunk_size_exceeded"
        case .commitThrottled: return "provider.commit_throttled"
        case .unsupportedModel: return "provider.unsupported_model"
        case .transcriberInternal: return "provider.transcriber_internal"
        case .malformedFrame: return "provider.malformed_frame"
        }
    }
}
