using Microsoft.Windows.AppLifecycle;
using Windows.ApplicationModel.Activation;

namespace WaiComputer.Native.Platform;

/// <summary>
/// Ensures a second launch of WaiComputer.exe redirects to the first
/// instance (preserving magic-link URL activation) and exits. Uses
/// <see cref="AppInstance"/> from Windows App SDK.
/// </summary>
public static class SingleInstanceCoordinator
{
    public static bool RedirectIfNotPrimary(EventHandler<AppActivationArguments>? onActivated)
    {
        var args = AppInstance.GetCurrent().GetActivatedEventArgs();
        var instance = AppInstance.FindOrRegisterForKey("WaiComputerSingleton");
        if (instance.IsCurrent)
        {
            if (onActivated is not null)
            {
                instance.Activated += onActivated;
            }
            return false;
        }
        instance.RedirectActivationToAsync(args).AsTask().GetAwaiter().GetResult();
        return true;
    }
}
