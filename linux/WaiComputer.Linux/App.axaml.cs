using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using WaiComputer.Core.Api;
using WaiComputer.Core.Audio;
using WaiComputer.Core.Monitoring;
using WaiComputer.Core.Recordings;
using WaiComputer.Linux.Audio;
using WaiComputer.Linux.Auth;
using WaiComputer.Linux.Platform;
using WaiComputer.Linux.ViewModels;

namespace WaiComputer.Linux;

public partial class App : Application
{
    public static IServiceProvider Services { get; private set; } = null!;
    public static LinuxAppSettings Settings { get; private set; } = null!;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        var configuration = LoadConfig();
        Settings = configuration.Get<LinuxAppSettings>()
            ?? throw new InvalidOperationException("appsettings.json is missing or malformed.");

        Services = BuildServices(Settings);

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var window = new MainWindow
            {
                DataContext = Services.GetRequiredService<MainWindowViewModel>(),
            };
            desktop.MainWindow = window;
        }

        base.OnFrameworkInitializationCompleted();
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

    private static IServiceProvider BuildServices(LinuxAppSettings settings)
    {
        var services = new ServiceCollection();
        services.AddLogging();

        services.AddSingleton<ICommandRunner, ProcessCommandRunner>();
        services.AddSingleton<ToolProbe>();
        services.AddSingleton<PortalCapabilityProbe>();
        services.AddSingleton<PulseAudioDeviceProbe>();
        services.AddSingleton<LinuxAudioCaptureFactory>();
        services.AddSingleton<LinuxCapabilityProbe>();

        services.AddSingleton(_ => new ApiClient(new Uri(settings.Api.BaseUrl)));
        services.AddSingleton<IApiClient>(sp => sp.GetRequiredService<ApiClient>());
        services.AddSingleton<LinuxSecretServiceSessionStore>();
        services.AddSingleton<ILinuxSessionStore>(sp => sp.GetRequiredService<LinuxSecretServiceSessionStore>());
        services.AddSingleton(_ =>
        {
            var pendingDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "WaiComputer",
                "PendingTranscripts");
            return new RecordingBackupStore(pendingDir);
        });
        services.AddSingleton(_ => new AudioCaptureConfig(
            SampleRate: settings.Audio.RealtimeSampleRate,
            MixToMono: !settings.Audio.SeparateChannels,
            SeparateChannels: settings.Audio.SeparateChannels,
            FrameSizeSamples: settings.Audio.FrameSizeSamples));

        if (IsRealSentryDsn(settings.Sentry.Dsn))
        {
            services.AddSingleton(_ => new SentryHelper(settings.Sentry.Dsn));
        }

        services.AddSingleton<MainWindowViewModel>();
        return services.BuildServiceProvider();
    }

    private static bool IsRealSentryDsn(string? dsn) =>
        !string.IsNullOrWhiteSpace(dsn) && !dsn.Contains("REPLACE_ME", StringComparison.Ordinal);
}

public sealed class LinuxAppSettings
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
public sealed record AudioSettings(int MicrophoneSampleRate, int RealtimeSampleRate, int ChannelCount, int FrameSizeSamples, bool SeparateChannels);
public sealed record DictationSettings(string DefaultHotkey, int HoldThresholdMilliseconds, int DoubleTapIntervalMilliseconds, int ModifierReleaseTimeoutMilliseconds);
