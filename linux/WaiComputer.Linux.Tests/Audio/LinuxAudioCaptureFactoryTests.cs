using FluentAssertions;
using WaiComputer.Core.Audio;
using WaiComputer.Linux.Audio;
using WaiComputer.Linux.Platform;
using WaiComputer.Linux.Tests.TestDoubles;

namespace WaiComputer.Linux.Tests.Audio;

public sealed class LinuxAudioCaptureFactoryTests
{
    [Fact]
    public async Task System_audio_mode_fails_hard_when_monitor_source_is_missing()
    {
        var commands = new FakeCommandRunner();
        commands.Enqueue("pactl", ["info"], new CommandResult(0, """
Default Sink: speaker
Default Source: mic
""", ""));
        commands.Enqueue("pactl", ["list", "short", "sources"], new CommandResult(0, """
1	mic	PipeWire	s16le 1ch 48000Hz	RUNNING
""", ""));
        var factory = new LinuxAudioCaptureFactory(new PulseAudioDeviceProbe(commands));

        var act = async () => await factory.CreateAsync(
            LinuxRecordingMode.MicrophoneAndSystemAudio,
            new AudioCaptureConfig(FrameSizeSamples: 1600));

        await act.Should().ThrowAsync<LinuxAudioCapabilityException>()
            .WithMessage("*monitor source*");
    }
}
