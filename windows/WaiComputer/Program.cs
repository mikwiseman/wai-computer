using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Velopack;
using WinRT;

namespace WaiComputer;

public static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        // Velopack must run BEFORE the UI thread is initialised so the
        // installer/updater hand-off works correctly.
        VelopackApp.Build().Run();

        ComWrappersSupport.InitializeComWrappers();
        Application.Start(p =>
        {
            var ctx = new DispatcherQueueSynchronizationContext(DispatcherQueue.GetForCurrentThread());
            System.Threading.SynchronizationContext.SetSynchronizationContext(ctx);
            _ = new App();
        });
        return 0;
    }
}
