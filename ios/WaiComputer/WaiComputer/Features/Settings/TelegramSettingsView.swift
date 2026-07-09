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
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    @State private var telegramStatus: TelegramLinkStatus?
    @State private var telegramPairing: TelegramPairing?
    @State private var telegramLinkCode = ""
    @State private var telegramLoading = false
    @State private var telegramError: String?
    @State private var telegramLinkPollTask: Task<Void, Never>?
    @State private var telegramShowCodeEntry = false

    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                regularLayout
            } else {
                compactList
            }
        }
        .navigationTitle("Telegram")
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadTelegramStatus() }
        .onDisappear { stopTelegramLinkPolling() }
    }

    private var compactList: some View {
        List {
            Section {
                if telegramLoading && telegramStatus == nil {
                    HStack {
                        ProgressView()
                        Text(t("Loading Telegram status…", "Загружаем статус Telegram…"))
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
    }

    private var regularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                regularHeader

                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                    alignment: .leading,
                    spacing: Spacing.lg
                ) {
                    regularStatusPanel
                    regularPairingPanel
                    regularCapturePanel
                }

                if let telegramError {
                    Text(telegramError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("settings-telegram-error")
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 920, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-telegram-regular-layout")
    }

    private var regularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "paperplane")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Telegram")
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Send voice, video, files, and text questions to Wai from Telegram.",
                    "Отправляй голос, видео, файлы и вопросы Wai из Telegram."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .accessibilityIdentifier("settings-telegram-regular-header")
    }

    private var regularStatusPanel: some View {
        regularPanel(
            title: t("Connection", "Подключение"),
            subtitle: t(
                "Pair @waicomputer_bot with this WaiComputer account.",
                "Привяжи @waicomputer_bot к этому аккаунту WaiComputer."
            ),
            systemImage: "paperplane.circle",
            identifier: "settings-telegram-regular-status-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                if telegramLoading && telegramStatus == nil {
                    HStack(spacing: Spacing.sm) {
                        ProgressView()
                            .controlSize(.small)
                        Text(t("Loading Telegram status…", "Загружаем статус Telegram…"))
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textTertiary)
                    }
                } else if telegramStatus?.linked == true {
                    regularInfoRow(
                        title: telegramDisplayName,
                        subtitle: t("Connected", "Подключено"),
                        systemImage: "checkmark.circle.fill",
                        tint: .green
                    )

                    Button(role: .destructive) {
                        Task { await unlinkTelegram() }
                    } label: {
                        Label(t("Disconnect Telegram", "Отключить Telegram"), systemImage: "xmark.circle")
                    }
                    .buttonStyle(.bordered)
                    .disabled(telegramLoading)
                    .accessibilityIdentifier("settings-telegram-unlink-button")
                } else {
                    Text(t(
                        "Start from WaiComputer to show a QR code and deep link, or enter a code if you started inside Telegram.",
                        "Начни из WaiComputer, чтобы показать QR-код и ссылку, или введи код, если начал в Telegram."
                    ))
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                    HStack(spacing: Spacing.sm) {
                        Button {
                            Task { await startTelegramLink() }
                        } label: {
                            Label(t("Connect Telegram", "Привязать Telegram"), systemImage: "link")
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(telegramLoading)
                        .accessibilityIdentifier("settings-telegram-link-button")

                        if telegramLoading {
                            ProgressView()
                                .controlSize(.small)
                        }
                    }
                }
            }
        }
    }

    private var regularPairingPanel: some View {
        regularPanel(
            title: t("Pairing", "Привязка"),
            subtitle: t(
                "Use a QR code, deep link, or reverse code from the bot.",
                "Используй QR-код, ссылку или код из бота."
            ),
            systemImage: "qrcode",
            identifier: "settings-telegram-regular-pairing-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                if let pairing = telegramPairing {
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
                        Label(t("Open Telegram", "Открыть Telegram"), systemImage: "paperplane")
                    }
                    .buttonStyle(.bordered)
                    .disabled(telegramLoading)
                    .accessibilityIdentifier("settings-telegram-open-button")

                    HStack(alignment: .top, spacing: Spacing.xs) {
                        ProgressView()
                            .controlSize(.small)
                        Text(t(
                            "Scan with another device or tap Open Telegram, then Start in the bot — WaiComputer finishes linking automatically.",
                            "Отсканируй код другим устройством или нажми «Открыть Telegram», затем Start в боте — WaiComputer завершит привязку автоматически."
                        ))
                    }
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                } else {
                    Text(t(
                        "A QR code appears here after you start pairing.",
                        "QR-код появится здесь после начала привязки."
                    ))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                }

                regularCodeEntry
            }
        }
    }

    private var regularCapturePanel: some View {
        regularPanel(
            title: t("Capture", "Захват"),
            subtitle: t(
                "Telegram becomes another input for your second brain.",
                "Telegram становится ещё одним входом в твою вторую память."
            ),
            systemImage: "tray.and.arrow.down",
            identifier: "settings-telegram-regular-capture-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                regularInfoRow(
                    title: t("Voice, video, and media", "Голос, видео и медиа"),
                    subtitle: t(
                        "Transcribed, summarized, and saved to your Library.",
                        "Расшифровываются, суммаризируются и сохраняются в Библиотеку."
                    ),
                    systemImage: "waveform",
                    tint: Palette.accent
                )

                Divider()

                regularInfoRow(
                    title: t("Text messages", "Текстовые сообщения"),
                    subtitle: t(
                        "Handled as Wai questions.",
                        "Обрабатываются как вопросы Wai."
                    ),
                    systemImage: "text.bubble",
                    tint: Palette.accent
                )
            }
        }
    }

    private var regularCodeEntry: some View {
        DisclosureGroup(isExpanded: $telegramShowCodeEntry) {
            HStack(spacing: Spacing.sm) {
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

    private func regularInfoRow(
        title: String,
        subtitle: String,
        systemImage: String,
        tint: Color
    ) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: systemImage)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 24, height: 24)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(title)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)
                Text(subtitle)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func regularPanel<Content: View>(
        title: String,
        subtitle: String?,
        systemImage: String,
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.md) {
                Image(systemName: systemImage)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 30, height: 30)
                    .background(Palette.accentSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(title)
                        .font(Typography.headingLarge)
                        .foregroundStyle(Palette.textPrimary)
                    if let subtitle {
                        Text(subtitle)
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            Divider()
            content()
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .accessibilityIdentifier(identifier)
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
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            telegramStatus = IOSScreenshotFixtures.telegramStatus
            telegramPairing = nil
            telegramLinkCode = ""
            telegramError = nil
            if !silent {
                telegramLoading = false
            }
            return
        }
        #endif
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
        guard let deepURL = URL(string: pairing.deepLink) else {
            telegramError = t("Couldn't open Telegram.", "Не удалось открыть Telegram.")
            return
        }
        // Use the async open API and hop back to the main actor for the @State
        // write so the mutation is provably main-actor-isolated (future-proof
        // for Swift 6 strict concurrency), not relying on UIKit's completion
        // thread guarantees inside an escaping closure.
        Task { @MainActor in
            let opened = await UIApplication.shared.open(deepURL)
            if !opened {
                telegramError = t("Couldn't open Telegram.", "Не удалось открыть Telegram.")
            }
        }
    }

    /// Render a QR for the pairing web link so the user can scan it with another
    /// device. Returns nil if generation fails; the explicit "Open Telegram"
    /// button is always available regardless.
    /// Shared `CIContext` for QR rasterization. Creating one is expensive
    /// (allocates a render pipeline), so reuse a single instance across renders.
    private static let qrContext = CIContext()

    private func qrImage(from string: String) -> UIImage? {
        guard !string.isEmpty else { return nil }
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 8, y: 8))
        guard let cgImage = Self.qrContext.createCGImage(scaled, from: scaled.extent) else { return nil }
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
