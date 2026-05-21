namespace WaiComputer.Core.Audio;

public sealed record AudioCaptureConfig(int SampleRate = 16000, bool MixToMono = true, bool SeparateChannels = false, int FrameSizeSamples = 1600)
{
    public ushort OutputChannelCount => (MixToMono && !SeparateChannels) ? (ushort)1 : (ushort)2;
}
