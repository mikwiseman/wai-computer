using Velopack;
using Velopack.Sources;

namespace WaiComputer.Linux.Updates;

public sealed class LinuxUpdateManager
{
    private readonly UpdateManager _inner;

    public LinuxUpdateManager(string feedUrl, LinuxUpdateChannel channel)
    {
        var feed = LinuxUpdatePolicy.Resolve(feedUrl, channel);
        _inner = new UpdateManager(new SimpleWebSource(feed.FeedUrl), new UpdateOptions { ExplicitChannel = feed.Channel });
    }

    public Task<UpdateInfo?> CheckAsync(CancellationToken ct = default)
    {
        _ = ct;
        return _inner.CheckForUpdatesAsync();
    }

    public Task DownloadAsync(UpdateInfo info, IProgress<int>? progress = null, CancellationToken ct = default)
    {
        _ = ct;
        return _inner.DownloadUpdatesAsync(info, progress: p => progress?.Report(p));
    }

    public void ApplyAndRestart(UpdateInfo info, string[]? restartArgs = null)
    {
        _inner.ApplyUpdatesAndRestart(info, restartArgs);
    }
}
