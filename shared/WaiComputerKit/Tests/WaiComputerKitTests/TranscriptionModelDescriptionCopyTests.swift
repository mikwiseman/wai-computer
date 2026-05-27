import XCTest
@testable import WaiComputerKit

final class TranscriptionModelDescriptionCopyTests: XCTestCase {
    func testRussianDescriptionUsesClientCopyForKnownOptions() {
        let option = TranscriptionModelOption(
            provider: "inworld",
            model: "inworld/inworld-stt-1",
            label: "Inworld STT-1",
            description: "Default for dictation. Inworld first-party model for configurable turn-taking and voice-profile-aware transcription."
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .dictationLiveSTT,
            languageCode: "ru"
        )

        XCTAssertEqual(
            description,
            "По умолчанию для диктовки. Собственная модель Inworld с настраиваемым определением пауз и учетом голосового профиля."
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

    func testContextDifferentiatesRepeatedProviderModelPairs() {
        let option = TranscriptionModelOption(
            provider: "inworld",
            model: "inworld/inworld-stt-1",
            label: "Inworld STT-1",
            description: "Default for live recording. Inworld first-party model for configurable turn-taking and voice-profile-aware transcription."
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .recordingLiveSTT,
            languageCode: "ru"
        )

        XCTAssertEqual(
            description,
            "По умолчанию для живой записи. Собственная модель Inworld с настраиваемым определением пауз и учетом голосового профиля."
        )
    }
}
