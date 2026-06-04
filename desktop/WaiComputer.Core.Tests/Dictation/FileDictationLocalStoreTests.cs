using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Dictation;
using Xunit;

namespace WaiComputer.Core.Tests.Dictation;

public class FileDictationLocalStoreTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "wc-dict-" + Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); } catch { }
    }

    [Fact]
    public async Task RoundTripsValue()
    {
        var store = new FileDictationLocalStore(_dir);
        await store.WriteAsync("dictation_history", new List<string> { "a", "b" }, CancellationToken.None);
        var read = await store.ReadAsync<List<string>>("dictation_history", CancellationToken.None);
        read.Should().Equal("a", "b");
    }

    [Fact]
    public async Task MissingKeyReturnsDefault()
    {
        var store = new FileDictationLocalStore(_dir);
        (await store.ReadAsync<List<string>>("nope", CancellationToken.None)).Should().BeNull();
    }

    [Fact]
    public async Task OverwritesExisting()
    {
        var store = new FileDictationLocalStore(_dir);
        await store.WriteAsync("k", 1, CancellationToken.None);
        await store.WriteAsync("k", 2, CancellationToken.None);
        (await store.ReadAsync<int>("k", CancellationToken.None)).Should().Be(2);
    }
}
