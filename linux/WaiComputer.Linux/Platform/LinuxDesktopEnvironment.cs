namespace WaiComputer.Linux.Platform;

public sealed record LinuxDesktopEnvironment(
    string SessionType,
    string CurrentDesktop,
    string? WaylandDisplay,
    string? X11Display,
    string XdgConfigHome,
    string XdgDataHome)
{
    public bool IsWayland => string.Equals(SessionType, "wayland", StringComparison.OrdinalIgnoreCase);
    public bool IsX11 => string.Equals(SessionType, "x11", StringComparison.OrdinalIgnoreCase) || !string.IsNullOrWhiteSpace(X11Display);

    public static LinuxDesktopEnvironment FromCurrentProcess() => From(Environment.GetEnvironmentVariables()
        .Cast<System.Collections.DictionaryEntry>()
        .ToDictionary(e => (string)e.Key, e => e.Value?.ToString(), StringComparer.Ordinal));

    public static LinuxDesktopEnvironment From(IReadOnlyDictionary<string, string?> env)
    {
        string? Get(string key) => env.TryGetValue(key, out var value) ? value : null;

        var home = Get("HOME") ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var configHome = Get("XDG_CONFIG_HOME");
        if (string.IsNullOrWhiteSpace(configHome))
        {
            configHome = Path.Combine(home, ".config");
        }

        var dataHome = Get("XDG_DATA_HOME");
        if (string.IsNullOrWhiteSpace(dataHome))
        {
            dataHome = Path.Combine(home, ".local", "share");
        }

        return new LinuxDesktopEnvironment(
            Get("XDG_SESSION_TYPE") ?? "",
            Get("XDG_CURRENT_DESKTOP") ?? "",
            Get("WAYLAND_DISPLAY"),
            Get("DISPLAY"),
            configHome,
            dataHome);
    }
}
