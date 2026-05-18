using Microsoft.Win32;

namespace WaiComputer.Native.Platform;

/// <summary>
/// Registers the <c>waicomputer://</c> URL scheme under
/// <c>HKCU\Software\Classes</c> so OS-level magic-link clicks land in our app.
/// </summary>
public static class UrlSchemeRegistrar
{
    private const string Scheme = "waicomputer";

    public static void Register(string executablePath)
    {
        using var root = Registry.CurrentUser.CreateSubKey($@"Software\Classes\{Scheme}", writable: true)!;
        root.SetValue(string.Empty, $"URL:{Scheme} Protocol");
        root.SetValue("URL Protocol", string.Empty);

        using var icon = root.CreateSubKey("DefaultIcon")!;
        icon.SetValue(string.Empty, $"\"{executablePath}\",0");

        using var command = root.CreateSubKey(@"shell\open\command")!;
        command.SetValue(string.Empty, $"\"{executablePath}\" \"%1\"");
    }

    public static void Unregister()
    {
        Registry.CurrentUser.DeleteSubKeyTree($@"Software\Classes\{Scheme}", throwOnMissingSubKey: false);
    }

    public static bool IsRegistered()
    {
        using var key = Registry.CurrentUser.OpenSubKey($@"Software\Classes\{Scheme}\shell\open\command");
        return key?.GetValue(string.Empty) is string s && !string.IsNullOrEmpty(s);
    }
}
