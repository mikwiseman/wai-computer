using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Auth;
using WaiComputer.Core.ViewModels;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;

namespace WaiComputer.Core.Tests.ViewModels;

public class AuthViewModelTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private string _sessionFile = null!;
    private SessionStore _store = null!;
    private AuthViewModel _vm = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _sessionFile = Path.Combine(Path.GetTempPath(), "wc-auth-" + Guid.NewGuid().ToString("N") + ".json");
        _store = new SessionStore(_sessionFile, new NullSessionProtector());
        _vm = new AuthViewModel(_client, _store, client: "windows");
        return Task.CompletedTask;
    }

    public Task DisposeAsync()
    {
        _vm.Dispose();
        _client.Dispose();
        _server.Stop();
        _server.Dispose();
        try { File.Delete(_sessionFile); } catch { }
        return Task.CompletedTask;
    }

    private static string Json<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value, WaiJson.Options);

    private void StubPost(string path, int status, object? body = null) => _server
        .Given(Request.Create().UsingPost().WithPath(path))
        .RespondWith(Body(Response.Create().WithStatusCode(status), status, body));

    private void StubGet(string path, int status, object? body = null) => _server
        .Given(Request.Create().UsingGet().WithPath(path))
        .RespondWith(Body(Response.Create().WithStatusCode(status), status, body));

    private static IResponseBuilder Body(IResponseBuilder resp, int status, object? body)
        => body is null ? resp : resp.WithBody(Json(body)).WithHeader("Content-Type", "application/json");

    private static AuthResponse Auth(string access, string? refresh) => new(access, refresh, "bearer");
    private static User Account(string email = "user@example.com") => new("u1", email, DateTimeOffset.UtcNow, true);

    // ----- password sign-in -------------------------------------------------

    [Fact]
    public async Task SignInWithValidCredentialsPersistsSessionAndSignsIn()
    {
        StubPost("/api/auth/login", 200, Auth("acc-token", "ref-token"));
        StubGet("/api/auth/me", 200, Account());

        User? signedIn = null;
        _vm.SignedIn += u => signedIn = u;
        _vm.Email = "user@example.com";
        _vm.Password = "secret";

        await _vm.SignInWithPasswordAsync();

        _vm.Status.Should().Be(AuthStatus.SignedIn);
        _vm.CurrentUser.Should().NotBeNull();
        _vm.Password.Should().BeEmpty(); // cleared after success
        signedIn.Should().NotBeNull();
        _client.GetAccessToken().Should().Be("acc-token");
        _store.Load()!.AccessToken.Should().Be("acc-token"); // persisted
    }

    [Fact]
    public async Task SignInFailureSurfacesErrorAndStaysSignedOut()
    {
        StubPost("/api/auth/login", 401);
        _vm.Email = "user@example.com";
        _vm.Password = "wrong";

        await _vm.SignInWithPasswordAsync();

        _vm.Status.Should().Be(AuthStatus.SignedOut);
        _vm.CurrentUser.Should().BeNull();
        _vm.ErrorMessage.Should().NotBeNull();
        _store.Load().Should().BeNull(); // nothing persisted
    }

    [Fact]
    public async Task SignInRejectsInvalidEmailWithoutCallingServer()
    {
        _vm.Email = "not-an-email";
        _vm.Password = "secret";

        await _vm.SignInWithPasswordAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _server.LogEntries.Should().NotContain(e => e.RequestMessage.Path == "/api/auth/login");
    }

    [Fact]
    public async Task SignInRejectsEmptyPassword()
    {
        _vm.Email = "user@example.com";
        _vm.Password = "";

        await _vm.SignInWithPasswordAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _server.LogEntries.Should().NotContain(e => e.RequestMessage.Path == "/api/auth/login");
    }

    // ----- magic link -------------------------------------------------------

    [Fact]
    public async Task SendMagicLinkSetsInfoMessageFromServer()
    {
        StubPost("/api/auth/magic-link", 200, new MessageResponse("Check your inbox."));
        _vm.Email = "user@example.com";

        await _vm.SendMagicLinkAsync();

        _vm.InfoMessage.Should().Be("Check your inbox.");
        _vm.ErrorMessage.Should().BeNull();
    }

    [Fact]
    public async Task SendMagicLinkRejectsInvalidEmail()
    {
        _vm.Email = "  ";

        await _vm.SendMagicLinkAsync();

        _vm.ErrorMessage.Should().NotBeNull();
        _server.LogEntries.Should().NotContain(e => e.RequestMessage.Path == "/api/auth/magic-link");
    }

    [Fact]
    public async Task HandleValidMagicLinkUrlVerifiesAndSignsIn()
    {
        StubPost("/api/auth/verify-magic", 200, Auth("magic-acc", "magic-ref"));
        StubGet("/api/auth/me", 200, Account());

        var ok = await _vm.HandleMagicLinkUrlAsync("waicomputer://auth/verify?token=abc123");

        ok.Should().BeTrue();
        _vm.Status.Should().Be(AuthStatus.SignedIn);
        _client.GetAccessToken().Should().Be("magic-acc");
        _store.Load()!.AccessToken.Should().Be("magic-acc");
    }

    [Fact]
    public async Task HandleInvalidMagicLinkUrlReturnsFalseWithoutServerCall()
    {
        var ok = await _vm.HandleMagicLinkUrlAsync("https://evil.example.com/auth/verify?token=x");

        ok.Should().BeFalse();
        _vm.ErrorMessage.Should().NotBeNull();
        _vm.Status.Should().NotBe(AuthStatus.SignedIn);
        _server.LogEntries.Should().NotContain(e => e.RequestMessage.Path == "/api/auth/verify-magic");
    }

    // ----- session restore --------------------------------------------------

    [Fact]
    public async Task RestoreSessionWithValidStoredTokenSignsIn()
    {
        _store.Save("stored-access", "stored-refresh");
        StubGet("/api/auth/me", 200, Account());

        await _vm.RestoreSessionAsync();

        _vm.Status.Should().Be(AuthStatus.SignedIn);
        _vm.CurrentUser.Should().NotBeNull();
        _client.GetAccessToken().Should().Be("stored-access");
    }

    [Fact]
    public async Task RestoreSessionWithRejectedTokenClearsAndSignsOut()
    {
        _store.Save("stale-access", "stale-refresh");
        StubGet("/api/auth/me", 401); // no refresh token recovery stub -> recovery fails, surfaces 401

        await _vm.RestoreSessionAsync();

        _vm.Status.Should().Be(AuthStatus.SignedOut);
        _vm.CurrentUser.Should().BeNull();
        _store.Load().Should().BeNull(); // cleared
    }

    [Fact]
    public async Task RestoreSessionWithNoStoredSessionSignsOut()
    {
        var signedOut = false;
        _vm.SignedOut += () => signedOut = true;

        await _vm.RestoreSessionAsync();

        _vm.Status.Should().Be(AuthStatus.SignedOut);
        signedOut.Should().BeTrue();
        _server.LogEntries.Should().BeEmpty(); // never hit the server
    }

    // ----- sign out ---------------------------------------------------------

    [Fact]
    public async Task SignOutClearsSessionAndTokensAndFiresEvent()
    {
        _store.Save("acc", "ref");
        _client.SetAccessToken("acc");
        _client.SetRefreshToken("ref");
        StubPost("/api/auth/logout", 200, new MessageResponse("ok"));

        var signedOut = false;
        _vm.SignedOut += () => signedOut = true;

        await _vm.SignOutAsync();

        _vm.Status.Should().Be(AuthStatus.SignedOut);
        _client.GetAccessToken().Should().BeNull();
        _store.Load().Should().BeNull();
        signedOut.Should().BeTrue();
    }

    [Fact]
    public async Task SignOutSucceedsLocallyEvenIfServerLogoutFails()
    {
        _store.Save("acc", "ref");
        _client.SetAccessToken("acc");
        _client.SetRefreshToken("ref");
        StubPost("/api/auth/logout", 500); // server revoke fails

        await _vm.SignOutAsync();

        _vm.Status.Should().Be(AuthStatus.SignedOut);
        _store.Load().Should().BeNull(); // local sign-out still completes
    }

    // ----- token refresh wiring (real 401 -> refresh -> retry flow) ----------

    [Fact]
    public async Task RefreshedTokenIsPersistedToSessionStore()
    {
        _store.Save("old-access", "old-refresh");
        _client.SetAccessToken("old-access");
        _client.SetRefreshToken("old-refresh");

        // /api/auth/me: 401 first, then 200 after the token is refreshed.
        _server.Given(Request.Create().UsingGet().WithPath("/api/auth/me"))
            .InScenario("refresh").WillSetStateTo("refreshed")
            .RespondWith(Response.Create().WithStatusCode(401));
        _server.Given(Request.Create().UsingGet().WithPath("/api/auth/me"))
            .InScenario("refresh").WhenStateIs("refreshed")
            .RespondWith(Response.Create().WithStatusCode(200).WithBody(Json(Account())).WithHeader("Content-Type", "application/json"));
        StubPost("/api/auth/refresh", 200, Auth("new-access", "new-refresh"));

        // Drive a refresh directly through the real client; the VM (subscribed in ctor) must persist it.
        await _client.GetCurrentUserAsync();

        _store.Load()!.AccessToken.Should().Be("new-access");
        _store.Load()!.RefreshToken.Should().Be("new-refresh");
    }
}
