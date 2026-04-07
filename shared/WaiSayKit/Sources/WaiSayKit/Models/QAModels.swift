import Foundation

public struct QARequest: Codable {
    public let question: String
    public let recordingIds: [String]?

    public init(question: String, recordingIds: [String]? = nil) {
        self.question = question
        self.recordingIds = recordingIds
    }

    enum CodingKeys: String, CodingKey {
        case question
        case recordingIds = "recording_ids"
    }
}

public struct QAResponse: Codable {
    public let answer: String
    public let sources: [QASource]

    public init(answer: String, sources: [QASource]) {
        self.answer = answer
        self.sources = sources
    }
}

public struct QASource: Codable, Identifiable {
    public var id: String { segmentId }
    public let segmentId: String
    public let recordingId: String
    public let recordingTitle: String?
    public let speaker: String?
    public let content: String
    public let startMs: Int?
    public let endMs: Int?

    public init(
        segmentId: String,
        recordingId: String,
        recordingTitle: String?,
        speaker: String?,
        content: String,
        startMs: Int?,
        endMs: Int?
    ) {
        self.segmentId = segmentId
        self.recordingId = recordingId
        self.recordingTitle = recordingTitle
        self.speaker = speaker
        self.content = content
        self.startMs = startMs
        self.endMs = endMs
    }

    enum CodingKeys: String, CodingKey {
        case segmentId = "segment_id"
        case recordingId = "recording_id"
        case recordingTitle = "recording_title"
        case speaker
        case content
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}
