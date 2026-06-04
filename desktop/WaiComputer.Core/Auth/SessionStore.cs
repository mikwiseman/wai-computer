using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;

namespace WaiComputer.Core.Auth;

/// <summary>
/// File-backed session storage. On disk:
/// <code>%APPDATA%\WaiComputer\session.json</code>
/// On Windows the file is DPAPI-encrypted (<c>CurrentUser</c> scope) so a
/// stolen copy of the file can't be decrypted without the user's logon
/// credentials. Identical role to the Swift <c>SessionStore</c>.
/// </summary>
public sealed class SessionStore
{
    private readonly string _filePath;
    private readonly ISessionProtector _protector;
    private readonly ILogger<SessionStore> _logger;
    private readonly object _lock = new();

    public SessionStore(string filePath, ISessionProtector protector, ILogger<SessionStore>? logger = null)
    {
        _filePath = filePath ?? throw new ArgumentNullException(nameof(filePath));
        _protector = protector ?? throw new ArgumentNullException(nameof(protector));
        _logger = logger ?? NullLogger<SessionStore>.Instance;
    }

    public string FilePath => _filePath;

    public Session? Load()
    {
        lock (_lock)
        {
            if (!File.Exists(_filePath)) return null;
            byte[] cipher;
            try { cipher = File.ReadAllBytes(_filePath); }
            catch (IOException ex) { _logger.LogWarning(ex, "Failed to read session file"); return null; }

            byte[] plain;
            try { plain = _protector.Unprotect(cipher); }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Session file decryption failed; treating as missing");
                return null;
            }

            try
            {
                var session = JsonSerializer.Deserialize<Session>(plain, WaiJson.Options);
                if (session is null || string.IsNullOrEmpty(session.AccessToken))
                {
                    _logger.LogWarning("Session file decoded to empty payload");
                    return null;
                }
                return session;
            }
            catch (JsonException ex)
            {
                _logger.LogWarning(ex, "Session file malformed; treating as missing");
                return null;
            }
        }
    }

    public void Save(string accessToken, string? refreshToken)
    {
        if (string.IsNullOrEmpty(accessToken))
        {
            throw new ArgumentException("Access token must not be empty.", nameof(accessToken));
        }

        var session = new Session(accessToken, refreshToken, DateTimeOffset.UtcNow);
        var json = JsonSerializer.SerializeToUtf8Bytes(session, WaiJson.Options);
        var cipher = _protector.Protect(json);

        lock (_lock)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_filePath)!);
            var tmp = _filePath + ".tmp";
            File.WriteAllBytes(tmp, cipher);
            ApplyRestrictiveAcl(tmp);
            if (File.Exists(_filePath))
            {
                File.Replace(tmp, _filePath, destinationBackupFileName: null);
            }
            else
            {
                File.Move(tmp, _filePath);
            }
            ApplyRestrictiveAcl(_filePath);
        }
    }

    public void Clear()
    {
        lock (_lock)
        {
            if (File.Exists(_filePath))
            {
                try { File.Delete(_filePath); }
                catch (IOException ex) { _logger.LogWarning(ex, "Session file delete failed"); }
            }
        }
    }

    /// <summary>
    /// Restrict the file to the current user. On non-Windows this is a no-op
    /// (Mac/Linux uses chmod 0600 elsewhere in the platform layer); on Windows
    /// the actual ACL trimming is applied by <see cref="WaiComputer"/>'s
    /// <c>WindowsAclHelper</c>. This shim lets Core/Auth ship on net9.0 (cross-platform)
    /// while keeping the security guarantee in production.
    /// </summary>
    public void ApplyRestrictiveAcl(string path)
    {
        AclApplied?.Invoke(path);
    }

    /// <summary>
    /// Hook for the Windows project to attach a real ACL helper to. The Core
    /// project stays portable and only emits the event; <c>WaiComputer</c>'s
    /// startup wiring subscribes once and applies the ACL via
    /// <c>FileSecurity</c>.
    /// </summary>
    public static event Action<string>? AclApplied;
}
