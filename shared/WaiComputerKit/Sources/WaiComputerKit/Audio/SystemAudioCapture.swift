#if os(macOS)
import Foundation
import AVFoundation
import CoreAudio
import AudioToolbox
import os
import Darwin.os
import Sentry

private let sysLog = Logger(subsystem: "is.waiwai.computer.kit", category: "system-audio")

/// Captures system audio output using Core Audio Process Taps (macOS 14.2+).
///
/// Produces `AsyncStream<AVAudioPCMBuffer>` at 16kHz mono, matching
/// the same interface pattern as `MicrophoneCapture`.
@available(macOS 14.2, *)
public final class SystemAudioCapture: AudioCaptureProtocol, @unchecked Sendable {
    private let config: AudioCaptureConfig

    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    /// Lock protecting `bufferContinuation` from concurrent access between the
    /// real-time audio IO proc thread and the main/caller thread.
    private let continuationLock: UnsafeMutablePointer<os_unfair_lock>
    public private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>

    private var _isCapturing = false
    public var isCapturing: Bool { _isCapturing }

    // Core Audio resources to clean up
    private var tapID: AudioObjectID = AudioObjectID.max
    private var aggregateDeviceID: AudioObjectID = AudioObjectID.max
    private var ioProcID: AudioDeviceIOProcID?

    // Audio flow verification — uses raw pointers for real-time thread safety (no locks)
    /// Atomic flag: 0 = no buffers received, 1 = at least one buffer received.
    /// Written from the real-time IO thread, read from any thread.
    private let _bufferReceivedFlag: UnsafeMutablePointer<Int32> = {
        let p = UnsafeMutablePointer<Int32>.allocate(capacity: 1)
        p.initialize(to: 0)
        return p
    }()

    /// Atomic flag: 0 = no audio received, 1 = non-zero audio received.
    /// Written from the real-time IO thread, read from any thread.
    private let _audioReceivedFlag: UnsafeMutablePointer<Int32> = {
        let p = UnsafeMutablePointer<Int32>.allocate(capacity: 1)
        p.initialize(to: 0)
        return p
    }()

    /// `true` once the IOProc has received at least one buffer containing non-zero audio samples.
    public var hasReceivedAudio: Bool {
        OSAtomicAdd32(0, _audioReceivedFlag) != 0
    }

    /// `true` once the IOProc has received at least one buffer, even if it is silent.
    public var hasReceivedBuffers: Bool {
        OSAtomicAdd32(0, _bufferReceivedFlag) != 0
    }

    private static let audioPresenceThreshold: Float = 0.000_001

    public init(config: AudioCaptureConfig = .default) {
        self.config = config
        self.continuationLock = .allocate(capacity: 1)
        self.continuationLock.initialize(to: os_unfair_lock())
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        self.audioBuffers = stream
        self.bufferContinuation = continuation
    }

    public var isRecording: Bool { isCapturing }

    private func setupBufferStream() {
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        audioBuffers = stream
        os_unfair_lock_lock(continuationLock)
        bufferContinuation = continuation
        os_unfair_lock_unlock(continuationLock)
    }

    /// Start capturing system audio.
    public func startCapture() throws {
        if _isCapturing {
            sysLog.warning("[SysAudio] startCapture called while already capturing -- stopping first")
            stopCapture()
        }

        // 1. Get the default output device
        var defaultOutputID = AudioObjectID(kAudioObjectSystemObject)
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultOutputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var dataSize = UInt32(MemoryLayout<AudioObjectID>.size)
        var status = AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &propertyAddress,
            0, nil,
            &dataSize,
            &defaultOutputID
        )
        guard status == noErr else {
            throw SystemAudioCaptureError.failedToGetDefaultOutput(status)
        }
        sysLog.warning("[SysAudio] Default output device ID: \(defaultOutputID)")

        // 2. Get the output device UID before creating the tap. The tap should
        // explicitly target the device currently receiving browser/meeting audio.
        var uid: CFString?
        var uidAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceUID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var uidSize = UInt32(MemoryLayout<CFString?>.size)
        status = withUnsafeMutablePointer(to: &uid) { uidPointer in
            AudioObjectGetPropertyData(defaultOutputID, &uidAddress, 0, nil, &uidSize, uidPointer)
        }
        guard status == noErr, let uid else {
            throw SystemAudioCaptureError.failedToGetDeviceUID(status)
        }
        sysLog.warning("[SysAudio] Output device UID: \(uid as String)")

