using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Recordings;

/// <summary>
/// Local-first store for recordings that have not yet been uploaded (network
/// dropped mid-upload, auth expired, server failure, etc.). On-disk layout
/// mirrors the Mac:
/// <code>
///   {root}/{recordingId}/manifest.json
///   {root}/{recordingId}/segments.json
///   {root}/{recordingId}/recording.wav   (optional)
/// </code>
/// On Windows <c>{root}</c> defaults to
/// <c>%APPDATA%\WaiComputer\PendingTranscripts</c>.
///
/// Thread-safe: every read/mutate path holds a store-wide lock, so manifest
/// read-modify-write can't lose updates and a Remove can't race a concurrent
/// mutation (the recording session and the background sync coordinator both
/// touch this store).
/// </summary>
public sealed class RecordingBackupStore
{
    private readonly string _root;
    private readonly ILogger<RecordingBackupStore> _logger;
    private readonly object _lock = new();

    public RecordingBackupStore(string root, ILogger<RecordingBackupStore>? logger = null)
    {
        _root = root ?? throw new ArgumentNullException(nameof(root));
        _logger = logger ?? NullLogger<RecordingBackupStore>.Instance;
        Directory.CreateDirectory(_root);
    }

    private string DirFor(Guid id) => Path.Combine(_root, id.ToString("N"));
    private string ManifestPath(Guid id) => Path.Combine(DirFor(id), "manifest.json");
    private string SegmentsPath(Guid id) => Path.Combine(DirFor(id), "segments.json");
    public string AudioPath(Guid id) => Path.Combine(DirFor(id), "recording.wav");

    public void Save(RecordingBackupManifest manifest, IReadOnlyList<LiveTranscriptSegment> segments, ReadOnlySpan<byte> audio = default)
    {
        var manifestJson = JsonSerializer.SerializeToUtf8Bytes(manifest, WaiJson.Options);
        var segmentsJson = JsonSerializer.SerializeToUtf8Bytes(segments, WaiJson.Options);
        var audioBytes = audio.IsEmpty ? null : audio.ToArray();

        lock (_lock)
        {
            Directory.CreateDirectory(DirFor(manifest.RecordingId));
            AtomicWrite(ManifestPath(manifest.RecordingId), manifestJson);
            AtomicWrite(SegmentsPath(manifest.RecordingId), segmentsJson);
            if (audioBytes is not null)
            {
                AtomicWrite(AudioPath(manifest.RecordingId), audioBytes);
            }
        }
    }

    public IReadOnlyList<RecordingBackupManifest> ListBackups()
    {
        lock (_lock)
        {
            var result = new List<RecordingBackupManifest>();
            if (!Directory.Exists(_root)) return result;
            foreach (var dir in Directory.EnumerateDirectories(_root))
            {
                var manifest = Path.Combine(dir, "manifest.json");
                if (!File.Exists(manifest)) continue;
                try
                {
                    var parsed = JsonSerializer.Deserialize<RecordingBackupManifest>(File.ReadAllBytes(manifest), WaiJson.Options);
                    if (parsed is not null) result.Add(parsed);
                }
                catch (JsonException ex) { _logger.LogWarning(ex, "Malformed backup manifest at {Path}", manifest); }
                catch (IOException ex) { _logger.LogWarning(ex, "Unreadable backup manifest at {Path}", manifest); }
            }
            return result;
        }
    }

    public RecordingBackupManifest? GetManifest(Guid id)
    {
        lock (_lock)
        {
            var path = ManifestPath(id);
            if (!File.Exists(path)) return null;
            try { return JsonSerializer.Deserialize<RecordingBackupManifest>(File.ReadAllBytes(path), WaiJson.Options); }
            catch (JsonException) { return null; }
            catch (IOException) { return null; }
        }
    }

    public IReadOnlyList<LiveTranscriptSegment>? GetSegments(Guid id)
    {
        lock (_lock)
        {
            var path = SegmentsPath(id);
            if (!File.Exists(path)) return null;
            try { return JsonSerializer.Deserialize<List<LiveTranscriptSegment>>(File.ReadAllBytes(path), WaiJson.Options); }
            catch (JsonException) { return null; }
            catch (IOException) { return null; }
        }
    }

    public void RecordSaveFailure(Guid id, string errorMessage)
        => UpdateManifest(id, m => m with { LastErrorMessage = errorMessage, UpdatedAt = DateTimeOffset.UtcNow });

    public void MarkPermanentFailure(Guid id)
        => UpdateManifest(id, m => m with { IsPermanentFailure = true, SyncState = RecordingBackupSyncState.PermanentFailure, UpdatedAt = DateTimeOffset.UtcNow });

    public void MarkAuthenticationRequired(Guid id)
        => UpdateManifest(id, m => m with { RequiresAuthentication = true, SyncState = RecordingBackupSyncState.AuthRequired, UpdatedAt = DateTimeOffset.UtcNow });

