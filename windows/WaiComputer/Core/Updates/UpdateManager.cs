using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Velopack;
using Velopack.Sources;

namespace WaiComputer.Native.Updates;

/// <summary>
/// Velopack wrapper. Stable + beta channels live at
/// <c>https://wai.computer/releases/windows/</c> with feed files
/// <c>releases.win.json</c> (stable) and <c>releases.win.beta.json</c> (beta).
/// </summary>
public sealed class UpdateManager
{
    private readonly Velopack.UpdateManager _inner;
    private readonly ILogger<UpdateManager> _logger;

    public UpdateManager(string feedUrl, bool beta, ILogger<UpdateManager>? logger = null)
    {
        _logger = logger ?? NullLogger<UpdateManager>.Instance;
        var channel = beta ? "beta" : null;
        var source = new SimpleWebSource(feedUrl);
        _inner = new Velopack.UpdateManager(source, new UpdateOptions { ExplicitChannel = channel });
    }

    public async Task<UpdateInfo?> CheckAsync(CancellationToken ct = default)
    {
        try { return await _inner.CheckForUpdatesAsync().ConfigureAwait(false); }
        catch (Exception ex) { _logger.LogWarning(ex, "Update check failed"); return null; }
    }

    public async Task DownloadAsync(UpdateInfo info, IProgress<int>? progress = null, CancellationToken ct = default)
    {
        await _inner.DownloadUpdatesAsync(info, progress: p => progress?.Report(p)).ConfigureAwait(false);
    }

    public void ApplyAndRestart(UpdateInfo info, string[]? restartArgs = null)
        => _inner.ApplyUpdatesAndRestart(info, restartArgs);
}
