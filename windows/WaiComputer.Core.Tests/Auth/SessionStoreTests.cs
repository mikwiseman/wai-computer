using FluentAssertions;
using WaiComputer.Core.Auth;
using Xunit;

namespace WaiComputer.Core.Tests.Auth;

public class SessionStoreTests : IDisposable
{
    private readonly string _dir;
    private readonly string _file;

    public SessionStoreTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "wc-session-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_dir);
        _file = Path.Combine(_dir, "session.json");
    }

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); } catch { /* ignore */ }
    }

    private SessionStore NewStore() => new(_file, new InMemoryProtector());

    [Fact]
    public void RoundTrip()
    {
        var store = NewStore();
        store.Save("at", "rt");

        var loaded = store.Load();
        loaded.Should().NotBeNull();
        loaded!.AccessToken.Should().Be("at");
        loaded.RefreshToken.Should().Be("rt");
        loaded.SavedAt.Should().BeCloseTo(DateTimeOffset.UtcNow, TimeSpan.FromSeconds(5));
    }

    [Fact]
    public void LoadReturnsNullWhenFileMissing()
    {
        NewStore().Load().Should().BeNull();
    }

    [Fact]
    public void LoadReturnsNullWhenCiphertextCorrupt()
    {
        var store = NewStore();
        store.Save("at", "rt");
        File.WriteAllBytes(_file, new byte[] { 0xDE, 0xAD, 0xBE, 0xEF });
        store.Load().Should().BeNull();
    }

    [Fact]
    public void LoadReturnsNullWhenJsonMalformed()
    {
        var store = new SessionStore(_file, new GarbageProtector());
        File.WriteAllBytes(_file, new byte[] { 1, 2, 3 });
        store.Load().Should().BeNull();
    }

    [Fact]
    public void SaveOverwrites()
    {
        var store = NewStore();
        store.Save("at1", "rt1");
        store.Save("at2", "rt2");
        store.Load()!.AccessToken.Should().Be("at2");
    }

    [Fact]
    public void ClearRemovesFile()
    {
        var store = NewStore();
        store.Save("at", "rt");
        store.Clear();
        File.Exists(_file).Should().BeFalse();
    }

    [Fact]
    public void SaveEmitsAclAppliedEvent()
    {
        var paths = new List<string>();
        SessionStore.AclApplied += paths.Add;
        try
        {
            NewStore().Save("at", "rt");
        }
        finally
        {
            SessionStore.AclApplied -= paths.Add;
        }
        paths.Should().Contain(_file);
    }

    [Fact]
    public void EmptyAccessTokenIsRejected()
    {
        var act = () => NewStore().Save(string.Empty, "rt");
        act.Should().Throw<ArgumentException>();
    }

    private sealed class InMemoryProtector : ISessionProtector
    {
        public byte[] Protect(byte[] plaintext) => (byte[])plaintext.Clone();
        public byte[] Unprotect(byte[] ciphertext) => (byte[])ciphertext.Clone();
    }

    private sealed class GarbageProtector : ISessionProtector
    {
        public byte[] Protect(byte[] plaintext) => new byte[] { 0xFF };
        public byte[] Unprotect(byte[] ciphertext) => new byte[] { (byte)'?' }; // not valid UTF-8 JSON
    }
}
