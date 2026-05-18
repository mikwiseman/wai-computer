using FluentAssertions;
using WaiComputer.Core.Monitoring;
using Xunit;

namespace WaiComputer.Core.Tests.Monitoring;

public class SanitizerTests
{
    [Theory]
    [InlineData("token")]
    [InlineData("password")]
    [InlineData("secret")]
    [InlineData("authorization")]
    [InlineData("cookie")]
    [InlineData("access_token")]
    [InlineData("refresh_token")]
    public void SecretKeysAlwaysFullyRedacted(string key)
    {
        Sanitizer.Sanitize(key, "anything-at-all").Should().Be("[REDACTED]");
    }

    [Fact]
    public void EmailUsesFingerprint()
    {
        var redacted = (string)Sanitizer.Sanitize("email", "hi@mikwiseman.com")!;
        redacted.Should().StartWith("[REDACTED:").And.EndWith("]");
    }

    [Fact]
    public void EmailFingerprintIsStable()
    {
        var a = Sanitizer.Sanitize("email", "hi@mikwiseman.com");
        var b = Sanitizer.Sanitize("email", "hi@mikwiseman.com");
        a.Should().Be(b);
    }

    [Fact]
    public void TitleUsesFingerprint()
    {
        var redacted = (string)Sanitizer.Sanitize("title", "Secret Project Meeting")!;
        redacted.Should().StartWith("[REDACTED:");
    }

    [Fact]
    public void TranscriptUsesLengthAndFingerprint()
    {
        var redacted = (string)Sanitizer.Sanitize("transcript", "hello world meeting transcript")!;
        redacted.Should().MatchRegex(@"^\[REDACTED:\d+:[0-9a-f]{6}\]$");
    }

    [Fact]
    public void InlineEmailsAreScrubbedInFreeText()
    {
        var redacted = (string)Sanitizer.Sanitize("note", "contact me at hi@mikwiseman.com for details")!;
        redacted.Should().NotContain("@");
        redacted.Should().Contain("[REDACTED:");
    }

    [Fact]
    public void NestedDictionarySanitised()
    {
        var input = new Dictionary<string, object?>
        {
            ["email"] = "user@example.com",
            ["nested"] = new Dictionary<string, object?>
            {
                ["password"] = "hunter2",
                ["title"] = "Q1 Plan",
            },
        };
        var sanitised = Sanitizer.SanitizeDictionary(input);
        sanitised["email"].Should().Match(s => ((string)s!).StartsWith("[REDACTED:"));
        ((IDictionary<string, object?>)sanitised["nested"]!)["password"].Should().Be("[REDACTED]");
        ((IDictionary<string, object?>)sanitised["nested"]!)["title"].Should().Match(s => ((string)s!).StartsWith("[REDACTED:"));
    }

    [Fact]
    public void NormalizePathStripsUuids()
    {
        Sanitizer.NormalizePath("/api/recordings/12345678-1234-1234-1234-123456789012/transcript")
            .Should().Be("/api/recordings/{id}/transcript");
    }

    [Fact]
    public void NormalizePathStripsNumericIds()
    {
        Sanitizer.NormalizePath("/api/folders/42").Should().Be("/api/folders/{id}");
    }

    [Fact]
    public void FingerprintHasExactRequestedLength()
    {
        Sanitizer.Fingerprint("anything", length: 8).Length.Should().Be(8);
        Sanitizer.Fingerprint("anything", length: 12).Length.Should().Be(12);
    }
}
