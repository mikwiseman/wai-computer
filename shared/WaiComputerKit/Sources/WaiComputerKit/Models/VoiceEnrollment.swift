import Foundation

/// Response from POST /api/voice-enrollment — the new voiceprint plus the Person it was attached to.
public struct VoiceEnrollmentResponse: Codable, Sendable {
    public let person: Person
    public let voiceprintId: String
    public let durationS: Double

    public init(person: Person, voiceprintId: String, durationS: Double) {
        self.person = person
        self.voiceprintId = voiceprintId
        self.durationS = durationS
    }

    private enum CodingKeys: String, CodingKey {
        case person
        case voiceprintId = "voiceprint_id"
        case durationS = "duration_s"
    }
}
