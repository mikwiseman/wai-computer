using System.Diagnostics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using WaiComputer.Native.Platform;

namespace WaiComputer.Features.Settings.Sections;

public sealed partial class AdvancedSection : UserControl
{
    public AdvancedSection()
    {
        InitializeComponent();
        AutoStartToggle.IsOn = AutoStartManager.IsEnabled;
        AutoStartToggle.Toggled += (_, _) =>
        {
            if (AutoStartToggle.IsOn)
            {
                AutoStartManager.Enable(Environment.ProcessPath ?? "WaiComputer.exe");
            }
            else
            {
                AutoStartManager.Disable();
            }
        };
    }

    private void OnRevealData(object sender, RoutedEventArgs e)
    {
        var path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "WaiComputer");
        if (Directory.Exists(path))
        {
            Process.Start(new ProcessStartInfo { FileName = path, UseShellExecute = true });
        }
    }

    private void OnResetSession(object sender, RoutedEventArgs e)
    {
        var store = global::WaiComputer.App.Services.GetService(typeof(WaiComputer.Core.Auth.SessionStore)) as WaiComputer.Core.Auth.SessionStore;
        store?.Clear();
    }
}
