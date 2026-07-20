import Foundation

public enum TranscriptionModelOptionContext: String, Sendable, Hashable {
    case dictationLiveSTT
    case recordingLiveSTT
    case fileSTT
    case dictationPostFilter
}

public enum TranscriptionModelDescriptionCopy {
    public static func description(
        for option: TranscriptionModelOption,
        context: TranscriptionModelOptionContext,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        description(
            for: option,
            context: context,
            languageCode: languageCode(for: language)
        )
    }

    public static func description(
        for option: TranscriptionModelOption,
        context: TranscriptionModelOptionContext,
        languageCode: String
    ) -> String {
        guard languageCode.lowercased().hasPrefix("ru") else {
            return option.description
        }

        let key = CopyKey(context: context, provider: option.provider, model: option.model)
        return russianCopy[key] ?? "Описание модели пока не локализовано."
    }

    private static func languageCode(for selection: LanguageManager.SupportedLanguage) -> String {
        switch selection {
        case .english:
            return "en"
        case .russian:
            return "ru"
        case .followSystem:
            return Locale.preferredLanguages.first ?? Locale.current.identifier
        }
    }

    private struct CopyKey: Hashable {
        let context: TranscriptionModelOptionContext
        let provider: String
        let model: String

        init(context: TranscriptionModelOptionContext, provider: String, model: String) {
            self.context = context
            self.provider = provider.lowercased()
            self.model = model
        }
    }

    private static let russianCopy: [CopyKey: String] = [
        CopyKey(context: .dictationLiveSTT, provider: "openai", model: "gpt-realtime-whisper"):
            "По умолчанию для диктовки. OpenAI gpt-realtime-whisper: потоковое распознавание "
            + "с высокой точностью, включая смешанную русско-английскую речь.",

        CopyKey(context: .dictationLiveSTT, provider: "deepgram", model: "nova-3"):
            "Deepgram Nova-3 для быстрого потокового распознавания речи.",

        CopyKey(context: .recordingLiveSTT, provider: "deepgram", model: "nova-3"):
            "По умолчанию для живой записи. Deepgram Nova-3 для быстрого потокового распознавания речи.",

        CopyKey(context: .fileSTT, provider: "deepgram", model: "nova-3"):
            "По умолчанию для полной расшифровки записи. Deepgram Nova-3 с разделением по говорящим.",
    ]
}
