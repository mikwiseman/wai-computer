using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace WaiComputer.Features.Recording;

public sealed partial class LiveRecordingView : Page
{
    public LiveRecordingView() => InitializeComponent();
    private void OnPause(object sender, RoutedEventArgs e) { /* TODO wire to RecordingViewModel */ }
    private void OnStop(object sender, RoutedEventArgs e) { /* TODO wire to RecordingViewModel */ }
}
