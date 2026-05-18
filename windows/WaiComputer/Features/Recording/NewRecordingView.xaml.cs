using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
namespace WaiComputer.Features.Recording;
public sealed partial class NewRecordingView : Page
{
    public NewRecordingView() => InitializeComponent();
    private void OnStart(object sender, RoutedEventArgs e) { Frame?.Navigate(typeof(LiveRecordingView)); }
    private void OnCancel(object sender, RoutedEventArgs e) { Frame?.GoBack(); }
}
