using FluentAssertions;
using WaiComputer.Core.Auth;
using Xunit;

namespace WaiComputer.Core.Tests.Auth;

public class MagicLinkUrlTests
{
    [Theory]
    [InlineData("waicomputer://auth/verify?token=abc123", "abc123")]
    [InlineData("WAICOMPUTER://AUTH/VERIFY?token=abc123", "abc123")]
    [InlineData("waicomputer://auth/verify?other=x&token=abc123", "abc123")]
    [InlineData("waicomputer://auth/verify?token=hello%20world", "hello world")]
    public void AcceptsValidUrls(string input, string expected)
    {
        MagicLinkUrl.TryParse(input, out var token).Should().BeTrue();
        token.Should().Be(expected);
    }

    [Theory]
    [InlineData("https://wai.computer/auth/verify?token=abc123")]
    [InlineData("waicomputer://other/verify?token=abc123")]
    [InlineData("waicomputer://auth/elsewhere?token=abc123")]
    [InlineData("waicomputer://auth/verify")]
    [InlineData("waicomputer://auth/verify?token=")]
    [InlineData("not a url")]
    [InlineData("")]
    [InlineData(null)]
    public void RejectsInvalidUrls(string? input)
    {
        MagicLinkUrl.TryParse(input, out var token).Should().BeFalse();
        token.Should().BeNull();
    }
}
