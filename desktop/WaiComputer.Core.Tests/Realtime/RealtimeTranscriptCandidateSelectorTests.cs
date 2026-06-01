using FluentAssertions;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class RealtimeTranscriptCandidateSelectorTests
{
    [Fact]
    public void PrefersLongerSupersetWhenProviderDroppedStartupWords()
        => RealtimeTranscriptCandidateSelector.Select(new[] { "check fast startup", null, "today we check fast startup" })
            .Should().Be("today we check fast startup");

    [Fact]
    public void KeepsProviderCandidateWhenAtLeastAsComplete()
        => RealtimeTranscriptCandidateSelector.Select(new[] { "hello world", null, "hello wor" })
            .Should().Be("hello world");

    [Fact]
    public void DoesNotPreferUnrelatedLongerCandidate()
        => RealtimeTranscriptCandidateSelector.Select(new[] { "hello world", null, "unrelated longer partial transcript" })
            .Should().Be("hello world");

    [Fact]
    public void IgnoresEmptyCandidatesAndTrims()
        => RealtimeTranscriptCandidateSelector.Select(new[] { "   ", null, "\nfirst word retained\n" })
            .Should().Be("first word retained");

    [Fact]
    public void EmptyInputReturnsEmpty()
    {
        RealtimeTranscriptCandidateSelector.Select(System.Array.Empty<string?>()).Should().Be("");
        RealtimeTranscriptCandidateSelector.Select(new string?[] { null, "  " }).Should().Be("");
    }
}
