import SwiftUI
import AVFoundation
import ApplicationServices
import WaiComputerKit

/// Wispr Flow-style toast banner that appears at the bottom of the main window
/// when a required permission is missing. Non-blocking — the main UI stays
/// fully usable behind it. Auto-dismisses when the permission is granted.
struct PermissionBanner: View {
    enum Kind: Equatable {
        case microphone
        case accessibility
    }

    let kind: Kind
    let onPrimaryTap: () -> Void
    let onDismiss: () -> Void
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            ZStack {
                Circle()
                    .stroke(Palette.danger.opacity(0.6), lineWidth: 1.5)
                    .frame(width: 22, height: 22)
                Image(systemName: "exclamationmark")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Palette.danger.opacity(0.9))
            }

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.white)
                Text(subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color.white.opacity(0.55))
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: Spacing.lg)

            Button(action: onPrimaryTap) {
                Text(actionLabel)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color.black)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(
                        Capsule(style: .continuous)
                            .fill(Color.white.opacity(0.95))
                    )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("permission-banner-\(kind.identifierSuffix)-action")

            Button(action: onDismiss) {
                ZStack {
                    Circle()
                        .fill(Color.white.opacity(0.12))
                        .frame(width: 22, height: 22)
                    Image(systemName: "xmark")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(Color.white.opacity(0.85))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(t("Dismiss", "Закрыть"))
            .accessibilityIdentifier("permission-banner-\(kind.identifierSuffix)-dismiss")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background {
            // Liquid Glass on Tahoe keeps the dark-HUD register via a dark
            // tint (white copy stays readable); earlier systems keep the
            // original near-black fill.
            if #available(macOS 26.0, *) {
                Color.clear.glassEffect(
                    .regular.tint(Color.black.opacity(0.6)),
                    in: .rect(cornerRadius: Radius.xl)
                )
            } else {
                RoundedRectangle(cornerRadius: Radius.xl, style: .continuous)
                    .fill(Color.black.opacity(0.92))
            }
        }
        .overlay(
            RoundedRectangle(cornerRadius: Radius.xl, style: .continuous)
                .strokeBorder(Color.white.opacity(0.06), lineWidth: 1)
        )
        .waiShadow(.floating)
        .accessibilityIdentifier("permission-banner-\(kind.identifierSuffix)")
    }

    private var title: String {
        switch kind {
        case .microphone:
            return t("Microphone permission required", "Нужен доступ к микрофону")
        case .accessibility:
            return t("Accessibility permission required", "Нужен Универсальный доступ")
        }
    }

    private var subtitle: String {
        switch kind {
        case .microphone:
            return t(
                "WaiComputer needs microphone access to record.",
                "WaiComputer нужен микрофон для диктовки и записей."
            )
        case .accessibility:
            return t(
                "WaiComputer needs accessibility access for the global hotkey and text insertion.",
                "Универсальный доступ нужен для глобальной клавиши и вставки текста."
            )
        }
    }

    private var actionLabel: String {
        switch kind {
        case .microphone:
            return AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined
                ? t("Grant Permission", "Разрешить")
                : t("Open Settings", "Открыть настройки")
        case .accessibility:
            return AXIsProcessTrusted()
                ? t("Open Settings", "Открыть настройки")
                : t("Grant Permission", "Разрешить")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

extension PermissionBanner.Kind {
    var identifierSuffix: String {
        switch self {
        case .microphone: return "microphone"
        case .accessibility: return "accessibility"
        }
    }
}

#Preview {
    VStack(spacing: 12) {
        PermissionBanner(kind: .microphone, onPrimaryTap: {}, onDismiss: {})
        PermissionBanner(kind: .accessibility, onPrimaryTap: {}, onDismiss: {})
    }
    .padding()
    .frame(width: 600)
    .background(Color.gray.opacity(0.1))
    .environmentObject(LanguageManager.shared)
}
