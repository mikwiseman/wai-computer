using System;
using System.Linq;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.ViewModels;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;
using RecordingModel = WaiComputer.Core.Api.Models.Recording;

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

    private static RecordingModel Rec(string id) =>
        new(id, "Standup", RecordingType.Meeting, "en", FolderId: null, RecordingStatus.Ready, AudioUrl: null,
            DurationSeconds: 60, IsStarred: false, CreatedAt: DateTimeOffset.UtcNow, UpdatedAt: DateTimeOffset.UtcNow,
            FailureCode: null, FailureMessage: null);

    private void StubRecordings(params RecordingModel[] recs) => _server
        .Given(Request.Create().UsingGet().WithPath("/api/recordings"))
        .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(recs)).WithHeader("Content-Type", "application/json"));

    private void StubFolders(params Folder[] folders) => _server
        .Given(Request.Create().UsingGet().WithPath("/api/folders"))
        .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(folders)).WithHeader("Content-Type", "application/json"));

    private void StubBulk(int processed, int failed) => _server
        .Given(Request.Create().UsingPost().WithPath("/api/recordings/bulk"))
        .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(new BulkRecordingOperationResponse(processed, failed))).WithHeader("Content-Type", "application/json"));

    [Fact]
    public async Task LoadPopulatesRecordingsAndFolders()
    {
        StubRecordings(Rec("rec1"), Rec("rec2"));
        StubFolders(new Folder("f1", "Work", null, DateTimeOffset.UtcNow));

        await _vm.LoadAsync();

        _vm.Recordings.Should().HaveCount(2);
        _vm.Folders.Should().ContainSingle();
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task LoadFailureSurfacesErrorAndLeavesListsEmpty()
    {
        _server.Given(Request.Create().UsingGet().WithPath("/api/recordings"))
            .RespondWith(Response.Create().WithStatusCode(500));

        await _vm.LoadAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.Recordings.Should().BeEmpty();
    }

    [Fact]
    public async Task FiltersApplyTheRightQueryParams()
    {
        StubRecordings();
        StubFolders();
        _vm.ShowStarredOnly = true;
        _vm.FilterType = RecordingType.Note;
        _vm.FilterFolderId = "f1";
        _vm.ShowTrashed = true;

        await _vm.LoadAsync();

        var entry = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/recordings");
        var query = entry.RequestMessage.Query!;
        query.Should().ContainKey("starred");
        query.Should().ContainKey("trashed");
        query["type"].Should().Contain("note");
        query["folder_id"].Should().Contain("f1");
    }

    [Fact]
    public async Task TrashSelectedSendsBulkDeleteAndClearsSelection()
    {
        StubRecordings(Rec("rec1"), Rec("rec2"));
        StubFolders();
        StubBulk(processed: 2, failed: 0);

        await _vm.LoadAsync();
        _vm.SelectedIds.Add("rec1");
        _vm.SelectedIds.Add("rec2");

        await _vm.TrashSelectedCommand.ExecuteAsync(null);

        var post = _server.LogEntries.Single(e => e.RequestMessage.Method == "POST" && e.RequestMessage.Path == "/api/recordings/bulk");
        post.RequestMessage.Body.Should().Contain("delete");
        post.RequestMessage.Body.Should().Contain("rec1");
        _vm.SelectedIds.Should().BeEmpty();
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task BulkPartialFailureSurfacesMessageAfterReload()
    {
        StubRecordings(Rec("rec1"));
        StubFolders();
        StubBulk(processed: 1, failed: 1);

        await _vm.LoadAsync();
        _vm.SelectedIds.Add("rec1");
        _vm.SelectedIds.Add("rec2");

        await _vm.BulkAsync(BulkRecordingAction.Delete, null);

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.ErrorMessage.Should().Contain("1");
        _vm.SelectedIds.Should().BeEmpty();
    }

    [Fact]
    public async Task BulkFailurePreservesSelectionAndDoesNotReload()
    {
        StubRecordings(Rec("rec1"));
        StubFolders();
        _server.Given(Request.Create().UsingPost().WithPath("/api/recordings/bulk"))
            .RespondWith(Response.Create().WithStatusCode(500));

        await _vm.LoadAsync();
        _vm.SelectedIds.Add("rec1");

        await _vm.BulkAsync(BulkRecordingAction.Delete, null);

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.SelectedIds.Should().ContainSingle(); // preserved for retry
        _server.LogEntries.Count(e => e.RequestMessage.Path == "/api/recordings").Should().Be(1); // no reload after failure
    }

    [Fact]
    public void BulkCommandsAreGatedBySelection()
    {
        _vm.TrashSelectedCommand.CanExecute(null).Should().BeFalse();
        _vm.RestoreSelectedCommand.CanExecute(null).Should().BeFalse();

        _vm.SelectedIds.Add("rec1");

        _vm.TrashSelectedCommand.CanExecute(null).Should().BeTrue();
        _vm.RestoreSelectedCommand.CanExecute(null).Should().BeTrue();
    }
}
