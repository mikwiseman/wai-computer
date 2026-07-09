import SwiftUI
import WaiComputerKit

/// Inline banner for transient status and error messages above list content.
///
/// Success/info banners auto-dismiss after `autoDismissAfter` seconds so the
/// user never has to close confirmations by hand; errors pass `nil` and stay
/// until dismissed (mirrors the web Toast contract in `web/src/components/Toast.tsx`).
struct InlineStatusBanner: View {
    @EnvironmentObject private var languageManager: LanguageManager

    static let statusDismissDelay: TimeInterval = 4

    let systemImage: String
    let message: String
    let color: Color
    var autoDismissAfter: TimeInterval?
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: systemImage)
                .foregroundStyle(color)
            Text(message)
                .font(Typography.bodySmall)
                .foregroundStyle(color)
                .lineLimit(3)
                .textSelection(.enabled)
            Spacer()
            Button(action: onDismiss) {
                Image(systemName: "xmark")
            }
            .buttonStyle(.plain)
            .help(OnboardingL10n.text("Dismiss", "Закрыть", language: languageManager.current))
            .accessibilityLabel(OnboardingL10n.text("Dismiss", "Закрыть", language: languageManager.current))
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
        .background(Palette.surfaceSubtle)
        .transition(.opacity)
        .task(id: message) {
            guard let delay = autoDismissAfter else { return }
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            onDismiss()
        }
    }
}
