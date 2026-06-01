import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI
import UIKit
import WaiComputerKit

/// Telegram pairing screen — connect / disconnect / QR / code-entry / status.
///
/// Ports the behavior of `MacSettingsView.telegramSection`. Shared APIs and
/// models (`getTelegramLinkStatus` / `startTelegramLink` / `claimTelegramLinkCode`
/// / `unlinkTelegram`, `TelegramLinkStatus` / `TelegramPairing`) are reused as-is;
/// only the QR rasterization (`UIImage(ciImage:)`) and deep-link open
/// (`UIApplication.shared.open`) are iOS-native. The pairing poll is bound to
/// the view lifecycle via `.onDisappear` to avoid leaks.
struct TelegramSettingsView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager

    @State private var telegramStatus: TelegramLinkStatus?
    @State private var telegramPairing: TelegramPairing?
    @State private var telegramLinkCode = ""
    @State private var telegramLoading = false
    @State private var telegramError: String?
    @State private var telegramLinkPollTask: Task<Void, Never>?
    @State private var telegramShowCodeEntry = false

    var body: some View {
        List {
            Section {
                if telegramLoading && telegramStatus == nil {
                    HStack {
                        ProgressView()
                        Text(t("Loading Telegram status...", "Загружаем статус Telegram..."))
                            .font(Typography.body)
                            .foregroundStyle(Palette.textSecondary)
                    }
                } else if telegramStatus?.linked == true {
                    LabeledContent {
                        Text(telegramDisplayName)
                            .foregroundStyle(.green)
                    } label: {
                        Text("Telegram")
                    }

                    Button(role: .destructive) {
                        Task { await unlinkTelegram() }
                    } label: {
                        Text(t("Disconnect Telegram", "Отключить Telegram"))
                    }
                    .disabled(telegramLoading)
                    .accessibilityIdentifier("settings-telegram-unlink-button")
                } else {
                    unlinkedContent
                }

                if let telegramError {
                    Text(telegramError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } footer: {
                Text(t(
                    "Media sent to the bot is transcribed, summarized, and saved to your Library. Text messages are handled as Wai questions.",
                    "Медиа из бота расшифровываются, суммаризируются и сохраняются в Библиотеку. Текстовые сообщения обрабатываются как вопросы Wai."
                ))
            }
        }
        .navigationTitle("Telegram")
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadTelegramStatus() }
        .onDisappear { stopTelegramLinkPolling() }
    }

    @ViewBuilder
    private var unlinkedContent: some View {
        Text(t(
            "Connect @waicomputer_bot to send voice messages, videos, and text questions to Wai. You can start from WaiComputer or enter a code from the bot.",
            "Подключи @waicomputer_bot, чтобы отправлять голосовые, видео и вопросы Wai. Можно начать здесь или ввести код из бота."
        ))
        .font(Typography.caption)
        .foregroundStyle(Palette.textSecondary)
        .fixedSize(horizontal: false, vertical: true)

        HStack {
            Button {
                Task { await startTelegramLink() }
            } label: {
                Text(t("Connect Telegram", "Привязать Telegram"))
            }
            .disabled(telegramLoading)
            .accessibilityIdentifier("settings-telegram-link-button")

            if telegramLoading {
                Spacer()
                ProgressView()
            }
        }

        if let pairing = telegramPairing {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                if let qr = qrImage(from: pairing.webLink) {
                    Image(uiImage: qr)
                        .interpolation(.none)
                        .resizable()
                        .frame(width: 160, height: 160)
                        .accessibilityIdentifier("settings-telegram-qr")
                }
                Button {
                    openTelegramPairing(pairing)
                } label: {
                    Text(t("Open Telegram", "Открыть Telegram"))
                }
                .disabled(telegramLoading)
                .accessibilityIdentifier("settings-telegram-open-button")

                HStack(alignment: .top, spacing: Spacing.xs) {
                    ProgressView()
                    Text(t(
                        "Scan with another device or tap Open Telegram, then Start in the bot — WaiComputer finishes linking automatically.",
                        "Отсканируй код другим устройством или нажми «Открыть Telegram», затем Start в боте — WaiComputer завершит привязку автоматически."
                    ))
                }
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }

        // Manual code entry is only for the reverse flow (user started in the
        // bot). Hidden behind a disclosure so it doesn't look required.
        DisclosureGroup(isExpanded: $telegramShowCodeEntry) {
            HStack {
                TextField(t("Code from the bot", "Код из бота"), text: $telegramLinkCode)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .disabled(telegramLoading)
                    .accessibilityIdentifier("settings-telegram-code-field")
                Button {
                    Task { await claimTelegramLinkCode() }
                } label: {
                    Text(t("Link", "Привязать"))
                }
                .disabled(telegramLoading || telegramLinkCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("settings-telegram-claim-code-button")
            }
            .padding(.top, Spacing.xs)
        } label: {
            Text(t("Started in Telegram?", "Начал в Telegram?"))
                .font(Typography.caption.weight(.semibold))
        }
        .accessibilityIdentifier("settings-telegram-code-disclosure")
    }

    private var telegramDisplayName: String {
        guard let status = telegramStatus else { return t("Connected", "Подключено") }
        if let username = status.username, !username.isEmpty {
            return "@\(username)"
        }
        let fullName = [status.firstName, status.lastName]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        return fullName.isEmpty ? t("Connected", "Подключено") : fullName
    }

    // MARK: - Actions

    private func loadTelegramStatus(silent: Bool = false) async {
        guard !telegramLoading || silent else { return }
        if !silent {
            telegramLoading = true
        }
        do {
            telegramStatus = try await appState.getAPIClient().getTelegramLinkStatus()
            if telegramStatus?.linked == true {
                telegramPairing = nil
                telegramLinkCode = ""
                stopTelegramLinkPolling()
            }
            telegramError = nil
        } catch {
            if !silent {
                telegramError = t(
                    "Couldn't load Telegram status: \(error.localizedDescription)",
                    "Не удалось загрузить статус Telegram: \(error.localizedDescription)"
                )
            }
        }
        if !silent {
            telegramLoading = false
        }
    }

    private func startTelegramLink() async {
        guard !telegramLoading else { return }
        stopTelegramLinkPolling()
        telegramLoading = true
        do {
            telegramPairing = try await appState.getAPIClient().startTelegramLink()
            telegramError = nil
            if let telegramPairing {
                // Don't auto-open the bot — show the QR + an explicit "Open
                // Telegram" button and poll in the background so linking still
                // completes automatically.
                startTelegramLinkPolling(until: telegramPairing.expiresAt)
            }
        } catch {
            telegramError = t(
                "Couldn't start Telegram pairing: \(error.localizedDescription)",
                "Не удалось начать привязку Telegram: \(error.localizedDescription)"
            )
        }
        telegramLoading = false
    }

    private func claimTelegramLinkCode() async {
        guard !telegramLoading else { return }
        let code = telegramLinkCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty else { return }
        telegramLoading = true
        do {
            telegramStatus = try await appState.getAPIClient().claimTelegramLinkCode(code)
            telegramPairing = nil
            telegramLinkCode = ""
            stopTelegramLinkPolling()
            telegramError = nil
        } catch {
            telegramError = t(
                "Couldn't link Telegram with this code: \(error.localizedDescription)",
                "Не удалось привязать Telegram по коду: \(error.localizedDescription)"
            )
        }
        telegramLoading = false
    }

    private func unlinkTelegram() async {
        guard !telegramLoading else { return }
        telegramLoading = true
        do {
            try await appState.getAPIClient().unlinkTelegram()
            telegramPairing = nil
            telegramLinkCode = ""
            stopTelegramLinkPolling()
            telegramStatus = try await appState.getAPIClient().getTelegramLinkStatus()
            telegramError = nil
        } catch {
            telegramError = t(
                "Couldn't disconnect Telegram: \(error.localizedDescription)",
                "Не удалось отключить Telegram: \(error.localizedDescription)"
            )
        }
        telegramLoading = false
    }

    private func openTelegramPairing(_ pairing: TelegramPairing) {
        if let deepURL = URL(string: pairing.deepLink) {
            UIApplication.shared.open(deepURL, options: [:]) { opened in
                if !opened {
                    telegramError = t("Couldn't open Telegram.", "Не удалось открыть Telegram.")
                }
            }
            return
        }
        telegramError = t("Couldn't open Telegram.", "Не удалось открыть Telegram.")
    }

    /// Render a QR for the pairing web link so the user can scan it with another
    /// device. Returns nil if generation fails; the explicit "Open Telegram"
    /// button is always available regardless.
    private func qrImage(from string: String) -> UIImage? {
        guard !string.isEmpty else { return nil }
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 8, y: 8))
        let context = CIContext()
        guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else { return nil }
        return UIImage(cgImage: cgImage)
    }

    private func startTelegramLinkPolling(until expiresAt: Date) {
        stopTelegramLinkPolling()
        telegramLinkPollTask = Task { @MainActor in
            while !Task.isCancelled && Date() < expiresAt {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                if Task.isCancelled { break }
                await loadTelegramStatus(silent: true)
                if telegramStatus?.linked == true { break }
            }
        }
    }

    private func stopTelegramLinkPolling() {
        telegramLinkPollTask?.cancel()
        telegramLinkPollTask = nil
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
