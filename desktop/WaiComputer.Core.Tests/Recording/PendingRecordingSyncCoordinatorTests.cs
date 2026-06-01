using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Recordings;
using WaiComputer.Core.Time;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;

namespace WaiComputer.Core.Tests.Recording;

public class PendingRecordingSyncCoordinatorTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private string _dir = null!;
    private RecordingBackupStore _store = null!;
    private FakeClock _clock = null!;
    private PendingRecordingSyncCoordinator _coord = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _dir = Path.Combine(Path.GetTempPath(), "wc-sync-" + Guid.NewGuid().ToString("N"));
        _store = new RecordingBackupStore(_dir);
        _clock = new FakeClock();
        _coord = new PendingRecordingSyncCoordinator(_client, _store, _clock);
        return Task.CompletedTask;
    }

    public Task DisposeAsync()
    {
        _client.Dispose();
        _server.Stop();
        _server.Dispose();
        try { Directory.Delete(_dir, recursive: true); } catch { }
        return Task.CompletedTask;
    }

    private static string Json<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value, WaiJson.Options);

    private RecordingBackupManifest Manifest(Guid id) => new(
        id, "Standup", RecordingType.Meeting, _clock.UtcNow, 60, 1, "hello", null, _clock.UtcNow, false, false, false);

    private RecordingDetail Detail(Guid id, RecordingStatus status, string? failureCode = null) => new(
        id.ToString(), "Standup", RecordingType.Meeting, "en", null, status, null, 60.0, false,
        _clock.UtcNow, _clock.UtcNow, failureCode, null,
        Array.Empty<Segment>(), null, Array.Empty<ActionItem>(), Array.Empty<Highlight>(), Array.Empty<SpeakerStat>());

    private static IReadOnlyList<LiveTranscriptSegment> Segments() => new[]
    {
        new LiveTranscriptSegment("hello world", null, true, 0, 1000, 0.9),
    };

    private void StubTranscript(Guid id, int statusCode, RecordingDetail? detail = null)
    {
        var resp = Response.Create().WithStatusCode(statusCode);
        if (detail is not null)
        {
            resp = resp.WithBody(Json(detail)).WithHeader("Content-Type", "application/json");
        }
        _server.Given(Request.Create().UsingPost().WithPath($"/api/recordings/{id}/transcript")).RespondWith(resp);
    }

    [Theory]
    [InlineData(1, 5)]
    [InlineData(2, 10)]
    [InlineData(3, 20)]
    [InlineData(4, 40)]
    [InlineData(5, 80)]
    [InlineData(6, 160)]
    [InlineData(7, 300)]
    [InlineData(10, 300)]
    public void BackoffScheduleMatchesMac(int attempt, int expected)
        => PendingRecordingSyncCoordinator.BackoffSeconds(attempt).Should().Be(expected);

    [Fact]
    public async Task SyncsTranscriptAndRemovesOnReady()
    {
        var id = Guid.NewGuid();
        _store.Save(Manifest(id), Segments());
        StubTranscript(id, 200, Detail(id, RecordingStatus.Ready));
        Guid? synced = null;
        _coord.RecordingSynced += rid => synced = rid;

        var remaining = await _coord.SyncPassAsync(CancellationToken.None);

        remaining.Should().Be(0);
        _store.GetManifest(id).Should().BeNull(); // removed on ready
        synced.Should().Be(id);
    }

    [Fact]
    public async Task SkipsTerminalStatesWithoutApiCalls()
    {
        var perm = Guid.NewGuid();
        var auth = Guid.NewGuid();
        _store.Save(Manifest(perm), Segments());
        _store.Save(Manifest(auth), Segments());
        _store.MarkPermanentFailure(perm);
        _store.MarkAuthenticationRequired(auth);

        var remaining = await _coord.SyncPassAsync(CancellationToken.None);

        remaining.Should().Be(0);              // terminal states are not "remaining to sync"
        _server.LogEntries.Should().BeEmpty();  // no upload attempts made
        _store.GetManifest(perm).Should().NotBeNull();
        _store.GetManifest(auth).Should().NotBeNull();
    }

    [Fact]
    public async Task MarksAuthRequiredOn401()
    {
        var id = Guid.NewGuid();
        _store.Save(Manifest(id), Segments());
        StubTranscript(id, 401);

        var remaining = await _coord.SyncPassAsync(CancellationToken.None);

        remaining.Should().Be(1);
        _store.GetManifest(id)!.SyncState.Should().Be(RecordingBackupSyncState.AuthRequired);
    }

    [Fact]
    public async Task MarksPermanentFailureOn413()
    {
        var id = Guid.NewGuid();
        _store.Save(Manifest(id), Segments());
        StubTranscript(id, 413);

        var remaining = await _coord.SyncPassAsync(CancellationToken.None);

        remaining.Should().Be(1);
        _store.GetManifest(id)!.SyncState.Should().Be(RecordingBackupSyncState.PermanentFailure);
    }

    [Fact]
    public async Task MarksServerProcessingWhenStillProcessing()
    {
        var id = Guid.NewGuid();
        _store.Save(Manifest(id), Segments());
        StubTranscript(id, 200, Detail(id, RecordingStatus.Processing));

        var remaining = await _coord.SyncPassAsync(CancellationToken.None);

        remaining.Should().Be(1);
        var m = _store.GetManifest(id)!;
        m.SyncState.Should().Be(RecordingBackupSyncState.ServerProcessing);
        m.SyncAttemptCount.Should().Be(1);
    }

    [Fact]
    public async Task SkipsInProgressLocalRecording()
    {
        var id = Guid.NewGuid();
        _store.Save(Manifest(id) with { SyncState = RecordingBackupSyncState.LocalRecording }, Segments());

        var remaining = await _coord.SyncPassAsync(CancellationToken.None);

        remaining.Should().Be(0);              // in-progress recordings are not synced
        _server.LogEntries.Should().BeEmpty();  // no upload attempt
        _store.GetManifest(id).Should().NotBeNull();
    }

    [Fact]
    public async Task RecordsConcreteFailureMessageOn404()
    {
        var id = Guid.NewGuid();
        _store.Save(Manifest(id), Segments());
        StubTranscript(id, 404);

        await _coord.SyncPassAsync(CancellationToken.None);

        var m = _store.GetManifest(id)!;
        m.SyncState.Should().Be(RecordingBackupSyncState.PermanentFailure);
        m.LastErrorMessage.Should().Contain("deleted"); // concrete user-facing message, not silent
    }

    private sealed class FakeClock : ISystemClock
    {
        public DateTimeOffset UtcNow { get; set; } = new(2026, 6, 1, 12, 0, 0, TimeSpan.Zero);
        public List<TimeSpan> Delays { get; } = new();
        public Task Delay(TimeSpan duration, CancellationToken ct)
        {
            Delays.Add(duration);
            return Task.CompletedTask;
        }
    }
}
