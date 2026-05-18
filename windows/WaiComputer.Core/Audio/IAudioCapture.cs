using System.Threading.Channels;

namespace WaiComputer.Core.Audio;

/// <summary>
/// One audio capture source — either a microphone or a system-audio loopback.
/// </summary>
public interface IAudioCapture : IAsyncDisposable
{
    AudioSource Source { get; }
    bool IsCapturing { get; }
    /// <summary>True once at least one non-zero frame has been observed.</summary>
    bool HasReceivedAudio { get; }
    /// <summary>Last time a frame above the audibility threshold was seen, or null.</summary>
    DateTimeOffset? LastAudibleAt { get; }

    Task StartAsync(CancellationToken ct);
    Task StopAsync();

    /// <summary>Bounded channel of <see cref="AudioFrame"/>s.</summary>
    ChannelReader<AudioFrame> Frames { get; }
}

public interface IMicrophoneCapture : IAudioCapture { }
public interface ISystemAudioCapture : IAudioCapture { }
