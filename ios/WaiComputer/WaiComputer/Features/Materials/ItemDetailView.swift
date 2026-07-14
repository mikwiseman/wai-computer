import AVFoundation
import SwiftUI
import WaiComputerKit

/// Detail screen for one Item: title, summary, the key-moments table, key points.
/// Loads the full item (with summary) on appear from a lightweight list entry.
struct ItemDetailView: View {
    let itemId: String
    let apiClient: APIClient
    var onDeleted: (() -> Void)?

    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var item: Item?
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var isGeneratingAudio = false
    @State private var isDownloadingAudio = false
    @State private var isPlayingAudio = false
    @State private var audioPlayer: AVAudioPlayer?
    @State private var audioPlaybackToken = UUID()

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private var isRegularWidth: Bool {
        horizontalSizeClass == .regular
    }

    var body: some View {
        Group {
            if let item {
                content(item)
            } else if isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ContentUnavailableViewCompat(
                    t("Couldn't load", "Не удалось загрузить"),
                    systemImage: "exclamationmark.triangle",
                    description: Text(errorMessage ?? t("Try again.", "Попробуйте снова."))
                )
            }
        }
        .navigationTitle(
            item.flatMap { ItemKindLabel.text($0.kind, language: languageManager.current) }
                ?? t("Item", "Материал")
        )
        .navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)
        .toolbar {
            if item != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .destructive) {
                        Task { await delete() }
                    } label: {
                        Image(systemName: "trash")
                    }
                }
            }
        }
        .task { await load() }
    }

    @ViewBuilder
    private func content(_ item: Item) -> some View {
        if isRegularWidth {
            regularItemDetailLayout(item)
        } else {
            compactItemDetailLayout(item)
        }
    }

    private func regularItemDetailLayout(_ item: Item) -> some View {
        List {
            regularHeader(item)
                .frame(maxWidth: 760, alignment: .leading)
                .iosItemDetailListRow()
                .accessibilityIdentifier("ios-item-detail-regular-header")

            if item.state == "needs_input", item.summary?.summary == nil {
                needsInputBanner
                    .frame(maxWidth: 760, alignment: .leading)
                    .iosItemDetailListRow()
            }

            summarySection(item)
                .frame(maxWidth: 760, alignment: .leading)
                .iosItemDetailListRow()

            originalMaterialSection(item)
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("ios-item-detail-regular-layout")
    }

    private func compactItemDetailLayout(_ item: Item) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                header(item)

                if item.state == "needs_input", item.summary?.summary == nil {
                    Text(t("Couldn't read this automatically — share the file or paste the text.",
                           "Не удалось прочитать автоматически — поделитесь файлом или вставьте текст."))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                summaryText(item)
                keyMomentsSection(item)
                keyPointsSection(item)
                topicsSection(item)

                if item.summary?.summary != nil {
                    summaryAudioControl(item)
                }

                if let body = item.body, !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Label(t("Original Material", "Исходный материал"), systemImage: "doc.text")
                            .font(Typography.headingSmall)
                        Text(body)
                            .font(Typography.reading)
                            .lineSpacing(6)
                            .textSelection(.enabled)
                            .foregroundStyle(Palette.textPrimary)
                    }
                }
            }
            .padding(Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func regularHeader(_ item: Item) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(ItemKindLabel.text(item.kind, language: languageManager.current) ?? item.kind)
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
            Text(item.title ?? t("Untitled", "Без названия"))
                .font(Typography.displaySmall)
                .textSelection(.enabled)
            Text(itemSubtitle(item))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
        }
    }

    private var needsInputBanner: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "doc.badge.ellipsis")
                .foregroundStyle(Palette.accent)
            Text(t(
                "Couldn't read this automatically. Share the file again or paste the text.",
                "Не удалось прочитать автоматически. Поделитесь файлом снова или вставьте текст."
            ))
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.textSecondary)
        }
        .padding(Spacing.md)
        .background(Palette.accentSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func summarySection(_ item: Item) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label(t("Summary", "Сводка"), systemImage: "doc.text.magnifyingglass")
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)

            if hasUsefulSummary(item) {
                if item.summary?.summary != nil {
                    summaryAudioControl(item)
                }

                summaryText(item)
                keyPointsSection(item)
                keyMomentsSection(item)
                topicsSection(item)
            } else if item.status == "failed" {
                failedSummaryBanner(item)
            } else {
                HStack(alignment: .center, spacing: Spacing.sm) {
                    if item.status == "fetching" || item.status == "summarizing" {
                        ProgressView().controlSize(.small)
                    }
                    Text(summaryPlaceholder(item))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }
                .padding(Spacing.md)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .accessibilityIdentifier("ios-item-detail-summary-section")
    }

    @ViewBuilder
    private func originalMaterialSection(_ item: Item) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label(t("Original Material", "Исходный материал"), systemImage: "doc.text")
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)

            sourceMetadata(item)
        }
        .frame(maxWidth: 760, alignment: .leading)
        .iosItemDetailListRow()
        .accessibilityIdentifier("ios-item-detail-original-section")

        if let body = item.body, !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            Text(body)
                .font(Typography.reading)
                .lineSpacing(6)
                .textSelection(.enabled)
                .foregroundStyle(Palette.textPrimary)
                .frame(maxWidth: 760, alignment: .leading)
                .iosItemDetailListRow()
        } else {
            Text(t(
                "Original text is not available in this item yet.",
                "Исходный текст этого материала пока недоступен."
            ))
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.textSecondary)
            .frame(maxWidth: 760, alignment: .leading)
            .iosItemDetailListRow()
        }
    }

    @ViewBuilder
    private func summaryText(_ item: Item) -> some View {
        if let summary = item.summary?.summary?.trimmingCharacters(in: .whitespacesAndNewlines),
           !summary.isEmpty {
            Text(summary)
                .font(isRegularWidth ? Typography.reading : Typography.body)
                .lineSpacing(isRegularWidth ? 6 : 0)
                .foregroundStyle(isRegularWidth ? Palette.textPrimary : Palette.textSecondary)
                .textSelection(.enabled)
        }
    }

    @ViewBuilder
    private func keyMomentsSection(_ item: Item) -> some View {
        let keyMoments = item.summary?.keyMoments ?? []
        if !keyMoments.isEmpty {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                Text(t("Key moments", "Ключевые моменты"))
                    .font(Typography.headingSmall)
                ForEach(keyMoments) { moment in
                    keyMomentRow(moment)
                }
            }
        }
    }

    @ViewBuilder
    private func keyPointsSection(_ item: Item) -> some View {
        let keyPoints = item.summary?.keyPoints ?? []
        if !keyPoints.isEmpty {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Key points", "Главное"))
                    .font(isRegularWidth ? Typography.bodySmall.weight(.semibold) : Typography.headingSmall)
                ForEach(Array(keyPoints.enumerated()), id: \.offset) { _, point in
                    HStack(alignment: .top, spacing: Spacing.xs) {
                        if isRegularWidth {
                            Circle()
                                .fill(Palette.accent)
                                .frame(width: 5, height: 5)
                                .padding(.top, 7)
                        } else {
                            Text("•").foregroundStyle(Palette.textTertiary)
                        }
                        Text(point)
                            .font(Typography.bodySmall)
                            .lineSpacing(isRegularWidth ? 4 : 0)
                            .textSelection(.enabled)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func topicsSection(_ item: Item) -> some View {
        let topics = item.summary?.topics ?? []
        if !topics.isEmpty {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                Text(t("Topics", "Темы")).waiSectionHeader()
                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 96), spacing: 6, alignment: .leading)],
                    alignment: .leading, spacing: 6
                ) {
                    ForEach(topics, id: \.self) { topic in
                        Text(topic)
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.textSecondary)
                            .padding(.horizontal, Spacing.sm)
                            .padding(.vertical, Spacing.xxs)
                            .background(Palette.surfaceSubtle)
                            .clipShape(Capsule())
                    }
                }
            }
        }
    }

    private func failedSummaryBanner(_ item: Item) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(alignment: .top, spacing: Spacing.sm) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(Palette.recording)
                Text(t("Couldn't summarize this item.", "Не удалось обработать материал."))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textPrimary)
            }
            if let message = item.error?.message, !message.isEmpty {
                Text(message)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(Spacing.md)
        .background(Palette.recording.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func summaryPlaceholder(_ item: Item) -> String {
        switch item.status {
        case "fetching":
            return t("Reading the source material…", "Читаем исходный материал…")
        case "summarizing":
            return t("Building the summary…", "Готовим сводку…")
        default:
            return t("No summary yet.", "Сводки пока нет.")
        }
    }

    private func hasUsefulSummary(_ item: Item) -> Bool {
        let text = item.summary?.summary?.trimmingCharacters(in: .whitespacesAndNewlines)
        return !(text?.isEmpty ?? true)
            || !(item.summary?.keyPoints?.isEmpty ?? true)
            || !(item.summary?.keyMoments?.isEmpty ?? true)
            || !(item.summary?.topics?.isEmpty ?? true)
    }

    @ViewBuilder
    private func summaryAudioControl(_ item: Item) -> some View {
        let audio = item.summaryAudio
        VStack(alignment: .leading, spacing: Spacing.xs) {
            if audio?.status == "succeeded" {
                Button {
                    Task { await playOrStopAudio() }
                } label: {
                    HStack(spacing: 6) {
                        if isDownloadingAudio {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: isPlayingAudio ? "stop.fill" : "play.fill")
                        }
                        Text(isPlayingAudio ? t("Stop", "Стоп") : t("Play summary", "Слушать сводку"))
                    }
                }
                .buttonStyle(.bordered)
                .disabled(isDownloadingAudio)
            } else if isGeneratingAudio || audio?.isActive == true {
                HStack(spacing: Spacing.sm) {
                    ProgressView().controlSize(.small)
                    Text(t("Generating audio…", "Создаю аудио…"))
                        .font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
                }
            } else {
                Button {
                    Task { await generateAndPollAudio() }
                } label: {
                    Label(t("Create Audio", "Создать аудио"), systemImage: "waveform")
                }
                .buttonStyle(.bordered)
                if audio?.isFailed == true {
                    Text(t("Audio generation failed.", "Не удалось создать аудио."))
                        .font(Typography.labelSmall).foregroundStyle(.red)
                }
            }
        }
    }

    private func header(_ item: Item) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(ItemKindLabel.text(item.kind, language: languageManager.current) ?? item.kind)
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
            Text(item.title ?? t("Untitled", "Без названия"))
                .font(Typography.displaySmall)
                .textSelection(.enabled)
            if let url = item.url, let dest = URL(string: url) {
                Link(url, destination: dest)
                    .font(Typography.bodySmall)
                    .lineLimit(1)
            }
        }
    }

    private func sourceMetadata(_ item: Item) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            metadataLine(title: t("Source", "Источник"), value: sourceLabel(item.source))
            if let sourceRef = item.sourceRef, !sourceRef.isEmpty {
                metadataLine(title: t("Reference", "Ссылка-источник"), value: sourceRef)
            }
            if let url = item.url, let destination = URL(string: url) {
                HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                    Text("URL")
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                        .frame(width: 116, alignment: .leading)
                    Link(url, destination: destination)
                        .font(Typography.bodySmall)
                        .lineLimit(1)
                }
            }
            metadataLine(title: t("Created", "Создано"), value: formattedDate(item.createdAt))
        }
    }

    private func metadataLine(title: String, value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
            Text(title)
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
                .frame(width: 116, alignment: .leading)
            Text(value)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
                .textSelection(.enabled)
        }
    }

    private func itemSubtitle(_ item: Item) -> String {
        var pieces = [sourceLabel(item.source)]
        if let status = statusLabel(item.status) {
            pieces.append(status)
        }
        pieces.append(formattedDate(item.occurredAt ?? item.createdAt))
        return pieces
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " / ")
    }

    private func sourceLabel(_ source: String) -> String {
        if source.hasPrefix("mcp:") {
            return t("Connected source", "Подключённый источник")
        }
        switch source {
        case "url":
            return t("Link", "Ссылка")
        case "paste":
            return t("Pasted text", "Вставленный текст")
        case "upload":
            return t("Upload", "Файл")
        case "telegram":
            return "Telegram"
        default:
            return source
        }
    }

    private func statusLabel(_ status: String) -> String? {
        switch status {
        case "ready":
            return nil
        case "fetching":
            return t("Fetching", "Загружается")
        case "summarizing":
            return t("Summarizing", "Обрабатывается")
        case "failed":
            return t("Failed", "Ошибка")
        case "needs_input":
            return t("Needs input", "Нужны данные")
        default:
            return status
        }
    }

    private static let isoWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let isoPlain: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private func formattedDate(_ iso: String) -> String {
        guard let date = Self.isoWithFractionalSeconds.date(from: iso)
            ?? Self.isoPlain.date(from: iso) else {
            return iso
        }
        return IOSDateFormatting.listTimestamp(
            from: date,
            language: languageManager.current
        )
    }

    private func keyMomentRow(_ moment: KeyMoment) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Text(moment.timestamp ?? "—")
                .font(Typography.mono)
                .foregroundStyle(Palette.accent)
                .frame(width: 56, alignment: .leading)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(moment.moment).font(Typography.bodySmall.weight(.medium))
                Text(moment.whyItMatters)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    private func load() async {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            item = IOSScreenshotFixtures.item(id: itemId)
            errorMessage = nil
            isLoading = false
            return
        }
        #endif

        isLoading = true
        defer { isLoading = false }
        do {
            item = try await apiClient.getItem(id: itemId)
        } catch {
            errorMessage = error.userFacingMessage(context: .library)
        }
    }

    private func generateAndPollAudio() async {
        isGeneratingAudio = true
        defer { isGeneratingAudio = false }
        do {
            let state = try await apiClient.startItemSummaryAudio(itemId: itemId)
            item = item?.withSummaryAudio(state)
            // Poll until the generation reaches a terminal state.
            while !Task.isCancelled, item?.summaryAudio?.isActive == true {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled else { return }
                if let refreshed = try? await apiClient.getItem(id: itemId) {
                    item = refreshed
                }
            }
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
        }
    }

    private func playOrStopAudio() async {
        if isPlayingAudio {
            audioPlaybackToken = UUID()
            audioPlayer?.stop()
            audioPlayer = nil
            isPlayingAudio = false
            return
        }

        isDownloadingAudio = true
        defer { isDownloadingAudio = false }
        do {
            let data = try await apiClient.downloadItemSummaryAudio(itemId: itemId)
            try AVAudioSession.sharedInstance().setCategory(.playback)
            try AVAudioSession.sharedInstance().setActive(true)
            let player = try AVAudioPlayer(data: data)
            player.prepareToPlay()
            guard player.play() else { return }
            audioPlayer?.stop()
            audioPlayer = player
            isPlayingAudio = true

            let token = UUID()
            audioPlaybackToken = token
            let duration = max(player.duration, 0)
            Task { @MainActor in
                if duration > 0 {
                    try? await Task.sleep(nanoseconds: UInt64((duration + 0.25) * 1_000_000_000))
                } else {
                    try? await Task.sleep(for: .seconds(1))
                }
                guard audioPlaybackToken == token else { return }
                isPlayingAudio = false
                audioPlayer = nil
            }
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
        }
    }

    private func delete() async {
        do {
            try await apiClient.deleteItem(id: itemId)
            onDeleted?()
            dismiss()
        } catch {
            errorMessage = error.userFacingMessage(context: .library)
        }
    }
}

private extension View {
    func iosItemDetailListRow() -> some View {
        self
            .padding(.vertical, Spacing.sm)
            .listRowInsets(EdgeInsets(
                top: Spacing.xs,
                leading: Spacing.xl,
                bottom: Spacing.xs,
                trailing: Spacing.xl
            ))
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
    }
}
