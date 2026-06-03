using FluentAssertions;
using WaiComputer.Core.Dictation;
using Xunit;

namespace WaiComputer.Core.Tests.Dictation;

public class DictationPoliciesTests
{
    [Theory]
    [InlineData(PushToTalkStopState.Listening, false, PushToTalkStopResolution.FinishNow)]
    [InlineData(PushToTalkStopState.Idle, false, PushToTalkStopResolution.DeferUntilReady)]
    [InlineData(PushToTalkStopState.Connecting, false, PushToTalkStopResolution.DeferUntilReady)]
    [InlineData(PushToTalkStopState.Finalizing, false, PushToTalkStopResolution.DoNothing)]
    [InlineData(PushToTalkStopState.Listening, true, PushToTalkStopResolution.DoNothing)]   // hands-free overrides
    [InlineData(PushToTalkStopState.Idle, true, PushToTalkStopResolution.DoNothing)]
    public void ResolveMatchesMac(PushToTalkStopState state, bool handsFree, PushToTalkStopResolution expected)
        => PushToTalkStopPolicy.Resolve(state, handsFree).Should().Be(expected);

    [Theory]
    [InlineData(true, false, DeferredStopAction.FinishAfterReady)] // deferred + not hands-free -> finish
    [InlineData(true, true, DeferredStopAction.ContinueListening)] // hands-free ignores the release
    [InlineData(false, false, DeferredStopAction.ContinueListening)]
    [InlineData(false, true, DeferredStopAction.ContinueListening)]
    public void DeferredStopActionMatchesMac(bool deferred, bool handsFree, DeferredStopAction expected)
        => DeferredDictationStopPolicy.Action(deferred, handsFree).Should().Be(expected);

    [Fact]
    public void CaptureTailDelayIs450Ms()
        => DictationFinalizationPolicy.CaptureTailDelay.Should().Be(TimeSpan.FromMilliseconds(450));

    [Fact]
    public void CleanupDisabledUsesRawVerbatim()
        => DictationCleanupPolicy.TextToInsert(postFilterEnabled: false, raw: "um hello", cleanupResult: null, cleanupFailed: false)
            .Should().Be("um hello");

    [Fact]
    public void CleanupEnabledReturnsTrimmedCleanedText()
        => DictationCleanupPolicy.TextToInsert(postFilterEnabled: true, raw: "um hello", cleanupResult: "  Hello.  ", cleanupFailed: false)
            .Should().Be("Hello.");

    [Fact]
    public void CleanupEnabledButFailedThrows()
    {
        var act = () => DictationCleanupPolicy.TextToInsert(true, "raw", cleanupResult: null, cleanupFailed: true);
        act.Should().Throw<DictationCleanupException>();
    }

    [Fact]
    public void CleanupEnabledButEmptyThrows()
    {
        var act = () => DictationCleanupPolicy.TextToInsert(true, "raw", cleanupResult: "   ", cleanupFailed: false);
        act.Should().Throw<DictationCleanupException>();
    }
}
