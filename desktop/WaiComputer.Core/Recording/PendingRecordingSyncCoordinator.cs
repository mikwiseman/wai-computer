using System.Linq;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Audio;
using WaiComputer.Core.Time;

namespace WaiComputer.Core.Recordings;

/// <summary>
/// Background uploader/retrier for locally-backed recordings, porting the macOS
/// <c>PendingRecordingSyncCoordinator</c>. Each pass walks the backup store and,
/// per recording: skips terminal states (permanent failure / auth required),
/// polls server-processing ones, and otherwise uploads the compressed audio (or
/// re-sends the transcript when there's no audio file). Server-status and
/// API-error outcomes drive the sync-state machine; a fully-ready recording is
/// removed. Passes repeat with exponential backoff until nothing remains.
/// No fallbacks — every failure is recorded as a concrete state.
/// </summary>
public sealed class PendingRecordingSyncCoordinator
{
    private readonly IApiClient _api;
    private readonly RecordingBackupStore _backups;
    private readonly ISystemClock _clock;
    private readonly ILogger<PendingRecordingSyncCoordinator> _logger;

    /// <summary>Raised with the recording id each time a backup syncs and is removed.</summary>
    public event Action<Guid>? RecordingSynced;

    public PendingRecordingSyncCoordinator(
        IApiClient api,
        RecordingBackupStore backups,
        ISystemClock clock,
        ILogger<PendingRecordingSyncCoordinator>? logger = null)
    {
        _api = api;
        _backups = backups;
        _clock = clock;
        _logger = logger ?? NullLogger<PendingRecordingSyncCoordinator>.Instance;
    }

    /// <summary>Exponential backoff (seconds): 5, 10, 20, 40, 80, 160, then capped at 300.</summary>
    internal static int BackoffSeconds(int attempt)
        => Math.Min(300, 5 * (int)Math.Pow(2, Math.Min(attempt - 1, 6)));

    /// <summary>Run passes with backoff until all backups drain or <paramref name="ct"/> cancels.</summary>
    public async Task RunAsync(CancellationToken ct)
    {
        var attempt = 0;
        while (!ct.IsCancellationRequested)
        {
            if (!_backups.ListBackups().Any())
            {
                return;
            }

            var remaining = await SyncPassAsync(ct).ConfigureAwait(false);
            if (remaining == 0)
            {
                return;
            }

            attempt++;
            await _clock.Delay(TimeSpan.FromSeconds(BackoffSeconds(attempt)), ct).ConfigureAwait(false);
        }
    }

    /// <summary>One pass over every backup. Returns the count that still needs syncing.</summary>
    public async Task<int> SyncPassAsync(CancellationToken ct)
    {
        var remaining = 0;
        foreach (var manifest in _backups.ListBackups().ToList())
        {
            ct.ThrowIfCancellationRequested();
            if (manifest.SyncState is RecordingBackupSyncState.PermanentFailure or RecordingBackupSyncState.AuthRequired)
            {
                continue; // terminal — not counted as "remaining to sync"
            }

            if (!await SyncOneAsync(manifest, ct).ConfigureAwait(false))
            {
                remaining++;
            }
        }
        return remaining;
    }

    private async Task<bool> SyncOneAsync(RecordingBackupManifest manifest, CancellationToken ct)
    {
        var id = manifest.RecordingId;
        var idText = id.ToString();
        try
        {
            _backups.RecordSyncAttempt(id, _clock.UtcNow);

            RecordingDetail detail;
            if (manifest.SyncState == RecordingBackupSyncState.ServerProcessing)
            {
                detail = await _api.GetRecordingAsync(idText, ct).ConfigureAwait(false);
            }
            else if (manifest.HasAudioFile && File.Exists(_backups.AudioPath(id)))
            {
                detail = await UploadAudioAsync(id, ct).ConfigureAwait(false);
            }
            else
            {
                var segments = SegmentsForSync(manifest);
                var duration = (int)Math.Round(manifest.DurationSeconds);
                detail = await _api.SaveLiveTranscriptAsync(idText, segments, duration, ct).ConfigureAwait(false);
            }

            if (detail.Status == RecordingStatus.Failed)
            {
                _backups.MarkRetryableFailure(id, detail.FailureCode);
                return false;
            }

            if (detail.Status != RecordingStatus.Ready)
            {
                if (detail.Status is RecordingStatus.Processing or RecordingStatus.Uploading)
                {
                    _backups.MarkServerProcessing(id, idText);
                }
                return false;
            }

            _backups.Remove(id);
            RecordingSynced?.Invoke(id);
            return true;
        }
        catch (ApiError.Unauthorized)
        {
            _backups.MarkAuthenticationRequired(id);
            return false;
        }
        catch (ApiError.HttpError http) when (http.StatusCode is 413 or 404)
        {
            _backups.MarkPermanentFailure(id);
            return false;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _backups.MarkRetryableFailure(id, null);
            _logger.LogWarning(ex, "Sync failed for recording {Id}", id);
            return false;
        }
    }

    private async Task<RecordingDetail> UploadAudioAsync(Guid id, CancellationToken ct)
    {
        // Compress the raw WAV to Ogg-Opus once and reuse across retries.
        var wavPath = _backups.AudioPath(id);
        var opusPath = Path.ChangeExtension(wavPath, ".ogg");
        if (!(File.Exists(opusPath) && new FileInfo(opusPath).Length > 0))
        {
            AudioCompressor.CompressWavToOpus(wavPath, opusPath);
        }

        await using var stream = new FileStream(opusPath, FileMode.Open, FileAccess.Read);
        return await _api.UploadRecordingAudioAsync(id.ToString(), stream, stream.Length, "recording.ogg", "audio/ogg", ct: ct).ConfigureAwait(false);
    }

    private IReadOnlyList<LiveTranscriptSegment> SegmentsForSync(RecordingBackupManifest manifest)
    {
        var persisted = _backups.GetSegments(manifest.RecordingId);
        if (persisted is { Count: > 0 })
        {
            return persisted;
        }

        var transcript = manifest.Transcript?.Trim();
        if (string.IsNullOrEmpty(transcript))
        {
            return Array.Empty<LiveTranscriptSegment>();
        }

        var durationSeconds = Math.Max((int)Math.Round(manifest.DurationSeconds), 1);
        return new[]
        {
            new LiveTranscriptSegment(transcript, Speaker: null, IsFinal: true, StartMs: 0, EndMs: durationSeconds * 1000L, Confidence: 1.0),
        };
    }
}
