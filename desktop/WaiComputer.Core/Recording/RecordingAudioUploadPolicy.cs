namespace WaiComputer.Core.Recordings;

/// <summary>
/// Decides whether a finalized recording's audio is eligible for upload, porting
/// the macOS <c>RecordingAudioUploadPolicy</c>. File STT accepts uploaded audio
/// from 100 ms upward; this is the transport floor, not a product-level
/// "too short / too quiet" judgement.
/// </summary>
public static class RecordingAudioUploadPolicy
{
    public const double MinimumDurationSeconds = 0.1;

    public static bool CanUploadFinalizedAudio(double? durationSeconds, long pcmBytesWritten)
        => durationSeconds is { } d && pcmBytesWritten > 0 && d >= MinimumDurationSeconds;
}