        // Use a global tap here: the include-list initializer with an empty array captures nothing.
        let tapDescription = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
        tapDescription.uuid = UUID()
        tapDescription.muteBehavior = .unmuted
        tapDescription.deviceUID = uid as String

        var newTapID = AudioObjectID.max
        status = AudioHardwareCreateProcessTap(tapDescription, &newTapID)
        guard status == noErr else {
            throw SystemAudioCaptureError.failedToCreateTap(status)
        }
        tapID = newTapID
        sysLog.warning("[SysAudio] Created process tap ID: \(self.tapID)")

        // 4. Create aggregate device containing the tap
        let aggregateDesc: [String: Any] = [
            kAudioAggregateDeviceNameKey: "WaiSystemAudioTap",
            kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceMainSubDeviceKey: uid as String,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [
                [kAudioSubDeviceUIDKey: uid as String]
            ],
            kAudioAggregateDeviceTapListKey: [
                [
                    kAudioSubTapDriftCompensationKey: true,
                    kAudioSubTapUIDKey: tapDescription.uuid.uuidString
                ]
            ]
        ]
        var newAggregateID = AudioObjectID.max
        status = AudioHardwareCreateAggregateDevice(aggregateDesc as CFDictionary, &newAggregateID)
        guard status == noErr else {
            destroyTap()
            throw SystemAudioCaptureError.failedToCreateAggregateDevice(status)
        }
        aggregateDeviceID = newAggregateID
        sysLog.warning("[SysAudio] Created aggregate device ID: \(self.aggregateDeviceID)")

