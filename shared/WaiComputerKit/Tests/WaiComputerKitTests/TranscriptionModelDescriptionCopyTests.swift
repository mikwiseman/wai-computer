import XCTest
@testable import WaiComputerKit

final class TranscriptionModelDescriptionCopyTests: XCTestCase {
    func testRussianDescriptionUsesClientCopyForKnownOptions() {
        let option = TranscriptionModelOption(
            provider: "deepgram",
            model: "nova-3",
            label: "Deepgram Nova-3",
            description: "Default for dictation. Deepgram Nova-3 for streaming speech recognition."
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .dictationLiveSTT,
            languageCode: "ru"
        )

        XCTAssertEqual(
            description,
            "По умолчанию для диктовки. Deepgram Nova-3 для быстрого потокового распознавания речи."
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
            provider: "deepgram",
            model: "nova-3",
            label: "Deepgram Nova-3",
            description: "Default for live recording. Deepgram Nova-3 for streaming speech recognition."
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .recordingLiveSTT,
            languageCode: "ru"
        )

        XCTAssertEqual(
            description,
            "По умолчанию для живой записи. Deepgram Nova-3 для быстрого потокового распознавания речи."
        )
    }
}
