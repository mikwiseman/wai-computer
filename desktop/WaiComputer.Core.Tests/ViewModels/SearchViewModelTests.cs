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

public class SearchViewModelTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private SearchViewModel _vm = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _vm = new SearchViewModel(_client);
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

    private static IResponseBuilder Body(IResponseBuilder resp, int status, object? body)
        => body is null ? resp : resp.WithBody(Json(body)).WithHeader("Content-Type", "application/json");

    private static SearchHit Hit(string id, string content, double score) =>
        new(id, "Standup", RecordingType.Meeting, id + "-seg", "speaker_0", content, 0, 1500, score);

    private static SearchResponse Response2() =>
        new(new[] { Hit("rec-1", "hello world", 0.9), Hit("rec-2", "second hit", 0.4) }, 2);

    // ----- hybrid (default) search -----------------------------------------

    [Fact]
    public async Task SearchInHybridModeHitsRootEndpointAndPopulatesResults()
    {
        StubGet("/api/search", 200, Response2());
        _vm.Query = "hello";

        await _vm.SearchAsync();

        _vm.Results.Should().HaveCount(2);
        _vm.Results[0].RecordingId.Should().Be("rec-1");
        _vm.Results[0].Content.Should().Be("hello world");
        _vm.Total.Should().Be(2);
        _vm.IsSearching.Should().BeFalse();
        _vm.ErrorMessage.Should().BeNull();
        _vm.HasNoResults.Should().BeFalse();
        _server.LogEntries.Should().Contain(e => e.RequestMessage.Path == "/api/search");
    }

    // ----- mode routing -----------------------------------------------------

    [Fact]
    public async Task SemanticModeHitsSemanticEndpoint()
    {
        StubGet("/api/search/semantic", 200, Response2());
        _vm.Mode = SearchMode.Semantic;
        _vm.Query = "ideas";

        await _vm.SearchAsync();

        _vm.Results.Should().HaveCount(2);
        _server.LogEntries.Should().Contain(e => e.RequestMessage.Path == "/api/search/semantic");
        _server.LogEntries.Should().NotContain(e => e.RequestMessage.Path == "/api/search");
    }

    [Fact]
    public async Task FullTextModeHitsFtsEndpoint()
    {
        StubGet("/api/search/fts", 200, new SearchResponse(new[] { Hit("rec-9", "exact phrase", 1.0) }, 1));
        _vm.Mode = SearchMode.FullText;
        _vm.Query = "exact phrase";

        await _vm.SearchAsync();

        _vm.Results.Should().ContainSingle();
        _vm.Total.Should().Be(1);
        _server.LogEntries.Should().Contain(e => e.RequestMessage.Path == "/api/search/fts");
    }

    [Fact]
    public async Task QueryIsTrimmedAndUrlEncodedOnTheWire()
    {
        StubGet("/api/search", 200, Response2());
        _vm.Query = "  hello world  ";

        await _vm.SearchAsync();

        var entry = _server.LogEntries.Single();
        entry.RequestMessage.Query.Should().Contain(q => q.Key == "q" && q.Value.Contains("hello world"));
    }

    // ----- empty-result path (not an error, no silent fallback) -------------

    [Fact]
    public async Task EmptyResultSetClearsResultsAndFlagsHasNoResults()
    {
        StubGet("/api/search", 200, new SearchResponse(Array.Empty<SearchHit>(), 0));
        _vm.Query = "nothing matches";

        await _vm.SearchAsync();

        _vm.Results.Should().BeEmpty();
        _vm.Total.Should().Be(0);
        _vm.ErrorMessage.Should().BeNull();
        _vm.HasNoResults.Should().BeTrue(); // ran, found nothing — distinct from idle
    }

    // ----- error path (ErrorMessage surfaces, no fabricated defaults) -------

    [Fact]
    public async Task ServerErrorSurfacesErrorMessageAndDoesNotMaskAsEmptyResults()
    {
        StubGet("/api/search", 500);
        _vm.Query = "hello";

        await _vm.SearchAsync();

        _vm.ErrorMessage.Should().NotBeNull(); // no silent fallback
        _vm.Results.Should().BeEmpty();
        _vm.Total.Should().Be(0);
        _vm.IsSearching.Should().BeFalse();
        _vm.HasNoResults.Should().BeFalse(); // error is NOT a "no results" empty state
    }

    [Fact]
    public async Task ErrorThenSuccessClearsThePreviousErrorMessage()
    {
        StubGet("/api/search", 500);
        _vm.Query = "hello";
        await _vm.SearchAsync();
        _vm.ErrorMessage.Should().NotBeNull();

        _server.Reset();
        StubGet("/api/search", 200, Response2());
        await _vm.SearchAsync();

        _vm.ErrorMessage.Should().BeNull();
        _vm.Results.Should().HaveCount(2);
    }

    // ----- SearchCommand guard ----------------------------------------------

    [Fact]
    public async Task SearchCommandIsDisabledForEmptyQueryAndNoOpsWithoutServerCall()
    {
        _vm.Query = "   ";
        _vm.SearchCommand.CanExecute(null).Should().BeFalse();

        await _vm.SearchCommand.ExecuteAsync(null);

        _server.LogEntries.Should().BeEmpty(); // never hit the server
        _vm.ErrorMessage.Should().BeNull();
        _vm.HasSearched.Should().BeFalse();
    }

    [Fact]
    public void SearchCommandBecomesExecutableWhenQueryIsTyped()
    {
        _vm.SearchCommand.CanExecute(null).Should().BeFalse();
        _vm.Query = "anything";
        _vm.SearchCommand.CanExecute(null).Should().BeTrue();
    }

    // ----- ClearCommand -----------------------------------------------------

    [Fact]
    public async Task ClearCommandResetsQueryResultsAndState()
    {
        StubGet("/api/search", 200, Response2());
        _vm.Query = "hello";
        await _vm.SearchAsync();
        _vm.Results.Should().HaveCount(2);

        _vm.ClearCommand.Execute(null);

        _vm.Query.Should().BeEmpty();
        _vm.Results.Should().BeEmpty();
        _vm.Total.Should().Be(0);
        _vm.ErrorMessage.Should().BeNull();
        _vm.HasSearched.Should().BeFalse();
        _vm.HasNoResults.Should().BeFalse();
    }
}
