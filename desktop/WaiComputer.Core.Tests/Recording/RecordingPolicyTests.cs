using FluentAssertions;
using WaiComputer.Core.Recordings;
using Xunit;

namespace WaiComputer.Core.Tests.Recording;

public class RecordingPolicyTests
{
    [Theory]
    [InlineData(0.1, 100L, true)]    // exactly the 100 ms floor
    [InlineData(0.099, 100L, false)] // below the floor
    [InlineData(5.0, 0L, false)]     // nothing written
    [InlineData(null, 100L, false)]  // unknown duration
    [InlineData(1.0, 1L, true)]
    public void CanUploadHonorsFloorAndBytes(double? durationSeconds, long bytes, bool expected)
        => RecordingAudioUploadPolicy.CanUploadFinalizedAudio(durationSeconds, bytes).Should().Be(expected);

    [Theory]
    [InlineData(true, true, true)]
    [InlineData(true, false, true)]   // receivedAny ignored — stall alone drives the warning
    [InlineData(false, true, false)]
    [InlineData(false, false, false)]
    public void WarningOnlyWhenStalled(bool stalled, bool receivedAny, bool expected)
        => SystemAudioWarningPolicy.ShouldShowCaptureWarning(stalled, receivedAny).Should().Be(expected);

    [Theory]
    [InlineData(false, true, false, SystemAudioHeaderIndicator.MicrophoneOnly)]     // not requested
    [InlineData(true, true, true, SystemAudioHeaderIndicator.SystemAudioDegraded)]  // warning present
    [InlineData(true, true, false, SystemAudioHeaderIndicator.MicAndSystem)]        // both live
    [InlineData(true, false, false, SystemAudioHeaderIndicator.SystemAudioStarting)] // requested, not yet flowing
    public void HeaderIndicatorMatchesMac(bool requested, bool hasSystem, bool warning, SystemAudioHeaderIndicator expected)
        => SystemAudioWarningPolicy.HeaderIndicator(requested, hasSystem, warning).Should().Be(expected);
}
