using FluentAssertions;
using WaiComputer.Linux.Audio;

namespace WaiComputer.Linux.Tests.Audio;

public sealed class PulseAudioSourceParserTests
{
    [Fact]
    public void Selects_default_microphone_and_active_sink_monitor()
    {
        const string info = """
Server Name: PulseAudio (on PipeWire 1.0.7)
Default Sink: alsa_output.pci-0000_00_1f.3.analog-stereo
Default Source: alsa_input.usb-Elgato_Wave_3.mono-fallback
""";
        const string sources = """
47	alsa_input.usb-Elgato_Wave_3.mono-fallback	PipeWire	s16le 1ch 48000Hz	SUSPENDED
59	alsa_output.pci-0000_00_1f.3.analog-stereo.monitor	PipeWire	float32le 2ch 48000Hz	RUNNING
""";

        var snapshot = PulseAudioSourceParser.Parse(info, sources);

        snapshot.DefaultMicrophone.Should().NotBeNull();
        snapshot.DefaultMicrophone!.Name.Should().Be("alsa_input.usb-Elgato_Wave_3.mono-fallback");
        snapshot.DefaultSystemMonitor.Should().NotBeNull();
        snapshot.DefaultSystemMonitor!.Name.Should().Be("alsa_output.pci-0000_00_1f.3.analog-stereo.monitor");
    }

    [Fact]
    public void Missing_monitor_source_is_visible_to_callers()
    {
        const string info = """
Default Sink: alsa_output.pci-0000_00_1f.3.analog-stereo
Default Source: alsa_input.usb-Elgato_Wave_3.mono-fallback
""";
        const string sources = """
47	alsa_input.usb-Elgato_Wave_3.mono-fallback	PipeWire	s16le 1ch 48000Hz	SUSPENDED
""";

        var snapshot = PulseAudioSourceParser.Parse(info, sources);

        snapshot.DefaultMicrophone.Should().NotBeNull();
        snapshot.DefaultSystemMonitor.Should().BeNull();
    }
}
