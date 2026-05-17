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
        HStack(alignment: .center, spacing: Spacing.md) {
            ZStack {
                Circle()
                    .stroke(Color.red.opacity(0.6), lineWidth: 1.5)
                    .frame(width: 22, height: 22)
                Image(systemName: "exclamationmark")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color.red.opacity(0.9))
            }

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.white)
                Text(subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color.white.opacity(0.55))
                    .lineLimit(1)
            }

            Spacer(minLength: Spacing.lg)

            Button(action: onPrimaryTap) {
                Text(actionLabel)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color.black)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: 999, style: .continuous)
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
            .accessibilityLabel("Dismiss")
            .accessibilityIdentifier("permission-banner-\(kind.identifierSuffix)-dismiss")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color.black.opacity(0.92))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.white.opacity(0.06), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.35), radius: 22, y: 8)
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
        case .microphone: return "WaiComputer needs microphone access to record."
        case .accessibility: return "WaiComputer needs accessibility access for the global hotkey and text insertion."
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
    .background(Color.gray.opacity(0.1))
}
