using System.Net;
using System.Text;
using System.Text.Json;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;

namespace WaiComputer.Core.Tests.Api;

public class ApiClientTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        return Task.CompletedTask;
    }

    public Task DisposeAsync()
    {
        _client.Dispose();
        _server.Stop();
        _server.Dispose();
        return Task.CompletedTask;
    }

    private static string Json<T>(T value) => JsonSerializer.Serialize(value, WaiJson.Options);

    [Fact]
    public async Task LoginRoundTrips()
    {
        var response = new AuthResponse("at", "rt", "Bearer");
        _server.Given(Request.Create().UsingPost().WithPath("/api/auth/login"))
               .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(response), encoding: Encoding.UTF8).WithHeader("Content-Type", "application/json"));

        var actual = await _client.LoginAsync("hi@mikwiseman.com", "p");

        actual.Should().BeEquivalentTo(response);
    }

    [Fact]
    public async Task MagicLinkSendsClientField()
    {
        _server.Given(Request.Create().UsingPost().WithPath("/api/auth/magic-link"))
               .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(new MessageResponse("sent"))).WithHeader("Content-Type", "application/json"));

        await _client.RequestMagicLinkAsync("hi@mikwiseman.com", "windows");

        var calls = _server.LogEntries.Where(e => e.RequestMessage.Path == "/api/auth/magic-link").ToList();
        calls.Should().ContainSingle();
        calls[0].RequestMessage.Body.Should().Contain("\"client\":\"windows\"");
    }

    [Fact]
    public async Task UnauthorizedTriggersRefresh()
    {
        _client.SetAccessToken("expired");
        _client.SetRefreshToken("good-refresh");

        var refreshed = new AuthResponse("new-at", "new-rt", "Bearer");
        var meCalls = 0;

        _server.Given(Request.Create().UsingGet().WithPath("/api/auth/me"))
               .InScenario("auth")
               .WillSetStateTo("refreshed")
               .RespondWith(Response.Create().WithStatusCode(401));

        _server.Given(Request.Create().UsingGet().WithPath("/api/auth/me"))
               .InScenario("auth")
               .WhenStateIs("refreshed")
               .RespondWith(Response.Create().WithStatusCode(200)
                   .WithBody(Json(new User("u", "hi@mikwiseman.com", DateTimeOffset.UtcNow, true)))
                   .WithHeader("Content-Type", "application/json"));

        _server.Given(Request.Create().UsingPost().WithPath("/api/auth/refresh"))
               .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(refreshed)).WithHeader("Content-Type", "application/json"));

        string? raisedAccess = null;
        _client.TokenRefreshed += (at, rt) => { raisedAccess = at; meCalls++; };

        var user = await _client.GetCurrentUserAsync();
        user.Email.Should().Be("hi@mikwiseman.com");
        raisedAccess.Should().Be("new-at");
        _client.GetAccessToken().Should().Be("new-at");
        _client.GetRefreshToken().Should().Be("new-rt");
    }

    [Fact]
    public async Task UnauthorizedWithoutRefreshTokenRaisesAuthFailed()
    {
        _client.SetAccessToken("anything");
        _client.SetRefreshToken(null);
        var failedCount = 0;
        _client.AuthenticationFailed += () => failedCount++;

        _server.Given(Request.Create().UsingGet().WithPath("/api/auth/me"))
               .RespondWith(Response.Create().WithStatusCode(401));

        var act = async () => await _client.GetCurrentUserAsync();
        await act.Should().ThrowAsync<ApiError.Unauthorized>();
        failedCount.Should().Be(1);
    }

    [Fact]
    public async Task BearerTokenAttached()
    {
        _client.SetAccessToken("the-token");
        _server.Given(Request.Create().UsingGet().WithPath("/api/auth/me"))
               .RespondWith(Response.Create().WithStatusCode(200)
                   .WithBody(Json(new User("u", "hi@mikwiseman.com", DateTimeOffset.UtcNow, true))).WithHeader("Content-Type", "application/json"));

        await _client.GetCurrentUserAsync();

        var logged = _server.LogEntries.Single();
        logged.RequestMessage.Headers!["Authorization"][0].Should().Be("Bearer the-token");
    }

    [Fact]
    public async Task Http500SurfacesServerDetail()
    {
        _server.Given(Request.Create().UsingGet().WithPath("/api/auth/me"))
               .RespondWith(Response.Create().WithStatusCode(500)
                   .WithBody("{\"detail\":\"boom\"}").WithHeader("Content-Type", "application/json"));

        var act = async () => await _client.GetCurrentUserAsync();
        (await act.Should().ThrowAsync<ApiError.HttpError>())
            .Which.ServerMessage.Should().Be("boom");
    }

    [Fact]
    public async Task ListRecordingsEncodesQueryParameters()
    {
        _server.Given(Request.Create().UsingGet().WithPath("/api/recordings"))
               .RespondWith(Response.Create().WithStatusCode(200).WithBody("[]").WithHeader("Content-Type", "application/json"));

        await _client.ListRecordingsAsync(skip: 25, limit: 75, starred: true);

        var entry = _server.LogEntries.Single();
        entry.RequestMessage.Query.Should().Contain(q => q.Key == "skip" && q.Value.Contains("25"));
        entry.RequestMessage.Query.Should().Contain(q => q.Key == "limit" && q.Value.Contains("75"));
        entry.RequestMessage.Query.Should().Contain(q => q.Key == "is_starred" && q.Value.Contains("true"));
    }

    [Fact]
    public async Task UploadEnforces200MbLimit()
    {
        await using var stream = new MemoryStream();
        var act = async () => await _client.UploadRecordingAudioAsync(
            "rec", stream, 250L * 1024 * 1024, "audio.wav", "audio/wav");

        await act.Should().ThrowAsync<ApiError.InvalidUrl>();
    }

    [Fact]
    public async Task NetworkErrorBecomesNetworkApiError()
    {
        using var client = new ApiClient(new Uri("http://127.0.0.1:1")); // closed port
        var act = async () => await client.GetCurrentUserAsync();
        await act.Should().ThrowAsync<ApiError.Network>();
    }

    [Fact]
    public async Task DeleteRecordingAcceptsNoContent()
    {
        _server.Given(Request.Create().UsingDelete().WithPath("/api/recordings/rec123"))
               .RespondWith(Response.Create().WithStatusCode(204));

        await _client.DeleteRecordingAsync("rec123", permanent: true);

        var entry = _server.LogEntries.Single();
        entry.RequestMessage.Query.Should().Contain(q => q.Key == "permanent" && q.Value.Contains("true"));
    }

    [Fact]
    public async Task SearchDecodesBackendShapeAndEncodesQuery()
    {
        // Literal backend SearchResponse wire shape (backend/app/api/routes/search.py).
        const string body = """
        {
          "results": [
            {
              "recording_id": "rec-1",
              "recording_title": "Standup",
              "recording_type": "meeting",
              "segment_id": "seg-1",
              "speaker": "speaker_0",
              "content": "hello world",
              "start_ms": 0,
              "end_ms": 1500,
              "score": 0.87
            },
            {
              "recording_id": "rec-2",
              "recording_title": null,
              "recording_type": "note",
              "segment_id": "seg-2",
              "speaker": null,
              "content": "second hit",
              "start_ms": null,
              "end_ms": null,
              "score": 0.42
            }
          ],
          "total": 2
        }
        """;
        _server.Given(Request.Create().UsingGet().WithPath("/api/search"))
               .RespondWith(Response.Create().WithStatusCode(200)
                   .WithBody(body).WithHeader("Content-Type", "application/json"));

        var r = await _client.SearchAsync("hello world");

        r.Total.Should().Be(2);
        r.Results.Should().HaveCount(2);
        r.Results[0].RecordingId.Should().Be("rec-1");
        r.Results[0].RecordingTitle.Should().Be("Standup");
        r.Results[0].RecordingType.Should().Be(RecordingType.Meeting);
        r.Results[0].SegmentId.Should().Be("seg-1");
        r.Results[0].Speaker.Should().Be("speaker_0");
        r.Results[0].Content.Should().Be("hello world");
        r.Results[0].StartMs.Should().Be(0);
        r.Results[0].EndMs.Should().Be(1500);
        r.Results[0].Score.Should().Be(0.87);
        r.Results[1].RecordingTitle.Should().BeNull();
        r.Results[1].RecordingType.Should().Be(RecordingType.Note);
        r.Results[1].Speaker.Should().BeNull();
        r.Results[1].StartMs.Should().BeNull();

        var entry = _server.LogEntries.Single();
        entry.RequestMessage.Query!.Single(q => q.Key == "q").Value
            .Should().ContainSingle(v => v == "hello world");
    }
}
