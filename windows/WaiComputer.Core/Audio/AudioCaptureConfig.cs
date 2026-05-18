namespace WaiComputer.Core.Audio;

public sealed record AudioCaptureConfig(int SampleRate = 16000, bool MixToMono = true, bool SeparateChannels = false)
{
    public ushort OutputChannelCount => (MixToMono && !SeparateChannels) ? (ushort)1 : (ushort)2;
}
