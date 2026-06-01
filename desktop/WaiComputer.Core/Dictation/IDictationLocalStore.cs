using System.Text.Json;
using WaiComputer.Core.Api;

namespace WaiComputer.Core.Dictation;

/// <summary>
/// JSON key-value persistence for the dictation history + dictionary (and their
/// tombstones) so they survive logout/login and sync across machines. Platforms
/// point it at the app-data dir; tests use an in-memory fake.
/// </summary>
public interface IDictationLocalStore
{
    Task<T?> ReadAsync<T>(string key, CancellationToken ct);
    Task WriteAsync<T>(string key, T value, CancellationToken ct);
}

/// <summary>
/// Portable <see cref="IDictationLocalStore"/> backed by one JSON file per key
/// under a directory, written atomically. Uses <see cref="WaiJson.Options"/> so
/// the on-disk shape matches the wire shape.
/// </summary>
public sealed class FileDictationLocalStore : IDictationLocalStore
{
    private readonly string _directory;

    public FileDictationLocalStore(string directory)
    {
        _directory = directory ?? throw new ArgumentNullException(nameof(directory));
        Directory.CreateDirectory(_directory);
    }

    private string PathFor(string key) => Path.Combine(_directory, key + ".json");

    public async Task<T?> ReadAsync<T>(string key, CancellationToken ct)
    {
        var path = PathFor(key);
        if (!File.Exists(path))
        {
            return default;
        }
        await using var stream = File.OpenRead(path);
        return await JsonSerializer.DeserializeAsync<T>(stream, WaiJson.Options, ct).ConfigureAwait(false);
    }

    public async Task WriteAsync<T>(string key, T value, CancellationToken ct)
    {
        var path = PathFor(key);
        var tmp = path + ".tmp";
        await using (var stream = File.Create(tmp))
        {
            await JsonSerializer.SerializeAsync(stream, value, WaiJson.Options, ct).ConfigureAwait(false);
        }
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
