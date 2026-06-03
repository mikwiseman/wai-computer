using Avalonia.Controls;
using WaiComputer.Linux.ViewModels;

namespace WaiComputer.Linux;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        Opened += async (_, _) =>
        {
            if (DataContext is MainWindowViewModel vm)
            {
                await vm.RefreshCapabilitiesAsync();
                vm.HandleStartupArgs(Program.StartupArgs);
            }
        };
    }
}
