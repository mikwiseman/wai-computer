import SwiftUI
import AVFoundation
import ApplicationServices

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

    var body: some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: "exclamationmark.circle.fill")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.recording)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(Typography.headingSmall)
                    .foregroundStyle(Palette.textPrimary)
                Text(subtitle)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }

            Spacer(minLength: Spacing.lg)

            Button(action: onPrimaryTap) {
                Text(actionLabel)
                    .font(Typography.bodySmall.weight(.medium))
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.regular)
            .accessibilityIdentifier("permission-banner-\(kind.identifierSuffix)-action")

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Palette.textSecondary)
                    .frame(width: 22, height: 22)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss")
            .accessibilityIdentifier("permission-banner-\(kind.identifierSuffix)-dismiss")
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm + 2)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.18), radius: 12, y: 4)
        .accessibilityIdentifier("permission-banner-\(kind.identifierSuffix)")
    }

    private var title: String {
        switch kind {
        case .microphone: return "Microphone permission required"
        case .accessibility: return "Accessibility permission required"
        }
    }

    private var subtitle: String {
        switch kind {
        case .microphone: return "WaiSay needs microphone access to record."
        case .accessibility: return "WaiSay needs accessibility access to insert dictated text."
        }
    }

    private var actionLabel: String {
        switch kind {
        case .microphone:
            return AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined
                ? "Grant Permission"
                : "Open Settings"
        case .accessibility:
            return AXIsProcessTrusted() ? "Open Settings" : "Grant Permission"
        }
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
}
