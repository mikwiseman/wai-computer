import Foundation
import AVFoundation
import CoreAudio
import WaiComputerKit

/// Manages system audio capture using BlackHole virtual audio device
@MainActor
class SystemAudioManager: ObservableObject {
    static let shared = SystemAudioManager()

    @Published var isBlackHoleInstalled = false
    @Published var availableDevices: [AudioDevice] = []
    @Published var selectedDevice: AudioDevice?
    @Published var isCapturing = false

    private var audioEngine: AVAudioEngine?
    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    public private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>!

    struct AudioDevice: Identifiable, Hashable {
        let id: AudioDeviceID
        let name: String
        let isInput: Bool
        let isBlackHole: Bool
    }

    private init() {
        refreshDevices()
        setupBufferStream()
    }

    private func setupBufferStream() {
        audioBuffers = AsyncStream { continuation in
            self.bufferContinuation = continuation
        }
    }

    /// Refresh available audio devices
    func refreshDevices() {
        var propertySize: UInt32 = 0
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )

        AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject),
            &propertyAddress,
            0,
            nil,
            &propertySize
        )

        let deviceCount = Int(propertySize) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = [AudioDeviceID](repeating: 0, count: deviceCount)

        AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &propertyAddress,
            0,
            nil,
            &propertySize,
            &deviceIDs
        )

        var devices: [AudioDevice] = []

        for deviceID in deviceIDs {
            if let name = getDeviceName(deviceID) {
                let isInput = hasInputStream(deviceID)
                let isBlackHole = name.lowercased().contains("blackhole")

                if isInput {
                    devices.append(AudioDevice(
                        id: deviceID,
                        name: name,
                        isInput: isInput,
                        isBlackHole: isBlackHole
                    ))

                    if isBlackHole {
                        isBlackHoleInstalled = true
                    }
                }
            }
        }

        availableDevices = devices
    }

    private func getDeviceName(_ deviceID: AudioDeviceID) -> String? {
        var propertySize: UInt32 = 0
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceNameCFString,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )

        AudioObjectGetPropertyDataSize(deviceID, &propertyAddress, 0, nil, &propertySize)

        var name: CFString? = nil
        AudioObjectGetPropertyData(deviceID, &propertyAddress, 0, nil, &propertySize, &name)

        return name as String?
    }

    private func hasInputStream(_ deviceID: AudioDeviceID) -> Bool {
        var propertySize: UInt32 = 0
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreamConfiguration,
            mScope: kAudioDevicePropertyScopeInput,
            mElement: kAudioObjectPropertyElementMain
        )

        let status = AudioObjectGetPropertyDataSize(deviceID, &propertyAddress, 0, nil, &propertySize)
        if status != noErr { return false }

        let bufferListSize = Int(propertySize)
        let bufferList = UnsafeMutablePointer<AudioBufferList>.allocate(capacity: bufferListSize)
        defer { bufferList.deallocate() }

        AudioObjectGetPropertyData(deviceID, &propertyAddress, 0, nil, &propertySize, bufferList)

        let buffers = UnsafeMutableAudioBufferListPointer(bufferList)
        return buffers.count > 0 && buffers[0].mNumberChannels > 0
    }

    /// Start capturing from a specific device
    func startCapture(device: AudioDevice) async throws {
        guard !isCapturing else { return }

        // For BlackHole, we use AVAudioEngine with the device as input
        audioEngine = AVAudioEngine()

        guard let engine = audioEngine else { return }

        // Configure input node to use the selected device
        // Note: This requires setting the system's audio input device
        // In production, you might use CoreAudio directly for more control

        let inputNode = engine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)

        // Target format for transcription
        guard let targetFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16000,
            channels: 1,
            interleaved: false
        ) else {
            throw SystemAudioError.invalidFormat
        }

        let converter = AVAudioConverter(from: inputFormat, to: targetFormat)

        inputNode.installTap(onBus: 0, bufferSize: 2560, format: inputFormat) { [weak self] buffer, _ in
            guard let self = self, let converter = converter else { return }

            guard let convertedBuffer = AVAudioPCMBuffer(
                pcmFormat: targetFormat,
                frameCapacity: 2560
            ) else { return }

            var error: NSError?
            let status = converter.convert(to: convertedBuffer, error: &error) { inNumPackets, outStatus in
                outStatus.pointee = .haveData
                return buffer
            }

            if status == .haveData {
                self.bufferContinuation?.yield(convertedBuffer)
            }
        }

        try engine.start()
        isCapturing = true
        selectedDevice = device
    }

    /// Stop capturing
    func stopCapture() async {
        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine?.stop()
        audioEngine = nil
        isCapturing = false
        selectedDevice = nil
        bufferContinuation?.finish()
        setupBufferStream()
    }
}

/// Instructions for BlackHole setup
struct BlackHoleSetupInstructions {
    static let installURL = URL(string: "https://github.com/ExistentialAudio/BlackHole")!

    static let steps = """
    To capture system audio (Zoom, Meet, etc.), install BlackHole:

    1. Download BlackHole from: https://github.com/ExistentialAudio/BlackHole
    2. Install BlackHole 2ch (recommended)
    3. Open Audio MIDI Setup (Applications > Utilities)
    4. Create a Multi-Output Device:
       - Click + at bottom left
       - Select "Create Multi-Output Device"
       - Check your speakers AND BlackHole 2ch
    5. Set the Multi-Output Device as your system output
    6. In WaiComputer, select BlackHole 2ch as input

    This routes audio to both your speakers and WaiComputer.
    """
}

enum SystemAudioError: Error {
    case invalidFormat
    case deviceNotFound
    case permissionDenied
}
