using Avalonia;
using Velopack;

namespace WaiComputer.Linux;

public static class Program
{
    public static string[] StartupArgs { get; private set; } = [];

    [STAThread]
    public static int Main(string[] args)
    {
        StartupArgs = args;
        VelopackApp.Build().Run();
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
        return 0;
    }

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
}
