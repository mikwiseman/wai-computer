namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Marshals an action onto the UI thread. Shared ViewModels that react to events
/// raised on background threads (e.g. the dictation/recording pumps) post their
/// property mutations through this so WinUI/Avalonia bindings update on the right
/// thread. Platforms wrap their dispatcher (WinUI <c>DispatcherQueue</c>, Avalonia
/// <c>Dispatcher.UIThread</c>); tests use <see cref="ImmediateUiDispatcher"/>.
/// </summary>
public interface IUiDispatcher
{
    void Post(Action action);
}

/// <summary>Runs the action inline on the calling thread. For tests and for VMs already on the UI thread.</summary>
public sealed class ImmediateUiDispatcher : IUiDispatcher
{
    public void Post(Action action) => action();
}
