using System;
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

public class SettingsViewModelTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private SettingsViewModel _vm = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _vm = new SettingsViewModel(_client);
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

    private static UserSettings Settings(string defaultLanguage = "en", bool postFilter = false) =>
        new(defaultLanguage, "en", SummaryStyle.Medium,
            "deepgram", "nova-3", "deepgram", "nova-3", "deepgram", "nova-3",
            postFilter, null, null);

    private void StubGet(int status, UserSettings? body = null) => _server
        .Given(Request.Create().UsingGet().WithPath("/api/settings"))
        .RespondWith(body is null
            ? Response.Create().WithStatusCode(status)
            : Response.Create().WithStatusCode(status).WithBody(Json(body)).WithHeader("Content-Type", "application/json"));

    private void StubPatch(int status, UserSettings? body = null) => _server
        .Given(Request.Create().UsingPatch().WithPath("/api/settings"))
        .RespondWith(body is null
            ? Response.Create().WithStatusCode(status)
            : Response.Create().WithStatusCode(status).WithBody(Json(body)).WithHeader("Content-Type", "application/json"));

    [Fact]
    public async Task LoadPopulatesEditablePropsAndHasNoChanges()
    {
        StubGet(200, Settings(defaultLanguage: "ru", postFilter: true));

        await _vm.LoadAsync();

        _vm.DefaultLanguage.Should().Be("ru");
        _vm.DictationPostFilterEnabled.Should().BeTrue();
        _vm.HasChanges.Should().BeFalse();
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task LoadFailureSurfacesError()
    {
        StubGet(500);

        await _vm.LoadAsync();

        _vm.ErrorMessage.Should().NotBeNull();
    }

    [Fact]
    public async Task SaveSendsOnlyChangedFieldAndOmitsManagedSttFields()
    {
        StubGet(200, Settings(defaultLanguage: "en"));
        await _vm.LoadAsync();

        _vm.DefaultLanguage = "ru"; // the only edit
        StubPatch(200, Settings(defaultLanguage: "ru"));

        await _vm.SaveAsync();

        var patch = _server.LogEntries.Single(e => e.RequestMessage.Method == "PATCH");
        var body = patch.RequestMessage.Body!;
        body.Should().Contain("default_language");
        body.Should().Contain("ru");
        // The managed STT provider/model fields must NOT be sent — the backend 400s on them.
        body.Should().NotContain("file_stt");
        body.Should().NotContain("dictation_live_stt");
        body.Should().NotContain("recording_live_stt");
        // Unchanged non-managed fields are omitted too (sparse PATCH).
        body.Should().NotContain("summary_language");
    }

    [Fact]
    public async Task SaveRefreshesFromResponseAndClearsHasChanges()
    {
        StubGet(200, Settings(defaultLanguage: "en"));
        await _vm.LoadAsync();
        _vm.DefaultLanguage = "ru";
        StubPatch(200, Settings(defaultLanguage: "ru"));

        await _vm.SaveAsync();

        _vm.DefaultLanguage.Should().Be("ru");
        _vm.HasChanges.Should().BeFalse();
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task SaveFailureSurfacesErrorAndKeepsEdits()
    {
        StubGet(200, Settings(defaultLanguage: "en"));
        await _vm.LoadAsync();
        _vm.DefaultLanguage = "ru";
        StubPatch(500);

        await _vm.SaveAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.DefaultLanguage.Should().Be("ru"); // edit preserved for retry
        _vm.HasChanges.Should().BeTrue();
    }

    [Fact]
    public async Task HasChangesAndSaveCommandTrackEdits()
    {
        StubGet(200, Settings(defaultLanguage: "en"));
        await _vm.LoadAsync();

        _vm.HasChanges.Should().BeFalse();
        _vm.SaveCommand.CanExecute(null).Should().BeFalse();

        _vm.DefaultLanguage = "ru";

        _vm.HasChanges.Should().BeTrue();
        _vm.SaveCommand.CanExecute(null).Should().BeTrue();
    }
}
