using FluentAssertions;
using WaiComputer.Linux.Updates;

namespace WaiComputer.Linux.Tests.Updates;

public sealed class LinuxUpdatePolicyTests
{
    [Theory]
    [InlineData(LinuxUpdateChannel.Stable, "linux")]
    [InlineData(LinuxUpdateChannel.Beta, "linux-beta")]
    public void Resolves_platform_specific_channels(LinuxUpdateChannel channel, string expected)
    {
        var feed = LinuxUpdatePolicy.Resolve("https://wai.computer/releases/linux/", channel);

        feed.FeedUrl.Should().Be("https://wai.computer/releases/linux");
        feed.Channel.Should().Be(expected);
    }
}
