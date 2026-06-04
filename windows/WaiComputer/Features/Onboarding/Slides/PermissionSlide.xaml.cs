using System.Diagnostics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using WaiComputer.Native.Platform;

namespace WaiComputer.Features.Onboarding.Slides;

public sealed partial class PermissionSlide : Page
{
    public PermissionSlide()
    {
        InitializeComponent();
        Loaded += (_, _) => Refresh();
    }

    private void Refresh()
    {
        if (PermissionMonitor.MicrophoneAccessible())
        {
            StatusBar.Severity = InfoBarSeverity.Success;
            StatusBar.Title = "Microphone available";
            StatusBar.Message = "You're all set.";
        }
        else
        {
            StatusBar.Severity = InfoBarSeverity.Warning;
            StatusBar.Title = "Microphone blocked";
            StatusBar.Message = "Allow desktop apps to access your microphone in Settings.";
        }
    }

    private void OnOpenSettings(object sender, RoutedEventArgs e)
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = PermissionMonitor.MicrophoneSettingsUri,
            UseShellExecute = true,
        });
    }
}
