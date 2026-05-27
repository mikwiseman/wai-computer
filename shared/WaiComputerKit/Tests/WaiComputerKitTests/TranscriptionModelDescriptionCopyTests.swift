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
            provider: "openai",
            model: "gpt-4o-transcribe-diarize",
            label: "OpenAI GPT-4o Transcribe Diarize",
            description: serverDescription
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .fileSTT,
            languageCode: "en"
        )

        XCTAssertEqual(description, serverDescription)
    }

    func testRussianFileSTTDescriptionUsesOpenAICopy() {
        let option = TranscriptionModelOption(
            provider: "openai",
            model: "gpt-4o-transcribe-diarize",
            label: "OpenAI GPT-4o Transcribe Diarize",
            description: "Fixed full-session transcription model with speaker diarization."
        )

        let description = TranscriptionModelDescriptionCopy.description(
            for: option,
            context: .fileSTT,
            languageCode: "ru"
        )

        XCTAssertEqual(
            description,
            "По умолчанию для полной расшифровки записи. Модель OpenAI для файловой транскрибации с разделением по говорящим."
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
