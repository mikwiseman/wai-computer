namespace WaiComputer.Core.Audio;

public sealed record AudioCaptureConfig(int SampleRate = 16000, bool MixToMono = true, bool SeparateChannels = false, int FrameSizeSamples = 1600)
{
    public ushort OutputChannelCount => (MixToMono && !SeparateChannels) ? (ushort)1 : (ushort)2;

    /// <summary>Minimum aligned samples (80 ms) before the dual mixer emits a frame (Mac <c>Int(sampleRate*0.08)</c>).</summary>
    public int MinFlushSamples => (int)(SampleRate * 0.08);

    /// <summary>Cap on mic samples emitted in one flush when system audio has stalled (1 s, Mac <c>Int(sampleRate)</c>).</summary>
    public int MaxStallPadSamples => SampleRate;
}
