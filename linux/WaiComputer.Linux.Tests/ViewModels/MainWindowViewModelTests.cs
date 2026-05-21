using FluentAssertions;
using WaiComputer.Linux.Audio;
using WaiComputer.Linux.Platform;
using WaiComputer.Linux.Tests.TestDoubles;
using WaiComputer.Linux.ViewModels;

namespace WaiComputer.Linux.Tests.ViewModels;

public sealed class MainWindowViewModelTests
{
    [Fact]
    public void Magic_link_startup_arg_routes_to_settings_without_logging_token()
    {
        var vm = new MainWindowViewModel(BuildNoopProbe());

        vm.HandleStartupArgs(["waicomputer://auth/verify?token=secret-token"]);

        vm.SelectedSection.Should().Be("Settings");
        vm.StatusText.Should().Contain("Magic link received");
        vm.StatusText.Should().NotContain("secret-token");
    }

    private static LinuxCapabilityProbe BuildNoopProbe()
    {
        var commands = new FakeCommandRunner();
        return new LinuxCapabilityProbe(
            new PulseAudioDeviceProbe(commands),
            new PortalCapabilityProbe(commands),
            new ToolProbe(commands),
            () => LinuxDesktopEnvironment.From(new Dictionary<string, string?>
            {
                ["HOME"] = "/home/mik",
            }));
    }
}
