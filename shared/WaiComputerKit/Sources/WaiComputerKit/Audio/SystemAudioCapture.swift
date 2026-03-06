import Foundation
import AVFoundation
import CoreAudio
import AudioToolbox
import os

private let sysLog = Logger(subsystem: "com.waicomputer.kit", category: "system-audio")

/// Captures system audio output using Core Audio Process Taps (macOS 14.2+).
///
/// Produces `AsyncStream<AVAudioPCMBuffer>` at 16kHz mono, matching
/// the same interface pattern as `MicrophoneCapture`.
@available(macOS 14.2, *)
public final class SystemAudioCapture: AudioCaptureProtocol, @unchecked Sendable {
    private let config: AudioCaptureConfig

    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    public private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>

    private var _isCapturing = false
    public var isCapturing: Bool { _isCapturing }

    // Core Audio resources to clean up
    private var tapID: AudioObjectID = AudioObjectID.max
    private var aggregateDeviceID: AudioObjectID = AudioObjectID.max
    private var ioProcID: AudioDeviceIOProcID?

    public init(config: AudioCaptureConfig = .default) {
        self.config = config
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        self.audioBuffers = stream
        self.bufferContinuation = continuation
    }

    public var isRecording: Bool { isCapturing }

    private func setupBufferStream() {
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        audioBuffers = stream
        bufferContinuation = continuation
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

        // 2. Create process tap (empty process list = all system audio)
        let tapDescription = CATapDescription(stereoMixdownOfProcesses: [])
        tapDescription.uuid = UUID()
        tapDescription.muteBehavior = .unmuted

        var newTapID = AudioObjectID.max
        status = AudioHardwareCreateProcessTap(tapDescription, &newTapID)
        guard status == noErr else {
            throw SystemAudioCaptureError.failedToCreateTap(status)
        }
        tapID = newTapID
        sysLog.warning("[SysAudio] Created process tap ID: \(self.tapID)")

        // 3. Get the output device UID
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
        if status == noErr {
            nativeSR = inputStreamFormat.mSampleRate
            nativeCh = inputStreamFormat.mChannelsPerFrame
            sysLog.warning("[SysAudio] Native input format: \(nativeSR)Hz, \(nativeCh)ch")
        } else {
            // Assume 48kHz stereo if we can't query
            nativeSR = 48000
            nativeCh = 2
            sysLog.warning("[SysAudio] Could not query format (status \(status)), assuming \(nativeSR)Hz \(nativeCh)ch")
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

            let bufferList = inInputData.pointee
            guard bufferList.mNumberBuffers > 0 else { return }

            let audioBuffer = bufferList.mBuffers
            guard let dataPtr = audioBuffer.mData else { return }

            let srcFrames = Int(audioBuffer.mDataByteSize) / MemoryLayout<Float>.size / Int(max(nativeCh, 1))
            if srcFrames == 0 { return }

            let srcSamples = dataPtr.assumingMemoryBound(to: Float.self)

            // Downsample from native rate to target rate (16kHz), mix to mono
            let ratio = nativeSR / targetSR
            let outFrames = Int(Double(srcFrames) / ratio)
            if outFrames == 0 { return }

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

            let channels = Int(max(nativeCh, 1))

            if ratio <= 1.01 && channels == 1 {
                // No resampling or mixing needed
                for i in 0..<outFrames {
                    dst[i] = srcSamples[i]
                }
            } else {
                // Downsample with averaging + mono mixdown
                let intRatio = Int(ratio.rounded())
                for i in 0..<outFrames {
                    let srcStart = Int(Double(i) * ratio)
                    var sum: Float = 0
                    let count = min(intRatio, srcFrames - srcStart)
                    for j in 0..<count {
                        // Average across channels for mono mixdown
                        var sampleSum: Float = 0
                        for ch in 0..<channels {
                            sampleSum += srcSamples[(srcStart + j) * channels + ch]
                        }
                        sum += sampleSum / Float(channels)
                    }
                    dst[i] = sum / Float(count)
                }
            }

            if tapCount <= 3 || tapCount % 100 == 0 {
                sysLog.warning("[SysAudio] Tap #\(tapCount): \(srcFrames)@\(nativeSR)Hz -> \(outFrames)@\(targetSR)Hz")
            }

            self.bufferContinuation?.yield(outBuffer)
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
        bufferContinuation?.finish()
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
