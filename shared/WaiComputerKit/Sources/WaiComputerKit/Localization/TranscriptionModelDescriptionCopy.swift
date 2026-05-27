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
        CopyKey(context: .dictationLiveSTT, provider: "inworld", model: "inworld/inworld-stt-1"):
            "По умолчанию для диктовки. Собственная модель Inworld с настраиваемым определением пауз и учетом голосового профиля.",

        CopyKey(context: .recordingLiveSTT, provider: "inworld", model: "inworld/inworld-stt-1"):
            "По умолчанию для живой записи. Собственная модель Inworld с настраиваемым определением пауз и учетом голосового профиля.",

        CopyKey(context: .fileSTT, provider: "elevenlabs", model: "scribe_v2"):
            "По умолчанию. Самая точная из поддерживаемых файловых моделей: 90+ языков и разделение по говорящим.",

        CopyKey(context: .dictationPostFilter, provider: "openai", model: "gpt-5.5"):
            "Модель очистки продиктованного текста по умолчанию.",
    ]
}
