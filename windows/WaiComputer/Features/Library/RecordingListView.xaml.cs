using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using WaiComputer.Features.Recording;

namespace WaiComputer.Features.Library;

public sealed partial class RecordingListView : Page
{
    public RecordingListView() => InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        TitleLabel.Text = e.Parameter switch
        {
            "meetings" => "Meetings",
            "notes" => "Notes",
            _ => "All recordings",
        };
    }

    private void OnNew(object sender, RoutedEventArgs e) => Frame?.Navigate(typeof(NewRecordingView));
}
