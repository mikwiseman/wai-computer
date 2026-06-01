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
}
