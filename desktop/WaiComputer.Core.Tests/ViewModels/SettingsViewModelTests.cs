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

    private void StubGet(string path, int status, object? body = null) => _server
        .Given(Request.Create().UsingGet().WithPath(path))
        .RespondWith(Body(Response.Create().WithStatusCode(status), body));

    private void StubPatch(string path, int status, object? body = null) => _server
        .Given(Request.Create().UsingPatch().WithPath(path))
        .RespondWith(Body(Response.Create().WithStatusCode(status), body));

    private static IResponseBuilder Body(IResponseBuilder resp, object? body)
        => body is null ? resp : resp.WithBody(Json(body)).WithHeader("Content-Type", "application/json");

    private static UserSettings Settings(
        string defaultLanguage = "en",
        SummaryStyle summaryStyle = SummaryStyle.Medium,
        bool postFilter = false,
        string? postFilterProvider = null,
        string? postFilterModel = null) => new(
            DefaultLanguage: defaultLanguage,
            SummaryLanguage: "en",
            SummaryStyle: summaryStyle,
            DictationLiveSttProvider: "deepgram",
            DictationLiveSttModel: "nova-3",
            RecordingLiveSttProvider: "deepgram",
            RecordingLiveSttModel: "nova-3",
            FileSttProvider: "deepgram",
            FileSttModel: "nova-3",
            DictationPostFilterEnabled: postFilter,
            DictationPostFilterProvider: postFilterProvider,
            DictationPostFilterModel: postFilterModel);

    // ----- load -------------------------------------------------------------

    [Fact]
    public async Task LoadPopulatesEveryFieldFromServer()
    {
        StubGet("/api/settings", 200, Settings(
            defaultLanguage: "ru",
            summaryStyle: SummaryStyle.Detailed,
            postFilter: true,
            postFilterProvider: "openai",
            postFilterModel: "gpt-4o-mini"));

        await _vm.LoadAsync();

        _vm.IsLoaded.Should().BeTrue();
        _vm.DefaultLanguage.Should().Be("ru");
        _vm.SummaryStyle.Should().Be(SummaryStyle.Detailed);
        _vm.DictationLiveSttProvider.Should().Be("deepgram");
        _vm.DictationLiveSttModel.Should().Be("nova-3");
        _vm.FileSttProvider.Should().Be("deepgram");
        _vm.DictationPostFilterEnabled.Should().BeTrue();
        _vm.DictationPostFilterProvider.Should().Be("openai");
        _vm.DictationPostFilterModel.Should().Be("gpt-4o-mini");
        _vm.ErrorMessage.Should().BeNull();
        _vm.IsLoading.Should().BeFalse();
        _vm.HasChanges.Should().BeFalse(); // freshly loaded = clean
    }

    [Fact]
    public async Task LoadFailureSurfacesErrorWithoutFabricatingDefaults()
    {
        StubGet("/api/settings", 500);

        await _vm.LoadAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.IsLoaded.Should().BeFalse();      // no fabricated state on failure
        _vm.DefaultLanguage.Should().BeEmpty();
        _vm.IsLoading.Should().BeFalse();
    }

    // ----- dirty tracking ---------------------------------------------------

    [Fact]
    public async Task EditingAFieldSetsHasChangesAndEnablesSave()
    {
        StubGet("/api/settings", 200, Settings(defaultLanguage: "en"));
        await _vm.LoadAsync();
        _vm.HasChanges.Should().BeFalse();
        _vm.CanSave.Should().BeFalse();

        _vm.DefaultLanguage = "ru";

        _vm.HasChanges.Should().BeTrue();
        _vm.CanSave.Should().BeTrue();
        _vm.SaveCommand.CanExecute(null).Should().BeTrue();
    }

    [Fact]
    public async Task RevertingAnEditBackToServerValueClearsHasChanges()
    {
        StubGet("/api/settings", 200, Settings(defaultLanguage: "en"));
        await _vm.LoadAsync();

        _vm.DefaultLanguage = "ru";
        _vm.HasChanges.Should().BeTrue();

        _vm.DefaultLanguage = "en"; // back to the loaded value

        _vm.HasChanges.Should().BeFalse();
        _vm.CanSave.Should().BeFalse();
    }

    [Fact]
    public void SaveIsDisabledBeforeAnyLoad()
    {
        _vm.IsLoaded.Should().BeFalse();
        _vm.CanSave.Should().BeFalse();
        _vm.SaveCommand.CanExecute(null).Should().BeFalse();
    }

    // ----- save -------------------------------------------------------------

    [Fact]
    public async Task SavePatchesEditedSettingsAndRefreshesFromResponse()
    {
        StubGet("/api/settings", 200, Settings(defaultLanguage: "en", summaryStyle: SummaryStyle.Medium));
        // Server echoes back the persisted state (canonicalised).
        StubPatch("/api/settings", 200, Settings(defaultLanguage: "ru", summaryStyle: SummaryStyle.Detailed));

        await _vm.LoadAsync();
        _vm.DefaultLanguage = "ru";
        _vm.SummaryStyle = SummaryStyle.Detailed;
        _vm.HasChanges.Should().BeTrue();

        await _vm.SaveAsync();

        // PATCH was hit with the edited values serialised snake_case.
        var patch = _server.LogEntries.Single(e =>
            e.RequestMessage.Path == "/api/settings" && e.RequestMessage.Method == "PATCH");
        var body = patch.RequestMessage.Body!;
        body.Should().Contain("\"default_language\":\"ru\"");
        body.Should().Contain("\"summary_style\":\"detailed\"");

        // State refreshed from the response, and the form is clean again.
        _vm.DefaultLanguage.Should().Be("ru");
        _vm.SummaryStyle.Should().Be(SummaryStyle.Detailed);
        _vm.HasChanges.Should().BeFalse();
        _vm.CanSave.Should().BeFalse();
        _vm.ErrorMessage.Should().BeNull();
        _vm.IsSaving.Should().BeFalse();
    }

    [Fact]
    public async Task SaveFailureSurfacesErrorAndKeepsEdits()
    {
        StubGet("/api/settings", 200, Settings(defaultLanguage: "en"));
        StubPatch("/api/settings", 500);

        await _vm.LoadAsync();
        _vm.DefaultLanguage = "ru";

        await _vm.SaveAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _vm.DefaultLanguage.Should().Be("ru"); // edits preserved — no silent rollback
        _vm.HasChanges.Should().BeTrue();
        _vm.IsSaving.Should().BeFalse();
    }

    [Fact]
    public async Task SaveBeforeLoadSurfacesErrorAndNeverCallsServer()
    {
        await _vm.SaveAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _server.LogEntries.Should().NotContain(e =>
            e.RequestMessage.Path == "/api/settings" && e.RequestMessage.Method == "PATCH");
    }

    [Fact]
    public async Task SaveSendsTheFullRequestIncludingUneditedFields()
    {
        StubGet("/api/settings", 200, Settings(defaultLanguage: "en", postFilter: true,
            postFilterProvider: "openai", postFilterModel: "gpt-4o-mini"));
        StubPatch("/api/settings", 200, Settings(defaultLanguage: "ru", postFilter: true,
            postFilterProvider: "openai", postFilterModel: "gpt-4o-mini"));

        await _vm.LoadAsync();
        _vm.DefaultLanguage = "ru"; // only edit one field

        await _vm.SaveAsync();

        var patch = _server.LogEntries.Single(e =>
            e.RequestMessage.Path == "/api/settings" && e.RequestMessage.Method == "PATCH");
        var body = patch.RequestMessage.Body!;
        // The whole snapshot is sent, not just the dirty field.
        body.Should().Contain("\"default_language\":\"ru\"");
        body.Should().Contain("\"dictation_post_filter_enabled\":true");
        body.Should().Contain("\"dictation_post_filter_provider\":\"openai\"");
        body.Should().Contain("\"file_stt_model\":\"nova-3\"");
    }
}
