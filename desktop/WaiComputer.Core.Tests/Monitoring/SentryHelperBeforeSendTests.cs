using System.Linq;
using FluentAssertions;
using Sentry;
using Sentry.Protocol;
using WaiComputer.Core.Monitoring;
using Xunit;

namespace WaiComputer.Core.Tests.Monitoring;

public class SentryHelperBeforeSendTests
{
    [Fact]
    public void StripsEmailFromMessageButKeepsContext()
    {
        var evt = new SentryEvent { Message = "login failed for hi@mikwiseman.com retrying" };

        var sanitized = SentryHelper.SanitizeEvent(evt);

        sanitized.Message!.Message.Should().NotContain("hi@mikwiseman.com");
        sanitized.Message!.Message.Should().Contain("login failed");
    }

    [Fact]
    public void RedactsKeyedExtraButKeepsSafeKeys()
    {
        var evt = new SentryEvent();
        evt.SetExtra("transcript", "secret words here");
        evt.SetExtra("email", "hi@mikwiseman.com");
        evt.SetExtra("method", "GET");

        var sanitized = SentryHelper.SanitizeEvent(evt);

        sanitized.Extra["transcript"].Should().NotBe("secret words here");
        sanitized.Extra["email"]!.ToString().Should().NotContain("hi@mikwiseman.com");
        sanitized.Extra["method"].Should().Be("GET");
        sanitized.Extra["sanitized"].Should().Be("true");
    }

    [Fact]
    public void RedactsSecretTag()
    {
        var evt = new SentryEvent();
        evt.SetTag("authorization", "Bearer abc123");

        var sanitized = SentryHelper.SanitizeEvent(evt);

        sanitized.Tags["authorization"].Should().Be("[REDACTED]");
    }

    [Fact]
    public void StripsEmailFromExceptionValue()
    {
        var evt = new SentryEvent
        {
            SentryExceptions = new[]
            {
                new SentryException { Type = "InvalidOperationException", Value = "bad token for hi@mikwiseman.com" },
            },
        };

        var sanitized = SentryHelper.SanitizeEvent(evt);

        sanitized.SentryExceptions!.Single().Value.Should().NotContain("hi@mikwiseman.com");
    }
}
