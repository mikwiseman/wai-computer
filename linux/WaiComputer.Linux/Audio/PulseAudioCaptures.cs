using WaiComputer.Core.Audio;

namespace WaiComputer.Linux.Audio;

public sealed class PulseAudioMicrophoneCapture : ProcessPcmCapture, IMicrophoneCapture, ILinuxAudioCapture
{
    public PulseAudioMicrophoneCapture(string deviceName, int sampleRate = 16000, int frameSizeSamples = 1600)
        : base(deviceName, sampleRate, frameSizeSamples)
    {
    }

    public override AudioSource Source => AudioSource.Microphone;
}

public sealed class PulseAudioSystemAudioCapture : ProcessPcmCapture, ISystemAudioCapture, ILinuxAudioCapture
{
    public PulseAudioSystemAudioCapture(string deviceName, int sampleRate = 16000, int frameSizeSamples = 1600)
        : base(deviceName, sampleRate, frameSizeSamples)
    {
    }

    public override AudioSource Source => AudioSource.SystemAudio;
}
