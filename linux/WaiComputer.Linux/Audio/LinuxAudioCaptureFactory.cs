using WaiComputer.Core.Audio;

namespace WaiComputer.Linux.Audio;

public enum LinuxRecordingMode
{
    MicrophoneOnly,
    MicrophoneAndSystemAudio,
}

public sealed class LinuxAudioCapabilityException : Exception
{
    public LinuxAudioCapabilityException(string message) : base(message)
    {
    }
}

public sealed class LinuxAudioCaptureFactory
{
    private readonly PulseAudioDeviceProbe _probe;

    public LinuxAudioCaptureFactory(PulseAudioDeviceProbe probe)
    {
        _probe = probe;
    }

    public async Task<DualAudioCapture> CreateAsync(
        LinuxRecordingMode mode,
        AudioCaptureConfig config,
        CancellationToken ct = default)
    {
        var snapshot = await _probe.ProbeAsync(ct).ConfigureAwait(false);
        var microphone = snapshot.DefaultMicrophone
            ?? throw new LinuxAudioCapabilityException("No PulseAudio/PipeWire microphone source is available.");

        var micCapture = new PulseAudioMicrophoneCapture(microphone.Name, config.SampleRate, config.FrameSizeSamples);

        if (mode == LinuxRecordingMode.MicrophoneOnly)
        {
            return new DualAudioCapture(micCapture, system: null, config);
        }

        var monitor = snapshot.DefaultSystemMonitor
            ?? throw new LinuxAudioCapabilityException("System audio requested, but no PulseAudio/PipeWire monitor source is available for the active sink.");

        var systemCapture = new PulseAudioSystemAudioCapture(monitor.Name, config.SampleRate, config.FrameSizeSamples);
        return new DualAudioCapture(micCapture, systemCapture, config);
    }
}
