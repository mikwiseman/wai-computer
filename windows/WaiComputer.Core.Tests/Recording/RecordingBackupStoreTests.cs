using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Recording;
using Xunit;

namespace WaiComputer.Core.Tests.Recording;

public class RecordingBackupStoreTests : IDisposable
{
    private readonly string _dir;

    public RecordingBackupStoreTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "wc-backups-" + Guid.NewGuid().ToString("N"));
    }

    public void Dispose() { try { Directory.Delete(_dir, recursive: true); } catch { } }

    private RecordingBackupStore NewStore() => new(_dir);

    private RecordingBackupManifest SampleManifest(Guid id) => new(
        id, "Standup", RecordingType.Meeting, DateTimeOffset.UtcNow, 60, 3,
        "hello", LastErrorMessage: null, UpdatedAt: DateTimeOffset.UtcNow,
        HasAudioFile: false, IsPermanentFailure: false, RequiresAuthentication: false);

    private static IReadOnlyList<LiveTranscriptSegment> SampleSegments() => new[]
    {
        new LiveTranscriptSegment("hello", "Mik", true, 0, 1000, 0.9),
    };

    [Fact]
    public void RoundTrip()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());

        store.GetManifest(id).Should().NotBeNull();
        store.GetSegments(id).Should().NotBeNull().And.ContainSingle();
    }

    [Fact]
    public void SaveWithAudioCreatesWavFile()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        var audio = new byte[] { 1, 2, 3, 4 };
        store.Save(SampleManifest(id) with { HasAudioFile = true }, SampleSegments(), audio);

        File.Exists(store.AudioPath(id)).Should().BeTrue();
        File.ReadAllBytes(store.AudioPath(id)).Should().Equal(audio);
    }

    [Fact]
    public void RecordSaveFailureMutatesManifest()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        store.RecordSaveFailure(id, "boom");
        store.GetManifest(id)!.LastErrorMessage.Should().Be("boom");
    }

    [Fact]
    public void MarkPermanentFailurePersistsFlag()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        store.MarkPermanentFailure(id);

        store.GetManifest(id)!.IsPermanentFailure.Should().BeTrue();
    }

    [Fact]
    public void ListBackupsSkipsMalformed()
    {
        var store = NewStore();
        store.Save(SampleManifest(Guid.NewGuid()), SampleSegments());

        var rogueDir = Path.Combine(_dir, "rogue");
        Directory.CreateDirectory(rogueDir);
        File.WriteAllText(Path.Combine(rogueDir, "manifest.json"), "{not valid json");

        store.ListBackups().Should().ContainSingle();
    }

    [Fact]
    public void RemoveDeletesDirectory()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        store.Remove(id);
        File.Exists(Path.Combine(_dir, id.ToString("N"), "manifest.json")).Should().BeFalse();
    }

    [Fact]
    public void RemoveAllClearsEverything()
    {
        var store = NewStore();
        for (int i = 0; i < 5; i++)
            store.Save(SampleManifest(Guid.NewGuid()), SampleSegments());
        store.RemoveAll();
        store.ListBackups().Should().BeEmpty();
    }
}
