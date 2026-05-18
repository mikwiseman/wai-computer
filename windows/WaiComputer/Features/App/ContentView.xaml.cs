using Microsoft.UI.Xaml.Controls;
using WaiComputer.Features.Apps;
using WaiComputer.Features.Companion;
using WaiComputer.Features.Dictation;
using WaiComputer.Features.Library;
using WaiComputer.Features.Search;
using WaiComputer.Features.Settings;

namespace WaiComputer.Features.App;

public sealed partial class ContentView : UserControl
{
    public ContentView()
    {
        InitializeComponent();
        Nav.SelectedItem = Nav.MenuItems[0];
        ContentFrame.Navigate(typeof(RecordingListView));
    }

    public void HandleMagicLinkToken(string token)
    {
        // Future: route through AuthService.VerifyMagicLinkAsync and surface
        // success/error banner. For now navigate to the recording list — the
        // session restore takes care of populating it once auth completes.
    }

    private void OnNavigationSelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.IsSettingsSelected)
        {
            ContentFrame.Navigate(typeof(SettingsView));
            return;
        }
        if (args.SelectedItemContainer is NavigationViewItem item && item.Tag is string tag)
        {
            switch (tag)
            {
                case "all":
                case "meetings":
                case "notes":
                    ContentFrame.Navigate(typeof(RecordingListView), tag);
                    break;
                case "search":
                    ContentFrame.Navigate(typeof(SearchView));
                    break;
                case "companion":
                    ContentFrame.Navigate(typeof(CompanionChatView));
                    break;
                case "dictation":
                    ContentFrame.Navigate(typeof(DictationHistoryView));
                    break;
                case "apps":
                    ContentFrame.Navigate(typeof(AppsView));
                    break;
            }
        }
    }
}
