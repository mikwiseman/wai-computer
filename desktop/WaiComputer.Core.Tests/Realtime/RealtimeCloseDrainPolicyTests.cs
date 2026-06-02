using System;
using FluentAssertions;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class RealtimeCloseDrainPolicyTests
{
    private static TimeSpan Ms(double ms) => TimeSpan.FromMilliseconds(ms);

    [Fact]
    public void PastDeadlineStops()
        => RealtimeCloseDrainPolicy.ShouldKeepWaiting(Ms(5000), Ms(5000), Ms(0), Ms(100), false)
            .Should().BeFalse();

    [Fact]
    public void FinalizationMarkerAfterMinimumWaitStops()
        => RealtimeCloseDrainPolicy.ShouldKeepWaiting(Ms(700), Ms(10_000), Ms(0), null, true)
            .Should().BeFalse();

    [Fact]
    public void FinalizationMarkerBeforeMinimumWaitKeepsWaiting()
        => RealtimeCloseDrainPolicy.ShouldKeepWaiting(Ms(600), Ms(10_000), Ms(0), null, true)
            .Should().BeTrue();

    [Fact]
    public void QuietWindowElapsedAfterTranscriptStops()
        // now=1600 (past 650 min), last=600 -> quiet 1000ms >= 900ms -> stop
        => RealtimeCloseDrainPolicy.ShouldKeepWaiting(Ms(1600), Ms(10_000), Ms(0), Ms(600), false)
            .Should().BeFalse();

    [Fact]
    public void RecentTranscriptKeepsWaiting()
        // now=1000, last=800 -> quiet 200ms < 900ms -> keep waiting
        => RealtimeCloseDrainPolicy.ShouldKeepWaiting(Ms(1000), Ms(10_000), Ms(0), Ms(800), false)
            .Should().BeTrue();

    [Fact]
    public void QuietButBeforeMinimumWaitKeepsWaiting()
        // now=500 (< 650 min), last=0 -> quiet 500<900 anyway, and min not reached -> keep
        => RealtimeCloseDrainPolicy.ShouldKeepWaiting(Ms(500), Ms(10_000), Ms(0), Ms(0), false)
            .Should().BeTrue();

    [Fact]
    public void NoTranscriptKeepsWaitingUntilNoTranscriptWaitThenStops()
    {
        RealtimeCloseDrainPolicy.ShouldKeepWaiting(Ms(2000), Ms(10_000), Ms(0), null, false).Should().BeTrue();
        RealtimeCloseDrainPolicy.ShouldKeepWaiting(Ms(2500), Ms(10_000), Ms(0), null, false).Should().BeFalse();
    }
}
