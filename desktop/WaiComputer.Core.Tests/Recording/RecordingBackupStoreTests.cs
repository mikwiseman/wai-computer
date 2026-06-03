using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Recordings;
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

    [Fact]
    public void FreshManifestDefaultsToLocalReady()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        store.GetManifest(id)!.SyncState.Should().Be(RecordingBackupSyncState.LocalReady);
    }

    [Fact]
    public void MarkServerProcessingSetsStateAndJobId()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        store.MarkServerProcessing(id, "job-7");
        var m = store.GetManifest(id)!;
        m.SyncState.Should().Be(RecordingBackupSyncState.ServerProcessing);
        m.ServerJobId.Should().Be("job-7");
    }

    [Fact]
    public void RecordSyncAttemptIncrementsAndStamps()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        var at = new DateTimeOffset(2026, 6, 1, 9, 0, 0, TimeSpan.Zero);
        store.RecordSyncAttempt(id, at);
        store.RecordSyncAttempt(id, at);
        var m = store.GetManifest(id)!;
        m.SyncAttemptCount.Should().Be(2);
        m.LastSyncAttemptAt.Should().Be(at);
        m.SyncState.Should().Be(RecordingBackupSyncState.Uploading);
    }

    [Fact]
    public void MarkRetryableFailureSetsCodeAndState()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        store.MarkRetryableFailure(id, "network");
        var m = store.GetManifest(id)!;
        m.SyncState.Should().Be(RecordingBackupSyncState.RetryableFailure);
        m.LastFailureCode.Should().Be("network");
    }

    [Fact]
    public void ClearAuthenticationRequiredResetsToLocalReady()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        store.MarkAuthenticationRequired(id);
        store.GetManifest(id)!.SyncState.Should().Be(RecordingBackupSyncState.AuthRequired);
        store.ClearAuthenticationRequired(id);
        var m = store.GetManifest(id)!;
        m.RequiresAuthentication.Should().BeFalse();
        m.SyncState.Should().Be(RecordingBackupSyncState.LocalReady);
    }

    [Fact]
    public void DiscardAudioFileRemovesWavAndClearsFlag()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id) with { HasAudioFile = true }, SampleSegments(), new byte[] { 1, 2, 3, 4 });
        File.Exists(store.AudioPath(id)).Should().BeTrue();
        store.DiscardAudioFile(id);
        File.Exists(store.AudioPath(id)).Should().BeFalse();
        store.GetManifest(id)!.HasAudioFile.Should().BeFalse();
    }

    [Fact]
    public void EnsureDirectoryForRecordingCreatesDirectory()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        var dir = store.EnsureDirectoryForRecording(id);
        Directory.Exists(dir).Should().BeTrue();
    }

    [Fact]
    public void MarkPermanentFailureAlsoSetsSyncState()
    {
        var store = NewStore();
        var id = Guid.NewGuid();
        store.Save(SampleManifest(id), SampleSegments());
        store.MarkPermanentFailure(id);
        store.GetManifest(id)!.SyncState.Should().Be(RecordingBackupSyncState.PermanentFailure);
    }
}
