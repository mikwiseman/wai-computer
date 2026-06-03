using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.ViewModels;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;

// `WaiComputer.Core.Recording` is a namespace visible by simple name from inside
// `WaiComputer.Core.Tests.*` and wins over the type in unqualified positions, so
// the `Recording` DTO is referenced fully-qualified below.
using RecordingDto = WaiComputer.Core.Api.Models.Recording;

namespace WaiComputer.Core.Tests.ViewModels;

public class LibraryViewModelTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private LibraryViewModel _vm = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _vm = new LibraryViewModel(_client);
        return Task.CompletedTask;
    }

    public Task DisposeAsync()
    {
        _client.Dispose();
        _server.Stop();
        _server.Dispose();
        return Task.CompletedTask;
    }

    private static string Json<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value, WaiJson.Options);

    private static IResponseBuilder Body(IResponseBuilder resp, int status, object? body)
        => body is null ? resp : resp.WithBody(Json(body)).WithHeader("Content-Type", "application/json");

    private void StubGet(string path, int status, object? body = null) => _server
        .Given(Request.Create().UsingGet().WithPath(path))
        .RespondWith(Body(Response.Create().WithStatusCode(status), status, body));

    private void StubPost(string path, int status, object? body = null) => _server
        .Given(Request.Create().UsingPost().WithPath(path))
        .RespondWith(Body(Response.Create().WithStatusCode(status), status, body));

    private static RecordingDto Rec(string id, bool starred = false) => new(
        Id: id,
        Title: "Recording " + id,
        Type: RecordingType.Meeting,
        Language: "en",
        FolderId: null,
        Status: RecordingStatus.Ready,
        AudioUrl: null,
        DurationSeconds: 12.5,
        IsStarred: starred,
        CreatedAt: DateTimeOffset.UtcNow,
        UpdatedAt: DateTimeOffset.UtcNow,
        FailureCode: null,
        FailureMessage: null);

    private static Folder Fol(string id, string name) => new(id, name, Color: null, CreatedAt: DateTimeOffset.UtcNow);

    private static BulkRecordingOperationResponse Bulk(int processed, int failed) => new(processed, failed);

    // ----- load -------------------------------------------------------------

    [Fact]
    public async Task LoadPopulatesRecordingsAndFolders()
    {
        StubGet("/api/folders", 200, new[] { Fol("f1", "Work"), Fol("f2", "Personal") });
        StubGet("/api/recordings", 200, new[] { Rec("r1"), Rec("r2"), Rec("r3") });

        await _vm.LoadAsync();

        _vm.Recordings.Should().HaveCount(3);
        _vm.Folders.Should().HaveCount(2);
        _vm.Recordings.Select(r => r.Id).Should().ContainInOrder("r1", "r2", "r3");
        _vm.IsLoading.Should().BeFalse();
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task LoadFailureSurfacesErrorAndLeavesListsEmpty()
    {
        StubGet("/api/folders", 200, Array.Empty<Folder>());
        StubGet("/api/recordings", 500); // server error, no body

        await _vm.LoadAsync();

        _vm.ErrorMessage.Should().NotBeNull(); // no silent swallow
        _vm.Recordings.Should().BeEmpty();      // nothing fabricated
        _vm.IsLoading.Should().BeFalse();
    }

    [Fact]
    public async Task LoadReplacesPreviousResultsRatherThanAppending()
    {
        StubGet("/api/folders", 200, Array.Empty<Folder>());
        StubGet("/api/recordings", 200, new[] { Rec("r1"), Rec("r2") });

        await _vm.LoadAsync();
        _vm.Recordings.Should().HaveCount(2);

        await _vm.RefreshCommand.ExecuteAsync(null);

        _vm.Recordings.Should().HaveCount(2); // replaced, not 4
    }

    // ----- filter state -----------------------------------------------------

    [Fact]
    public async Task StarredFilterAppliesStarredQueryParam()
    {
        StubGet("/api/folders", 200, Array.Empty<Folder>());
        StubGet("/api/recordings", 200, new[] { Rec("r1", starred: true) });

        await _vm.SetStarredOnlyAsync(true);

        _vm.ShowStarredOnly.Should().BeTrue();
        var entry = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/recordings");
        entry.RequestMessage.Query.Should().ContainKey("starred");
        entry.RequestMessage.Query!["starred"].Should().Contain("true");
    }

    [Fact]
    public async Task TrashFilterRequestsTrashedRecordings()
    {
        StubGet("/api/folders", 200, Array.Empty<Folder>());
        StubGet("/api/recordings", 200, new[] { Rec("r1") });

        await _vm.ShowTrashAsync();

        _vm.ShowTrashed.Should().BeTrue();
        var entry = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/recordings");
        entry.RequestMessage.Query!["trashed"].Should().Contain("true");
    }

    [Fact]
    public async Task FolderFilterAppliesFolderIdQueryParam()
    {
        StubGet("/api/folders", 200, new[] { Fol("f1", "Work") });
        StubGet("/api/recordings", 200, new[] { Rec("r1") });

        await _vm.SetFolderAsync("f1");

        _vm.FolderId.Should().Be("f1");
        var entry = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/recordings");
        entry.RequestMessage.Query!["folder_id"].Should().Contain("f1");
    }

    // ----- multi-select -----------------------------------------------------

    [Fact]
    public void ToggleSelectionAddsThenRemovesAndUpdatesDerivedState()
    {
        _vm.HasSelection.Should().BeFalse();

        _vm.ToggleSelection("r1");
        _vm.ToggleSelection("r2");
        _vm.HasSelection.Should().BeTrue();
        _vm.SelectionCount.Should().Be(2);
        _vm.IsSelected("r1").Should().BeTrue();
        _vm.BulkTrashCommand.CanExecute(null).Should().BeTrue();

        _vm.ToggleSelection("r1"); // toggle off
        _vm.IsSelected("r1").Should().BeFalse();
        _vm.SelectionCount.Should().Be(1);

        _vm.ClearSelection();
        _vm.HasSelection.Should().BeFalse();
        _vm.BulkTrashCommand.CanExecute(null).Should().BeFalse();
    }

    // ----- bulk operations --------------------------------------------------

    [Fact]
    public async Task BulkTrashHitsBulkEndpointWithDeleteActionAndReloads()
    {
        StubGet("/api/folders", 200, Array.Empty<Folder>());
        StubGet("/api/recordings", 200, new[] { Rec("r1") }); // reload after the op
        StubPost("/api/recordings/bulk", 200, Bulk(processed: 2, failed: 0));

        _vm.ToggleSelection("r1");
        _vm.ToggleSelection("r2");

        await _vm.BulkTrashCommand.ExecuteAsync(null);

        var bulk = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/recordings/bulk");
        var body = bulk.RequestMessage.Body!;
        body.Should().Contain("\"action\":\"delete\"");
        body.Should().Contain("r1").And.Contain("r2");

        _vm.SelectedIds.Should().BeEmpty();            // selection cleared after op
        _vm.ErrorMessage.Should().BeNull();
        _vm.Recordings.Should().ContainSingle();       // reloaded
        _server.LogEntries.Should().Contain(e => e.RequestMessage.Path == "/api/recordings");
    }

    [Fact]
    public async Task BulkMoveSendsMoveActionWithFolderIdAndReloads()
    {
        StubGet("/api/folders", 200, new[] { Fol("f9", "Archive") });
        StubGet("/api/recordings", 200, Array.Empty<RecordingDto>());
        StubPost("/api/recordings/bulk", 200, Bulk(processed: 1, failed: 0));

        _vm.ToggleSelection("r1");

        await _vm.BulkMoveAsync("f9");

        var bulk = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/recordings/bulk");
        var body = bulk.RequestMessage.Body!;
        body.Should().Contain("\"action\":\"move\"");
        body.Should().Contain("\"folder_id\":\"f9\"");
        _vm.SelectedIds.Should().BeEmpty();
    }

    [Fact]
    public async Task BulkPartialFailureSurfacesErrorMessage()
    {
        StubGet("/api/folders", 200, Array.Empty<Folder>());
        StubGet("/api/recordings", 200, Array.Empty<RecordingDto>());
        StubPost("/api/recordings/bulk", 200, Bulk(processed: 1, failed: 2));

        _vm.ToggleSelection("r1");
        _vm.ToggleSelection("r2");
        _vm.ToggleSelection("r3");

        await _vm.BulkTrashCommand.ExecuteAsync(null);

        _vm.ErrorMessage.Should().NotBeNull(); // partial failure is not silently dropped
        _vm.ErrorMessage.Should().Contain("2");
    }

    [Fact]
    public async Task BulkServerErrorSurfacesErrorAndDoesNotClearSelection()
    {
        StubPost("/api/recordings/bulk", 500); // call fails outright

        _vm.ToggleSelection("r1");

        await _vm.BulkTrashCommand.ExecuteAsync(null);

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.IsLoading.Should().BeFalse();
        _vm.SelectedIds.Should().ContainSingle(); // selection preserved so the user can retry
        _server.LogEntries.Should().NotContain(e => e.RequestMessage.Path == "/api/recordings"); // no reload after failure
    }
}
