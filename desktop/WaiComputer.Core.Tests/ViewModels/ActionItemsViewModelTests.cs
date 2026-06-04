using System;
using System.Collections.Generic;
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

namespace WaiComputer.Core.Tests.ViewModels;

public class ActionItemsViewModelTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private ActionItemsViewModel _vm = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _vm = new ActionItemsViewModel(_client);
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

    private void StubGet(string path, int status, object? body = null) => _server
        .Given(Request.Create().UsingGet().WithPath(path))
        .RespondWith(Body(Response.Create().WithStatusCode(status), status, body));

    private void StubPatch(string path, int status, object? body = null) => _server
        .Given(Request.Create().UsingPatch().WithPath(path))
        .RespondWith(Body(Response.Create().WithStatusCode(status), status, body));

    private void StubDelete(string path, int status) => _server
        .Given(Request.Create().UsingDelete().WithPath(path))
        .RespondWith(Response.Create().WithStatusCode(status));

    private static IResponseBuilder Body(IResponseBuilder resp, int status, object? body)
        => body is null ? resp : resp.WithBody(Json(body)).WithHeader("Content-Type", "application/json");

    private static ActionItem Item(
        string id,
        string task = "Follow up",
        ActionItemStatus status = ActionItemStatus.Pending,
        ActionItemPriority? priority = ActionItemPriority.Medium)
        => new(
            Id: id,
            RecordingId: "rec1",
            Task: task,
            Owner: null,
            DueDate: null,
            Priority: priority,
            Status: status,
            Source: "ai",
            CreatedAt: DateTimeOffset.UtcNow);

    // ----- load -------------------------------------------------------------

    [Fact]
    public async Task LoadPopulatesItemsFromServer()
    {
        StubGet("/api/action-items", 200, new[]
        {
            Item("a1", "Email Bob"),
            Item("a2", "Book room", status: ActionItemStatus.InProgress, priority: ActionItemPriority.High),
        });

        await _vm.LoadAsync();

        _vm.Items.Should().HaveCount(2);
        _vm.Items[0].Id.Should().Be("a1");
        _vm.Items[1].Status.Should().Be(ActionItemStatus.InProgress);
        _vm.Items[1].Priority.Should().Be(ActionItemPriority.High);
        _vm.HasItems.Should().BeTrue();
        _vm.ErrorMessage.Should().BeNull();
        _vm.IsLoading.Should().BeFalse();
    }

    [Fact]
    public async Task LoadFailureSurfacesErrorAndLeavesItemsIntact()
    {
        // First load succeeds.
        StubGet("/api/action-items", 200, new[] { Item("a1") });
        await _vm.LoadAsync();
        _vm.Items.Should().HaveCount(1);

        // Replace the stub with a server error and reload — no silent fallback.
        _server.Reset();
        StubGet("/api/action-items", 500);

        await _vm.LoadAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.Items.Should().HaveCount(1); // prior list untouched, not fabricated/cleared
        _vm.IsLoading.Should().BeFalse();
    }

    [Fact]
    public async Task LoadWithEmptyResultClearsItemsWithoutError()
    {
        StubGet("/api/action-items", 200, Array.Empty<ActionItem>());

        await _vm.LoadAsync();

        _vm.Items.Should().BeEmpty();
        _vm.HasItems.Should().BeFalse();
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task FilterByStatusSendsStatusQueryAndReloads()
    {
        StubGet("/api/action-items", 200, new[] { Item("a1", status: ActionItemStatus.InProgress) });

        await _vm.FilterByStatusAsync(ActionItemStatus.InProgress);

        _vm.StatusFilter.Should().Be(ActionItemStatus.InProgress);
        var entry = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/action-items");
        // Enum maps to its JSON wire value, not "inprogress".
        entry.RequestMessage.Query.Should().Contain(q => q.Key == "status" && q.Value.Contains("in_progress"));
    }

    [Fact]
    public async Task FilterByPrioritySendsPriorityQuery()
    {
        StubGet("/api/action-items", 200, Array.Empty<ActionItem>());

        await _vm.FilterByPriorityAsync(ActionItemPriority.High);

        _vm.PriorityFilter.Should().Be(ActionItemPriority.High);
        var entry = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/action-items");
        entry.RequestMessage.Query.Should().Contain(q => q.Key == "priority" && q.Value.Contains("high"));
    }

    // ----- toggle status ----------------------------------------------------

    [Fact]
    public async Task ToggleStatusAdvancesPendingToCompletedAndResyncs()
    {
        StubGet("/api/action-items", 200, new[] { Item("a1", "Email Bob", ActionItemStatus.Pending) });
        await _vm.LoadAsync();

        // Server returns the item now marked completed.
        StubPatch("/api/action-items/a1", 200, Item("a1", "Email Bob", ActionItemStatus.Completed));

        await _vm.ToggleStatusAsync(_vm.Items[0]);

        var patch = _server.LogEntries.Single(e =>
            e.RequestMessage.Method == "PATCH" && e.RequestMessage.Path == "/api/action-items/a1");
        patch.RequestMessage.Body.Should().Contain("completed"); // requested next status went over the wire
        _vm.Items.Should().ContainSingle();
        _vm.Items[0].Status.Should().Be(ActionItemStatus.Completed); // re-synced from server response
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task ToggleStatusFlipsCompletedBackToPending()
    {
        StubGet("/api/action-items", 200, new[] { Item("a1", "Email Bob", ActionItemStatus.Completed) });
        await _vm.LoadAsync();

        _server.Reset();
        StubPatch("/api/action-items/a1", 200, Item("a1", "Email Bob", ActionItemStatus.Pending));

        await _vm.ToggleStatusAsync(_vm.Items[0]);

        _vm.Items[0].Status.Should().Be(ActionItemStatus.Pending);
        var patch = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/action-items/a1");
        patch.RequestMessage.Body.Should().Contain("pending"); // requested next status went over the wire
    }

    [Fact]
    public async Task ToggleStatusFailureSurfacesErrorAndKeepsOriginalStatus()
    {
        StubGet("/api/action-items", 200, new[] { Item("a1", "Email Bob", ActionItemStatus.Pending) });
        await _vm.LoadAsync();

        StubPatch("/api/action-items/a1", 500);

        await _vm.ToggleStatusAsync(_vm.Items[0]);

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.Items[0].Status.Should().Be(ActionItemStatus.Pending); // unchanged, no optimistic fabrication
        _vm.IsLoading.Should().BeFalse();
    }

    // ----- delete -----------------------------------------------------------

    [Fact]
    public async Task DeleteRemovesItemFromListOnSuccess()
    {
        StubGet("/api/action-items", 200, new[] { Item("a1"), Item("a2") });
        await _vm.LoadAsync();

        StubDelete("/api/action-items/a1", 204);

        await _vm.DeleteAsync(_vm.Items.Single(i => i.Id == "a1"));

        _vm.Items.Should().ContainSingle(i => i.Id == "a2");
        _server.LogEntries.Should().Contain(e =>
            e.RequestMessage.Method == "DELETE" && e.RequestMessage.Path == "/api/action-items/a1");
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task DeleteFailureSurfacesErrorAndKeepsItem()
    {
        StubGet("/api/action-items", 200, new[] { Item("a1") });
        await _vm.LoadAsync();

        StubDelete("/api/action-items/a1", 500);

        await _vm.DeleteAsync(_vm.Items[0]);

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.Items.Should().ContainSingle(i => i.Id == "a1"); // not removed on failure
    }
}
