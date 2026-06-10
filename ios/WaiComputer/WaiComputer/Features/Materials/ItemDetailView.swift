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
        .navigationTitle(item?.kind.capitalized ?? t("Item", "Материал"))
        .navigationBarTitleDisplayMode(.inline)
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

    private func content(_ item: Item) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                header(item)

                if item.state == "needs_input", item.summary?.summary == nil {
                    Text(t("Couldn't read this automatically — share the file or paste the text.",
                           "Не удалось прочитать автоматически — поделитесь файлом или вставьте текст."))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                if let summary = item.summary?.summary {
                    Text(summary)
                        .font(Typography.body)
                        .foregroundStyle(Palette.textSecondary)
                        .textSelection(.enabled)
                }

                let keyMoments = item.summary?.keyMoments ?? []
                if !keyMoments.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text(t("Key moments", "Ключевые моменты")).font(Typography.headingSmall)
                        ForEach(keyMoments) { moment in
                            keyMomentRow(moment)
                        }
                    }
                }

                let keyPoints = item.summary?.keyPoints ?? []
                if !keyPoints.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Key points", "Главное")).font(Typography.headingSmall)
                        ForEach(Array(keyPoints.enumerated()), id: \.offset) { _, point in
                            HStack(alignment: .top, spacing: Spacing.xs) {
                                Text("•").foregroundStyle(Palette.textTertiary)
                                Text(point).font(Typography.bodySmall)
                            }
                        }
                    }
                }

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
                                    .padding(.horizontal, Spacing.sm).padding(.vertical, Spacing.xxs)
                                    .background(Palette.surfaceSubtle)
                                    .clipShape(Capsule())
                            }
                        }
                    }
                }

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
            Text(item.kind.uppercased())
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
        isLoading = true
        defer { isLoading = false }
        do {
            item = try await apiClient.getItem(id: itemId)
        } catch {
            errorMessage = error.localizedDescription
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
            errorMessage = error.localizedDescription
        }
    }
}
