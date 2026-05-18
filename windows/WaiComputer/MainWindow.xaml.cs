using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;
using Windows.ApplicationModel.Activation;
using WaiComputer.Core.Auth;

namespace WaiComputer;

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        ExtendsContentIntoTitleBar = true;
        Title = "WaiComputer";
    }

    public void HandleActivation(AppActivationArguments args)
    {
        if (args.Kind != ExtendedActivationKind.Protocol) return;
        if (args.Data is not IProtocolActivatedEventArgs protocol) return;
        if (!MagicLinkUrl.TryParse(protocol.Uri.ToString(), out var token)) return;

        DispatcherQueue.TryEnqueue(() => Content.HandleMagicLinkToken(token));
    }
}
