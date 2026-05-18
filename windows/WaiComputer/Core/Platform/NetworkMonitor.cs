using System.Net.NetworkInformation;

namespace WaiComputer.Native.Platform;

/// <summary>
/// Thin wrapper around <see cref="NetworkChange.NetworkAvailabilityChanged"/>.
/// Used by PendingRecordingSync to resume queued uploads when the user
/// regains connectivity.
/// </summary>
public sealed class NetworkMonitor : IDisposable
{
    public event Action? CameOnline;
    public event Action? WentOffline;

    public NetworkMonitor()
    {
        NetworkChange.NetworkAvailabilityChanged += OnAvailabilityChanged;
    }

    public bool IsAvailable => NetworkInterface.GetIsNetworkAvailable();

    private void OnAvailabilityChanged(object? sender, NetworkAvailabilityEventArgs e)
    {
        if (e.IsAvailable) CameOnline?.Invoke();
        else WentOffline?.Invoke();
    }

    public void Dispose()
    {
        NetworkChange.NetworkAvailabilityChanged -= OnAvailabilityChanged;
    }
}
