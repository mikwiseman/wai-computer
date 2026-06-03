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

    private static ActionItem Item(string id, ActionItemStatus status) =>
        new(id, "rec1", "Send the report", Owner: null, DueDate: null, Priority: ActionItemPriority.Medium, Status: status, Source: "transcript", CreatedAt: DateTimeOffset.UtcNow);

    private void StubList(params ActionItem[] items) => _server
        .Given(Request.Create().UsingGet().WithPath("/api/action-items"))
        .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(items)).WithHeader("Content-Type", "application/json"));

    [Fact]
    public async Task LoadPopulatesItems()
    {
        StubList(Item("a1", ActionItemStatus.Pending), Item("a2", ActionItemStatus.Completed));

        await _vm.LoadAsync();

        _vm.Items.Should().HaveCount(2);
        _vm.ErrorMessage.Should().BeNull();
        _vm.IsLoading.Should().BeFalse();
    }

    [Fact]
    public async Task LoadFailureSurfacesErrorAndLeavesItemsEmpty()
    {
        _server.Given(Request.Create().UsingGet().WithPath("/api/action-items"))
            .RespondWith(Response.Create().WithStatusCode(500));

        await _vm.LoadAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.Items.Should().BeEmpty();
    }

    [Fact]
    public async Task FilterAppliesStatusAndPriorityQueryParams()
    {
        StubList();
        _vm.FilterStatus = ActionItemStatus.Completed;
        _vm.FilterPriority = ActionItemPriority.High;

        await _vm.LoadAsync();

        var entry = _server.LogEntries.Single(e => e.RequestMessage.Path == "/api/action-items");
        var values = entry.RequestMessage.Query!.SelectMany(kv => kv.Value).ToList();
        values.Should().Contain("completed");
        values.Should().Contain("high");
    }

    [Fact]
    public async Task ToggleMarksPendingItemCompletedAndUpdatesInPlace()
    {
        StubList(Item("a1", ActionItemStatus.Pending));
        await _vm.LoadAsync();

        _server.Given(Request.Create().UsingPatch().WithPath("/api/action-items/a1"))
            .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(Item("a1", ActionItemStatus.Completed))).WithHeader("Content-Type", "application/json"));

        await _vm.ToggleStatusAsync(_vm.Items[0]);

        _vm.Items[0].Status.Should().Be(ActionItemStatus.Completed);
        var patch = _server.LogEntries.Single(e => e.RequestMessage.Method == "PATCH");
        patch.RequestMessage.Body.Should().Contain("completed");
    }

    [Fact]
    public async Task ToggleReopensCompletedItemToPending()
    {
        StubList(Item("a1", ActionItemStatus.Completed));
        await _vm.LoadAsync();

        _server.Given(Request.Create().UsingPatch().WithPath("/api/action-items/a1"))
            .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(Item("a1", ActionItemStatus.Pending))).WithHeader("Content-Type", "application/json"));

        await _vm.ToggleStatusAsync(_vm.Items[0]);

        _vm.Items[0].Status.Should().Be(ActionItemStatus.Pending);
        var patch = _server.LogEntries.Single(e => e.RequestMessage.Method == "PATCH");
        patch.RequestMessage.Body.Should().Contain("pending");
    }

    [Fact]
    public async Task DeleteRemovesItem()
    {
        StubList(Item("a1", ActionItemStatus.Pending), Item("a2", ActionItemStatus.Pending));
        await _vm.LoadAsync();

        _server.Given(Request.Create().UsingDelete().WithPath("/api/action-items/a1"))
            .RespondWith(Response.Create().WithStatusCode(204));

        await _vm.DeleteAsync(_vm.Items.First(i => i.Id == "a1"));

        _vm.Items.Should().ContainSingle().Which.Id.Should().Be("a2");
    }

    [Fact]
    public async Task UpdateFailureSurfacesErrorAndLeavesItemUnchanged()
    {
        StubList(Item("a1", ActionItemStatus.Pending));
        await _vm.LoadAsync();

        _server.Given(Request.Create().UsingPatch().WithPath("/api/action-items/a1"))
            .RespondWith(Response.Create().WithStatusCode(500));

        await _vm.ToggleStatusAsync(_vm.Items[0]);

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.Items[0].Status.Should().Be(ActionItemStatus.Pending); // unchanged
    }
}
