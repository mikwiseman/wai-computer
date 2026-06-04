using Microsoft.Win32;

namespace WaiComputer.Native.Platform;

/// <summary>
/// "Start with Windows" toggle backed by the
/// <c>HKCU\Software\Microsoft\Windows\CurrentVersion\Run</c> registry key.
/// </summary>
public static class AutoStartManager
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "WaiComputer";

    public static bool IsEnabled
    {
        get
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKey, writable: false);
            return key?.GetValue(ValueName) is string s && !string.IsNullOrEmpty(s);
        }
    }

    public static void Enable(string executablePath)
    {
        using var key = Registry.CurrentUser.CreateSubKey(RunKey, writable: true)
            ?? throw new InvalidOperationException("Unable to open Run registry key.");
        key.SetValue(ValueName, $"\"{executablePath}\" --launched-on-startup");
    }

    public static void Disable()
    {
        using var key = Registry.CurrentUser.OpenSubKey(RunKey, writable: true);
        key?.DeleteValue(ValueName, throwOnMissingValue: false);
    }
}
