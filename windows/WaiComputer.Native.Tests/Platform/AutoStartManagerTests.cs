using FluentAssertions;
using Microsoft.Win32;
using WaiComputer.Native.Platform;
using Xunit;

namespace WaiComputer.Native.Tests.Platform;

[Collection("Registry")]
public class AutoStartManagerTests
{
    [Fact]
    public void EnableSetsRunEntry()
    {
        AutoStartManager.Disable();
        AutoStartManager.IsEnabled.Should().BeFalse();

        AutoStartManager.Enable(@"C:\Program Files\WaiComputer\WaiComputer.exe");
        AutoStartManager.IsEnabled.Should().BeTrue();
    }

    [Fact]
    public void DisableClearsRunEntry()
    {
        AutoStartManager.Enable(@"C:\Program Files\WaiComputer\WaiComputer.exe");
        AutoStartManager.Disable();
        AutoStartManager.IsEnabled.Should().BeFalse();
    }
}
