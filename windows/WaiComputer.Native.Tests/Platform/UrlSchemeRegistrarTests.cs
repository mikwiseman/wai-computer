using FluentAssertions;
using WaiComputer.Native.Platform;
using Xunit;

namespace WaiComputer.Native.Tests.Platform;

[Collection("Registry")]
public class UrlSchemeRegistrarTests
{
    [Fact]
    public void RegisterSetsCommand()
    {
        UrlSchemeRegistrar.Unregister();
        UrlSchemeRegistrar.IsRegistered().Should().BeFalse();

        UrlSchemeRegistrar.Register(@"C:\Program Files\WaiComputer\WaiComputer.exe");
        UrlSchemeRegistrar.IsRegistered().Should().BeTrue();
    }

    [Fact]
    public void UnregisterRemovesCommand()
    {
        UrlSchemeRegistrar.Register(@"C:\Program Files\WaiComputer\WaiComputer.exe");
        UrlSchemeRegistrar.Unregister();
        UrlSchemeRegistrar.IsRegistered().Should().BeFalse();
    }
}
