using Microsoft.Win32;

namespace WaiComputer.Native.Updates;

/// <summary>
/// Mirrors the macOS <c>BetaChannelStore</c>: a boolean preference that flips
/// the Velopack feed URL between stable and beta. Persisted under
/// <c>HKCU\Software\WaiWai\WaiComputer\BetaChannel</c>.
/// </summary>
public static class BetaChannelStore
{
    private const string KeyPath = @"Software\WaiWai\WaiComputer";
    private const string ValueName = "BetaChannel";

    public static bool IsEnabled
    {
        get
        {
            using var key = Registry.CurrentUser.OpenSubKey(KeyPath, writable: false);
            return key?.GetValue(ValueName) is int i && i != 0;
        }
        set
        {
            using var key = Registry.CurrentUser.CreateSubKey(KeyPath, writable: true)!;
            key.SetValue(ValueName, value ? 1 : 0, RegistryValueKind.DWord);
        }
    }
}
