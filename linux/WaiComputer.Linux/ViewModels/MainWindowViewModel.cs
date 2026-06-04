using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using Avalonia.Media;
using CommunityToolkit.Mvvm.Input;
using WaiComputer.Core.Auth;
using WaiComputer.Linux.Platform;

namespace WaiComputer.Linux.ViewModels;

public sealed class MainWindowViewModel : INotifyPropertyChanged
{
    private readonly LinuxCapabilityProbe _capabilities;
    private string _selectedSection = "All recordings";
    private string _statusText = "Checking Linux desktop capabilities...";
    private string _sectionDetail = "Your searchable recording library, summaries, transcript detail, and upload state live here.";
    private string _workSurfaceTitle = "Recordings";
    private string _workSurfaceBody = "Recordings will sync with https://wai.computer after authentication. Linux v1 uses the shared desktop API models and recording backup store.";

    public MainWindowViewModel(LinuxCapabilityProbe capabilities)
    {
        _capabilities = capabilities;
        NavigateCommand = new RelayCommand<string>(Navigate);
        StartRecordingCommand = new RelayCommand(() => StatusText = "Recording start requested. Audio capability gates must pass before capture starts.");
        StopRecordingCommand = new RelayCommand(() => StatusText = "Recording stopped.");
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public IReadOnlyList<string> Sections { get; } =
    [
        "All recordings",
        "Meetings",
        "Notes",
        "Search",
        "Companion",
        "Dictation",
        "Billing",
        "MCP",
        "Settings",
    ];

    public ObservableCollection<CapabilityRow> CapabilityRows { get; } = [];
    public IRelayCommand<string> NavigateCommand { get; }
    public IRelayCommand StartRecordingCommand { get; }
    public IRelayCommand StopRecordingCommand { get; }

    public string SelectedSection
    {
        get => _selectedSection;
        private set => SetField(ref _selectedSection, value);
    }

    public string StatusText
    {
        get => _statusText;
        private set => SetField(ref _statusText, value);
    }

    public string SectionDetail
    {
        get => _sectionDetail;
        private set => SetField(ref _sectionDetail, value);
    }

    public string WorkSurfaceTitle
    {
        get => _workSurfaceTitle;
        private set => SetField(ref _workSurfaceTitle, value);
    }

    public string WorkSurfaceBody
    {
        get => _workSurfaceBody;
        private set => SetField(ref _workSurfaceBody, value);
    }

    public async Task RefreshCapabilitiesAsync(CancellationToken ct = default)
    {
        var report = await _capabilities.ProbeAsync(ct);
        CapabilityRows.Clear();
        foreach (var status in report.All)
        {
            CapabilityRows.Add(CapabilityRow.From(status));
        }

        StatusText = report.All.All(c => c.IsSupported)
            ? "Ready on this Linux session."
            : "Some Linux capabilities need attention.";
    }

    public void HandleStartupArgs(IEnumerable<string> args)
    {
        foreach (var arg in args)
        {
            if (MagicLinkUrl.TryParse(arg, out var token))
            {
                StatusText = $"Magic link received ({token.Length} byte token).";
                Navigate("Settings");
                return;
            }
        }
    }

    private void Navigate(string? section)
    {
        if (string.IsNullOrWhiteSpace(section))
        {
            return;
        }

        SelectedSection = section;
        (SectionDetail, WorkSurfaceTitle, WorkSurfaceBody) = section switch
        {
            "Search" => ("Search recordings, people, entities, summaries, and transcript text.", "Search", "The Linux client shares API search models with Windows and macOS so server-side relevance stays identical."),
            "Companion" => ("Ask questions against your recording memory and app context.", "Companion", "Companion chat uses the existing desktop API contract; no Linux-only prompt path is introduced."),
            "Dictation" => ("Push-to-talk and hands-free dictation with explicit Wayland/X11 capability checks.", "Dictation", "Wayland depends on GlobalShortcuts, RemoteDesktop, and Clipboard portals. X11 uses XGrabKey/XTest-compatible tools."),
            "Billing" => ("Subscription and account billing status.", "Billing", "Billing opens through wai.computer with the same authenticated account state."),
            "MCP" => ("In-app MCP connection instructions.", "MCP", "Production MCP URL: https://wai.computer/mcp"),
            "Settings" => ("Account, audio, dictation, updates, privacy, and Linux capability status.", "Settings", "Linux stores auth in Secret Service and updates through Velopack AppImage feeds."),
            "Meetings" => ("Meeting recordings and summaries.", "Meetings", "Meeting filters use the shared recording model."),
            "Notes" => ("Quick notes and dictated captures.", "Notes", "Notes stay in the same library and sync pipeline as other recordings."),
            _ => ("Your searchable recording library, summaries, transcript detail, and upload state live here.", "Recordings", "Recordings will sync with https://wai.computer after authentication. Linux v1 uses the shared desktop API models and recording backup store."),
        };
    }

    private void SetField(ref string field, string value, [CallerMemberName] string? propertyName = null)
    {
        if (field == value)
        {
            return;
        }

        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}

public sealed record CapabilityRow(string Name, string State, string Detail, string? RecoveryAction, IBrush StateBrush)
{
    public static CapabilityRow From(CapabilityStatus status)
    {
        var brush = status.State switch
        {
            LinuxCapabilityState.Supported => Brushes.ForestGreen,
            LinuxCapabilityState.PermissionRequired => Brushes.DarkGoldenrod,
            _ => Brushes.Firebrick,
        };

        return new CapabilityRow(status.Name, status.State.ToString(), status.Detail, status.RecoveryAction, brush);
    }
}
