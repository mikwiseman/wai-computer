using NAudio.CoreAudioApi;

namespace WaiComputer.Native.Platform;

/// <summary>
/// Detects whether the OS-level "Let desktop apps access your microphone"
/// setting is on. Win10/11 doesn't expose a programmatic prompt for unpackaged
/// apps, so we infer state by enumerating capture endpoints.
/// </summary>
public static class PermissionMonitor
{
    public static bool MicrophoneAccessible()
    {
        try
        {
            var enumerator = new MMDeviceEnumerator();
            var devices = enumerator.EnumerateAudioEndPoints(DataFlow.Capture, DeviceState.Active);
            return devices.Count > 0;
        }
        catch
        {
            return false;
        }
    }

    public static string MicrophoneSettingsUri => "ms-settings:privacy-microphone";
}
