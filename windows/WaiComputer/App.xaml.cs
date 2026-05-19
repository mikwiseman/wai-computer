using System;
using System.IO;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;
using WaiComputer.Core.Api;
using WaiComputer.Core.Auth;
using WaiComputer.Core.Monitoring;
using WaiComputer.Core.Recordings;
using WaiComputer.Native.Platform;

namespace WaiComputer;

public partial class App : Application
{
    public static IServiceProvider Services { get; private set; } = null!;
    public static AppSettings Settings { get; private set; } = null!;
    private Window? _mainWindow;

    public App()
    {
        InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        if (SingleInstanceCoordinator.RedirectIfNotPrimary(OnActivatedFromOtherInstance))
        {
            Current.Exit();
            return;
        }

        var config = LoadConfig();
        Settings = config.Get<AppSettings>() ?? throw new InvalidOperationException("appsettings.json is missing or malformed.");

        Services = BuildServices(Settings);
        WindowsAclHelper.Attach();
        UrlSchemeRegistrar.Register(Environment.ProcessPath ?? "WaiComputer.exe");

        var sentry = Services.GetService<SentryHelper>();
        _ = sentry; // construct so it initialises

        _mainWindow = new MainWindow();
        _mainWindow.Activate();
    }

    private static IConfigurationRoot LoadConfig()
    {
        var basePath = AppContext.BaseDirectory;
        return new ConfigurationBuilder()
            .SetBasePath(basePath)
            .AddJsonFile("appsettings.json", optional: false)
            .AddJsonFile("appsettings.user.json", optional: true, reloadOnChange: true)
            .Build();
    }

    private static IServiceProvider BuildServices(AppSettings settings)
    {
        var services = new ServiceCollection();
        services.AddLogging();

        services.AddSingleton(_ => new ApiClient(new Uri(settings.Api.BaseUrl)));
        services.AddSingleton<IApiClient>(sp => sp.GetRequiredService<ApiClient>());
        services.AddSingleton<ISessionProtector>(_ => new DpapiSessionProtector());
        services.AddSingleton(sp =>
        {
            var dir = SessionDirectory();
            return new SessionStore(Path.Combine(dir, "session.json"), sp.GetRequiredService<ISessionProtector>());
        });
        services.AddSingleton(_ =>
        {
            var dir = Path.Combine(SessionDirectory(), "PendingTranscripts");
            return new RecordingBackupStore(dir);
        });
        if (IsRealSentryDsn(settings.Sentry.Dsn))
        {
            services.AddSingleton(_ => new SentryHelper(settings.Sentry.Dsn));
        }
        services.AddSingleton<NetworkMonitor>();

        return services.BuildServiceProvider();
    }

    private static bool IsRealSentryDsn(string? dsn) =>
        !string.IsNullOrWhiteSpace(dsn) && !dsn.Contains("REPLACE_ME", StringComparison.Ordinal);

    private static string SessionDirectory()
    {
        var roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        var dir = Path.Combine(roaming, "WaiComputer");
        Directory.CreateDirectory(dir);
        return dir;
    }

    private void OnActivatedFromOtherInstance(object? sender, AppActivationArguments args)
    {
        // Forward magic-link / URL activation from the redirected second
        // instance to the running window.
        if (_mainWindow is MainWindow mw)
        {
            mw.DispatcherQueue?.TryEnqueue(() => mw.HandleActivation(args));
        }
    }
}

public sealed class AppSettings
{
    public required ApiSettings Api { get; init; }
    public required SentrySettings Sentry { get; init; }
    public required UpdateSettings Updates { get; init; }
    public required AudioSettings Audio { get; init; }
    public required DictationSettings Dictation { get; init; }
}

public sealed record ApiSettings(string BaseUrl, int RequestTimeoutSeconds, int UploadTimeoutSeconds, long MaxUploadBytes);
public sealed record SentrySettings(string Dsn, double TracesSampleRate, double ProfilesSampleRate, bool AttachScreenshot, bool SendDefaultPii);
public sealed record UpdateSettings(string FeedUrl, bool AutomaticChecksEnabled, int CheckIntervalSeconds);
public sealed record AudioSettings(int MicrophoneSampleRate, int RealtimeSampleRate, int ChannelCount, int FrameSizeSamples, bool UseProcessIsolatedLoopback, bool SeparateChannels);
public sealed record DictationSettings(string DefaultHotkey, int HoldThresholdMilliseconds, int DoubleTapIntervalMilliseconds, int ModifierReleaseTimeoutMilliseconds);
