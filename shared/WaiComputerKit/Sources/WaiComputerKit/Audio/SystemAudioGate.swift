#if os(macOS)
import Foundation

/// Single source of truth for the macOS 14.2+ Core Audio Process Tap (CATap)
/// system-audio capability.
///
/// The app lowers its deployment floor below 14.2, so the CATap symbols
/// (`CATapDescription`, `AudioHardwareCreateProcessTap`, …) are weak-linked via
/// `-weak_framework CoreAudio -weak_framework AudioToolbox`. dyld binds weak
/// undefined symbols lazily, so the binary launches on macOS 13.0–14.1 even though
/// those symbols are absent there. Every `SystemAudioCapture`/`DualAudioCapture`
/// reference is already guarded by `@available(macOS 14.2, *)`, so the absent
/// symbols are never touched below 14.2; recording falls back to microphone-only
/// with explicit UI messaging (never a silent failure).
///
/// Use this flag — not an ad-hoc `#available` check — wherever the UI or recording
/// pipeline decides whether system-audio capture can be offered.
public enum SystemAudioGate {
    /// `true` when the OS is new enough for Core Audio Process Taps.
    public static var isSupported: Bool {
        if #available(macOS 14.2, *) { return true }
        return false
    }
}
#endif