    public void MarkHasAudioFile(Guid id, bool hasAudio)
        => UpdateManifest(id, m => m with { HasAudioFile = hasAudio, UpdatedAt = DateTimeOffset.UtcNow });

    /// <summary>Server accepted the upload and is transcribing.</summary>
    public void MarkServerProcessing(Guid id, string? serverJobId = null)
        => UpdateManifest(id, m => m with { SyncState = RecordingBackupSyncState.ServerProcessing, ServerJobId = serverJobId ?? m.ServerJobId, UpdatedAt = DateTimeOffset.UtcNow });

    /// <summary>Server processing resolved; return to a clean local-ready baseline.</summary>
    public void ClearServerProcessing(Guid id)
        => UpdateManifest(id, m => m with { SyncState = RecordingBackupSyncState.LocalReady, ServerJobId = null, UpdatedAt = DateTimeOffset.UtcNow });

    /// <summary>Re-authentication succeeded; lift the auth gate so the coordinator retries.</summary>
    public void ClearAuthenticationRequired(Guid id)
        => UpdateManifest(id, m => m with
        {
            RequiresAuthentication = false,
            SyncState = m.SyncState == RecordingBackupSyncState.AuthRequired ? RecordingBackupSyncState.LocalReady : m.SyncState,
            UpdatedAt = DateTimeOffset.UtcNow,
        });

    /// <summary>A transient upload failure — eligible for backoff retry.</summary>
    public void MarkRetryableFailure(Guid id, string? failureCode)
        => UpdateManifest(id, m => m with { SyncState = RecordingBackupSyncState.RetryableFailure, LastFailureCode = failureCode, UpdatedAt = DateTimeOffset.UtcNow });

    /// <summary>Record a sync attempt (increments the counter + stamps the time) and mark uploading.</summary>
    public void RecordSyncAttempt(Guid id, DateTimeOffset attemptedAt)
        => UpdateManifest(id, m => m with
        {
            SyncState = RecordingBackupSyncState.Uploading,
            SyncAttemptCount = m.SyncAttemptCount + 1,
            LastSyncAttemptAt = attemptedAt,
            UpdatedAt = DateTimeOffset.UtcNow,
        });

    /// <summary>Drop the local WAV (e.g. after a successful upload) while keeping the manifest.</summary>
    public void DiscardAudioFile(Guid id)
    {
        lock (_lock)
        {
            var path = AudioPath(id);
            if (File.Exists(path))
            {
                try { File.Delete(path); }
                catch (IOException ex) { _logger.LogWarning(ex, "Failed to discard audio for {Id}", id); }
            }
            UpdateManifest(id, m => m with { HasAudioFile = false, UpdatedAt = DateTimeOffset.UtcNow });
        }
    }

    /// <summary>Ensure the per-recording directory exists and return its path (for the WAV writer).</summary>
    public string EnsureDirectoryForRecording(Guid id)
    {
        lock (_lock)
        {
            var dir = DirFor(id);
            Directory.CreateDirectory(dir);
            return dir;
        }
    }

    public void Remove(Guid id)
    {
        lock (_lock)
        {
            var dir = DirFor(id);
            if (Directory.Exists(dir))
            {
                try { Directory.Delete(dir, recursive: true); }
                catch (IOException ex) { _logger.LogWarning(ex, "Failed to remove backup {Id}", id); }
            }
        }
    }

    public void RemoveAll()
    {
        lock (_lock)
        {
            if (!Directory.Exists(_root)) return;
            foreach (var dir in Directory.EnumerateDirectories(_root))
            {
                try { Directory.Delete(dir, recursive: true); }
                catch (IOException) { /* swallow per-dir */ }
            }
        }
    }

    private void UpdateManifest(Guid id, Func<RecordingBackupManifest, RecordingBackupManifest> mutate)
    {
        lock (_lock)
        {
            var path = ManifestPath(id);
            if (!File.Exists(path)) return;
            try
            {
                var current = JsonSerializer.Deserialize<RecordingBackupManifest>(File.ReadAllBytes(path), WaiJson.Options);
                if (current is null) return;
                AtomicWrite(path, JsonSerializer.SerializeToUtf8Bytes(mutate(current), WaiJson.Options));
            }
            catch (JsonException ex) { _logger.LogWarning(ex, "Skipping manifest mutation — malformed at {Path}", path); }
            catch (IOException ex) { _logger.LogWarning(ex, "Failed to persist manifest mutation at {Path}", path); }
        }
    }

    private static void AtomicWrite(string path, byte[] content)
    {
        var tmp = path + ".tmp";
        File.WriteAllBytes(tmp, content);
        if (File.Exists(path))
        {
            File.Replace(tmp, path, destinationBackupFileName: null);
        }
        else
        {
            File.Move(tmp, path);
        }
    }
}
