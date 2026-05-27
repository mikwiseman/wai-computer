import XCTest
@testable import WaiComputerKit

final class TranscriptionModelDescriptionCopyTests: XCTestCase {
    func testRussianDescriptionUsesClientCopyForKnownOptions() {
        let option = TranscriptionModelOption(
            provider: "openai",
            model: "gpt-realtime-whisper",
            label: "OpenAI GPT Realtime Whisper",
            description: "Default for dictation. OpenAI realtime Whisper model for streaming speech recognition."
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .dictationLiveSTT,
            languageCode: "ru"
        )

        XCTAssertEqual(
            description,
            "По умолчанию для диктовки. Realtime-модель OpenAI Whisper для потокового распознавания речи."
        )
        XCTAssertFalse(description.contains("Default for dictation"))
    }

    func testEnglishDescriptionPreservesServerCopy() {
        let serverDescription = "Default file transcription model with multilingual diarization."
        let option = TranscriptionModelOption(
            provider: "elevenlabs",
            model: "scribe_v2",
            label: "ElevenLabs Scribe v2",
            description: serverDescription
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .fileSTT,
            languageCode: "en"
        )

        XCTAssertEqual(description, serverDescription)
    }

    func testRussianFileSTTDescriptionUsesElevenLabsCopy() {
        let option = TranscriptionModelOption(
            provider: "elevenlabs",
            model: "scribe_v2",
            label: "ElevenLabs Scribe v2",
            description: "Fixed full-session transcription model with speaker diarization."
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .fileSTT,
            languageCode: "ru"
        )

        XCTAssertEqual(
            description,
            "По умолчанию для полной расшифровки записи. ElevenLabs Scribe v2 с разделением по говорящим."
        )
    }

    func testContextDifferentiatesRepeatedProviderModelPairs() {
        let option = TranscriptionModelOption(
            provider: "openai",
            model: "gpt-realtime-whisper",
            label: "OpenAI GPT Realtime Whisper",
            description: "Default for live recording. OpenAI realtime Whisper model for streaming speech recognition."
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .recordingLiveSTT,
            languageCode: "ru"
        )

        XCTAssertEqual(
            description,
            "По умолчанию для живой записи. Realtime-модель OpenAI Whisper для потокового распознавания речи."
        )
    }
}
