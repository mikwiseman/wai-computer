import Foundation
import CoreAudio
import os

private let watcherLog = Logger(subsystem: "is.waiwai.computer.app", category: "mic-usage")

/// Watches whether any OTHER process is capturing microphone input.
///
/// Meeting apps (Zoom, Meet in a browser, Teams, FaceTime) hold the mic for
/// the duration of a call and release it when the call ends. That release is
/// the strongest available "the call is over" signal on macOS, so the
/// recording flow feeds the transitions into `ConversationAutoStopMonitor`
/// as `noteCallActive` / `noteCallEnded`.
///
/// Uses the CoreAudio process-object API (macOS 14+). On failure or older
/// systems the watcher simply reports nothing — silence detection remains
/// the only end-of-conversation signal.
@available(macOS 14.0, *)
final class MicrophoneUsageWatcher {
    private var pollTask: Task<Void, Never>?

    /// Starts polling. `onChange` fires on transitions of "another process is
    /// capturing mic input", with the observation date. Delivered off-main.
    func start(
        interval: TimeInterval = 2.0,
        onChange: @escaping @Sendable (Bool, Date) -> Void
    ) {
        stop()
        pollTask = Task.detached(priority: .utility) {
            var lastActive: Bool?
            while !Task.isCancelled {
                if let active = Self.otherProcessIsCapturingInput() {
                    if active != lastActive {
                        if lastActive != nil || active {
                            onChange(active, Date())
                        }
                        lastActive = active
                    }
                }
                try? await Task.sleep(for: .seconds(interval))
            }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    deinit {
        pollTask?.cancel()
    }

    /// True when a process other than ours currently runs audio input.
    /// Returns nil when the process-object API is unavailable or errors.
    static func otherProcessIsCapturingInput() -> Bool? {
        guard let objects = processObjectIDs() else { return nil }
        let ownPid = ProcessInfo.processInfo.processIdentifier
        for object in objects {
            guard isRunningInput(object) else { continue }
            guard let pid = pid(of: object), pid != ownPid else { continue }
            return true
        }
        return false
    }

    // MARK: - CoreAudio process objects

    private static func processObjectIDs() -> [AudioObjectID]? {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyProcessObjectList,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var dataSize: UInt32 = 0
        let sizeStatus = AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize
        )
        guard sizeStatus == noErr, dataSize > 0 else {
            if sizeStatus != noErr {
                watcherLog.debug("Process object list size query failed status=\(sizeStatus, privacy: .public)")
            }
            return nil
        }

        let count = Int(dataSize) / MemoryLayout<AudioObjectID>.size
        var objects = [AudioObjectID](repeating: AudioObjectID(), count: count)
        let status = AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize, &objects
        )
        guard status == noErr else {
            watcherLog.debug("Process object list query failed status=\(status, privacy: .public)")
            return nil
        }
        return objects
    }

    private static func isRunningInput(_ object: AudioObjectID) -> Bool {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyIsRunningInput,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var value: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        let status = AudioObjectGetPropertyData(object, &address, 0, nil, &size, &value)
        return status == noErr && value != 0
    }

    private static func pid(of object: AudioObjectID) -> pid_t? {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyPID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var value: pid_t = 0
        var size = UInt32(MemoryLayout<pid_t>.size)
        let status = AudioObjectGetPropertyData(object, &address, 0, nil, &size, &value)
        guard status == noErr else { return nil }
        return value
    }
}
