using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
namespace WaiComputer.Features.Companion;
public sealed partial class CompanionChatView : Page
{
    public CompanionChatView() => InitializeComponent();
    private void OnSend(object sender, RoutedEventArgs e) { /* TODO wire to ApiClient.StreamCompanionMessageAsync */ }
}
