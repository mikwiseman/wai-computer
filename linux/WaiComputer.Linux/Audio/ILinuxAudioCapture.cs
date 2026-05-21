using WaiComputer.Core.Audio;

namespace WaiComputer.Linux.Audio;

public interface ILinuxAudioCapture : IAudioCapture
{
    string DeviceName { get; }
}