        // 5. Query the aggregate device's input stream format to get native sample rate
        // The tap provides audio on the INPUT scope of the aggregate device.
        // Try input scope first (correct for tapped audio), fall back to output if needed.
        var inputStreamFormat = AudioStreamBasicDescription()
        var formatAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreamFormat,
            mScope: kAudioObjectPropertyScopeInput,
            mElement: kAudioObjectPropertyElementMain
        )
        var formatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        status = AudioObjectGetPropertyData(
            aggregateDeviceID,
            &formatAddress,
            0, nil,
            &formatSize,
            &inputStreamFormat
        )

        let nativeSR: Double
        let nativeCh: UInt32
        if status == noErr && inputStreamFormat.mSampleRate > 0 {
            nativeSR = inputStreamFormat.mSampleRate
            nativeCh = inputStreamFormat.mChannelsPerFrame
            sysLog.warning("[SysAudio] Native input format: \(nativeSR)Hz, \(nativeCh)ch")
        } else {
            // Input scope query failed — try output scope (some aggregate devices expose format there)
            sysLog.warning("[SysAudio] Input scope format query failed (status \(status)), trying output scope...")
            var outputFormatAddress = AudioObjectPropertyAddress(
                mSelector: kAudioDevicePropertyStreamFormat,
                mScope: kAudioObjectPropertyScopeOutput,
                mElement: kAudioObjectPropertyElementMain
            )
            var outputStreamFormat = AudioStreamBasicDescription()
            var outputFormatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
            let outputStatus = AudioObjectGetPropertyData(
                aggregateDeviceID,
                &outputFormatAddress,
                0, nil,
                &outputFormatSize,
                &outputStreamFormat
            )
            if outputStatus == noErr && outputStreamFormat.mSampleRate > 0 {
                nativeSR = outputStreamFormat.mSampleRate
                nativeCh = outputStreamFormat.mChannelsPerFrame
                sysLog.warning("[SysAudio] Output scope format: \(nativeSR)Hz, \(nativeCh)ch")
            } else {
                // Fall back to querying the original output device directly
                var deviceFormatAddress = AudioObjectPropertyAddress(
                    mSelector: kAudioDevicePropertyNominalSampleRate,
                    mScope: kAudioObjectPropertyScopeGlobal,
                    mElement: kAudioObjectPropertyElementMain
                )
                var deviceSR: Float64 = 0
                var deviceSRSize = UInt32(MemoryLayout<Float64>.size)
                let deviceStatus = AudioObjectGetPropertyData(
                    defaultOutputID,
                    &deviceFormatAddress,
                    0, nil,
                    &deviceSRSize,
                    &deviceSR
                )
                if deviceStatus == noErr && deviceSR > 0 {
                    nativeSR = deviceSR
                    nativeCh = 2 // stereo is safe default for output devices
                    sysLog.warning("[SysAudio] Using output device sample rate: \(nativeSR)Hz, assuming \(nativeCh)ch")
                } else {
                    nativeSR = 48000
                    nativeCh = 2
                    sysLog.warning("[SysAudio] All format queries failed, assuming \(nativeSR)Hz \(nativeCh)ch")
                }
            }
        }

        // 6. Set up IO proc to receive audio buffers
        guard let targetFormat = config.format else {
            destroyAggregateDevice()
            destroyTap()
            throw AudioCaptureError.invalidFormat
        }
        let targetSR = config.sampleRate
        var tapCount = 0

        var procID: AudioDeviceIOProcID?
        status = AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateDeviceID, nil) {
            [weak self] _, inInputData, _, _, _ in
            guard let self = self else { return }
            tapCount += 1

            let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inInputData))
            guard !buffers.isEmpty else { return }

            let declaredChannels = Int(max(nativeCh, 1))
            let sourceChannels = buffers.count > 1 ? buffers.count : declaredChannels
            guard sourceChannels > 0 else { return }

            var srcFrames = 0
            if buffers.count > 1 {
                var minFrames = Int.max
                for channelIndex in 0..<sourceChannels {
                    guard channelIndex < buffers.count, buffers[channelIndex].mData != nil else { return }
                    let framesInBuffer = Int(buffers[channelIndex].mDataByteSize) / MemoryLayout<Float>.size
                    minFrames = min(minFrames, framesInBuffer)
                }
                srcFrames = minFrames == Int.max ? 0 : minFrames
            } else {
                guard buffers[0].mData != nil else { return }
                let totalSamples = Int(buffers[0].mDataByteSize) / MemoryLayout<Float>.size
                srcFrames = totalSamples / sourceChannels
            }
            if srcFrames == 0 { return }

            func sourceSample(frame: Int, channel: Int) -> Float {
                if buffers.count > 1 {
                    let audioBuffer = buffers[min(channel, buffers.count - 1)]
                    guard let dataPtr = audioBuffer.mData else { return 0 }
                    return dataPtr.assumingMemoryBound(to: Float.self)[frame]
                }

                guard let dataPtr = buffers[0].mData else { return 0 }
                let srcSamples = dataPtr.assumingMemoryBound(to: Float.self)
                return srcSamples[frame * sourceChannels + min(channel, sourceChannels - 1)]
            }

            // Downsample from native rate to target rate (16kHz), mix to mono
            let ratio = nativeSR / targetSR
            let outFrames = Int(Double(srcFrames) / ratio)
            if outFrames == 0 { return }
            OSAtomicCompareAndSwap32(0, 1, self._bufferReceivedFlag)

            guard let outBuffer = AVAudioPCMBuffer(
                pcmFormat: targetFormat,
                frameCapacity: AVAudioFrameCount(outFrames)
            ) else {
                if tapCount <= 5 { sysLog.error("[SysAudio] Failed to create output buffer") }
                return
            }
            outBuffer.frameLength = AVAudioFrameCount(outFrames)

            guard let outData = outBuffer.floatChannelData else { return }
            let dst = outData[0]

            let channels = sourceChannels

            if ratio <= 1.01 && channels == 1 {
                // No resampling or mixing needed
                for i in 0..<outFrames {
                    dst[i] = sourceSample(frame: i, channel: 0)
                }
            } else {
                // Downsample with averaging + mono mixdown
                let intRatio = max(1, Int(ratio.rounded()))
                for i in 0..<outFrames {
                    let srcStart = Int(Double(i) * ratio)
                    if srcStart >= srcFrames {
                        dst[i] = 0
                        continue
                    }
                    var sum: Float = 0
                    let count = min(intRatio, srcFrames - srcStart)
                    guard count > 0 else {
                        dst[i] = 0
                        continue
                    }
                    for j in 0..<count {
                        // Average across channels for mono mixdown
                        var sampleSum: Float = 0
                        for ch in 0..<channels {
                            sampleSum += sourceSample(frame: srcStart + j, channel: ch)
                        }
                        sum += sampleSum / Float(channels)
                    }
                    dst[i] = sum / Float(count)
                }
            }

            if tapCount <= 5 || tapCount % 100 == 0 {
                sysLog.warning("[SysAudio] Tap #\(tapCount): \(srcFrames)@\(nativeSR)Hz, buffers=\(buffers.count), channels=\(sourceChannels) -> \(outFrames)@\(targetSR)Hz")
            }

            // Mark audio as flowing once we see any non-zero sample (lock-free, real-time safe)
            if OSAtomicAdd32(0, self._audioReceivedFlag) == 0 {
                var foundNonZero = false
                for i in 0..<outFrames {
                    if abs(dst[i]) > Self.audioPresenceThreshold {
                        foundNonZero = true
                        break
                    }
                }
                if foundNonZero {
                    OSAtomicCompareAndSwap32(0, 1, self._audioReceivedFlag)
                    sysLog.warning("[SysAudio] First non-zero audio received at tap #\(tapCount)")
                }
            }

            os_unfair_lock_lock(self.continuationLock)
            self.bufferContinuation?.yield(outBuffer)
            os_unfair_lock_unlock(self.continuationLock)
        }
        guard status == noErr, let validProcID = procID else {
            destroyAggregateDevice()
            destroyTap()
            throw SystemAudioCaptureError.failedToCreateIOProc(status)
        }
        ioProcID = validProcID

        // 7. Start the device
        status = AudioDeviceStart(aggregateDeviceID, validProcID)
        guard status == noErr else {
            destroyIOProc()
            destroyAggregateDevice()
            destroyTap()
            throw SystemAudioCaptureError.failedToStartDevice(status)
        }

        _isCapturing = true
        sysLog.warning("[SysAudio] System audio capture started")

        let transport = Self.transportName(for: defaultOutputID)
        SentryHelper.addBreadcrumb(
            category: "audio.system",
            message: "system audio capture started",
            data: [
                "deviceUID": uid as String,
                "transport": transport,
                "nativeSR": nativeSR,
                "nativeCh": Int(nativeCh),
            ]
        )

        // Schedule a verification check — warn if no real audio arrives within 3 seconds
        let flag = _audioReceivedFlag
        let capturedDeviceUID = uid as String
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 3.0) { [weak self] in
            guard let self = self, self._isCapturing else { return }
            if OSAtomicAdd32(0, flag) == 0 {
                sysLog.error("[SysAudio] WARNING: No non-zero audio received within 3 seconds of starting capture. The tap may have silently failed or permission was denied.")
                SentryHelper.addBreadcrumb(
                    category: "audio.system",
                    message: "system audio tap produced no audible samples in 3s",
                    level: .warning,
                    data: [
                        "deviceUID": capturedDeviceUID,
                        "transport": transport,
                    ]
                )
            }
        }
    }

    /// Best-effort identification of the output device's transport (built-in,
    /// usb, bluetooth, airplay, virtual, etc.). Used purely as diagnostic
    /// breadcrumb data so Sentry can correlate "silent tap" reports with
    /// device classes that are known to break CATap (Bluetooth, AirPlay).
    private static func transportName(for deviceID: AudioObjectID) -> String {
        var transport: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyTransportType,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        let status = AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, &transport)
        guard status == noErr else { return "unknown" }
        switch transport {
        case kAudioDeviceTransportTypeBuiltIn: return "built-in"
        case kAudioDeviceTransportTypeAggregate: return "aggregate"
        case kAudioDeviceTransportTypeVirtual: return "virtual"
        case kAudioDeviceTransportTypePCI: return "pci"
        case kAudioDeviceTransportTypeUSB: return "usb"
        case kAudioDeviceTransportTypeFireWire: return "firewire"
        case kAudioDeviceTransportTypeBluetooth: return "bluetooth"
        case kAudioDeviceTransportTypeBluetoothLE: return "bluetooth-le"
        case kAudioDeviceTransportTypeHDMI: return "hdmi"
        case kAudioDeviceTransportTypeDisplayPort: return "displayport"
        case kAudioDeviceTransportTypeAirPlay: return "airplay"
        case kAudioDeviceTransportTypeAVB: return "avb"
        case kAudioDeviceTransportTypeThunderbolt: return "thunderbolt"
        case kAudioDeviceTransportTypeContinuityCaptureWired: return "continuity-wired"
        case kAudioDeviceTransportTypeContinuityCaptureWireless: return "continuity-wireless"
        default: return "transport_\(transport)"
        }
    }

    /// Returns `true` if at least one buffer with non-zero audio samples has been received
    /// since capture started. Use this to verify the tap is actually producing audio.
    public func verifyAudioFlowing() -> Bool {
        return OSAtomicAdd32(0, _audioReceivedFlag) != 0
    }

    /// Wait up to `timeout` seconds for the tap to start producing non-silent audio.
    ///
    /// CATap silently returns silence in several scenarios:
    /// - The user denied the System Audio TCC prompt (the tap still gets a valid ID
    ///   but receives only zero samples — there is no error return from CoreAudio).
    /// - Permission was granted but the running process has a stale TCC cache.
    /// - The default output device is a Bluetooth/AirPlay sink whose audio path
    ///   bypasses the kernel layer the tap monitors.
    /// - The user is on macOS 14.2+ but has nothing actually playing — in that
    ///   case the result is genuinely "no audio yet", which is benign.
    ///
    /// Callers use the result to decide whether to keep the tap or fall back to
    /// microphone-only. Returns `true` as soon as any non-zero sample is seen, or
    /// `false` if the timeout elapses with only silence.
    public func waitForAudibleAudio(timeout: TimeInterval) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if hasReceivedAudio { return true }
            try? await Task.sleep(nanoseconds: 100_000_000)  // 100 ms
        }
        return hasReceivedAudio
    }

    /// Wait up to `timeout` seconds for the tap to start producing buffers.
    ///
    /// This is the UI-facing health signal. A buffer that contains silence can be
    /// healthy system audio when nothing is playing yet; no buffers means the tap
    /// is not delivering data to the app.
    public func waitForAudioBuffers(timeout: TimeInterval) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if hasReceivedBuffers { return true }
            try? await Task.sleep(nanoseconds: 100_000_000)  // 100 ms
        }
        return hasReceivedBuffers
    }

    /// Stop capturing system audio and release all Core Audio resources.
    public func stopCapture() {
        guard _isCapturing else { return }

        sysLog.warning("[SysAudio] Stopping system audio capture...")

        // Stop device
        if let procID = ioProcID {
            AudioDeviceStop(aggregateDeviceID, procID)
        }

        destroyIOProc()
        destroyAggregateDevice()
        destroyTap()

        _isCapturing = false
        OSAtomicCompareAndSwap32(1, 0, _bufferReceivedFlag)
        OSAtomicCompareAndSwap32(1, 0, _audioReceivedFlag)
        os_unfair_lock_lock(continuationLock)
        bufferContinuation?.finish()
        bufferContinuation = nil
        os_unfair_lock_unlock(continuationLock)
        setupBufferStream()

        sysLog.warning("[SysAudio] System audio capture stopped")
    }

    // MARK: - Cleanup helpers

    private func destroyIOProc() {
        if let procID = ioProcID, aggregateDeviceID != AudioObjectID.max {
            AudioDeviceDestroyIOProcID(aggregateDeviceID, procID)
            ioProcID = nil
        }
    }

    private func destroyAggregateDevice() {
        if aggregateDeviceID != AudioObjectID.max {
            AudioHardwareDestroyAggregateDevice(aggregateDeviceID)
            aggregateDeviceID = AudioObjectID.max
        }
    }

    private func destroyTap() {
        if tapID != AudioObjectID.max {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = AudioObjectID.max
        }
    }

    deinit {
        if _isCapturing {
            stopCapture()
        }
        continuationLock.deinitialize(count: 1)
        continuationLock.deallocate()
        _bufferReceivedFlag.deinitialize(count: 1)
        _bufferReceivedFlag.deallocate()
        _audioReceivedFlag.deinitialize(count: 1)
        _audioReceivedFlag.deallocate()
    }

    public func startRecording() async throws {
        try startCapture()
    }

    public func stopRecording() async {
        stopCapture()
    }
}

/// Errors specific to system audio capture.
public enum SystemAudioCaptureError: Error, Sendable {
    case failedToGetDefaultOutput(OSStatus)
    case failedToCreateTap(OSStatus)
    case failedToGetDeviceUID(OSStatus)
    case failedToCreateAggregateDevice(OSStatus)
    case failedToCreateIOProc(OSStatus)
    case failedToStartDevice(OSStatus)
}
#endif
