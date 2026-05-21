namespace WaiComputer.Core.Audio;

/// <summary>
/// A single chunk of 16 kHz mono 16-bit PCM audio emitted by a capture
/// source. <see cref="Pcm16"/> length is always <c>2 * SampleCount</c> bytes.
/// </summary>
public readonly record struct AudioFrame(byte[] Pcm16, TimeSpan Timestamp, int SampleCount)
{
    public int SizeBytes => Pcm16.Length;
    public bool IsEmpty => SampleCount == 0;
}

public enum AudioSource { Microphone, SystemAudio }
