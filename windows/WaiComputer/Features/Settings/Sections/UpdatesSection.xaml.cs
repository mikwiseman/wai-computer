using System.Reflection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using WaiComputer.Native.Updates;

namespace WaiComputer.Features.Settings.Sections;

public sealed partial class UpdatesSection : UserControl
{
    public UpdatesSection()
    {
        InitializeComponent();
        BetaToggle.IsOn = BetaChannelStore.IsEnabled;
        BetaToggle.Toggled += (_, _) => BetaChannelStore.IsEnabled = BetaToggle.IsOn;
        var v = Assembly.GetEntryAssembly()?.GetName().Version?.ToString() ?? "dev";
        VersionLabel.Text = $"Version {v}";
    }

    private async void OnCheck(object sender, RoutedEventArgs e)
    {
        var settings = global::WaiComputer.App.Settings;
        var mgr = new UpdateManager(settings.Updates.FeedUrl, BetaChannelStore.IsEnabled);
        var info = await mgr.CheckAsync();
        VersionLabel.Text = info is null ? "You're on the latest version." : $"Update available: {info.TargetFullRelease.Version}";
    }
}
