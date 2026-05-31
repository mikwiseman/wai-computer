using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Api;

/// <summary>
/// REST + SSE client for the WaiComputer backend at <c>https://wai.computer</c>.
/// Thread-safe. All methods retry once on a 401 by triggering a coalesced refresh.
/// </summary>
public sealed class ApiClient : IApiClient, IDisposable
{
    private readonly HttpClient _http;
    private readonly bool _ownsHttp;
    private readonly Uri _baseUrl;
    private readonly ILogger<ApiClient> _logger;
    private readonly TokenRefreshCoordinator _refresher;

    private readonly object _tokenLock = new();
    private string? _accessToken;
    private string? _refreshToken;

    public event Action<string, string?>? TokenRefreshed;
    public event Action? AuthenticationFailed;

    public ApiClient(Uri baseUrl, HttpClient? http = null, ILogger<ApiClient>? logger = null)
    {
        _baseUrl = baseUrl ?? throw new ArgumentNullException(nameof(baseUrl));
        _logger = logger ?? NullLogger<ApiClient>.Instance;
        if (http is null)
        {
            _http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
            _ownsHttp = true;
        }
        else
        {
            _http = http;
            _ownsHttp = false;
        }
        _refresher = new TokenRefreshCoordinator(RefreshOnceAsync);
    }

    // ----- session ------------------------------------------------------

    public void SetAccessToken(string? token)
    {
        lock (_tokenLock) { _accessToken = token; }
    }

    public void SetRefreshToken(string? token)
    {
        lock (_tokenLock) { _refreshToken = token; }
    }

    public string? GetAccessToken()
    {
        lock (_tokenLock) { return _accessToken; }
    }

    public string? GetRefreshToken()
    {
        lock (_tokenLock) { return _refreshToken; }
    }

    // ----- auth ---------------------------------------------------------

    public Task<AuthResponse> RegisterAsync(string email, string password, CancellationToken ct = default)
        => SendJsonAsync<RegisterRequest, AuthResponse>(HttpMethod.Post, "/api/auth/register",
            new RegisterRequest(email, password), authenticated: false, ct);

    public Task<AuthResponse> LoginAsync(string email, string password, CancellationToken ct = default)
        => SendJsonAsync<LoginRequest, AuthResponse>(HttpMethod.Post, "/api/auth/login",
            new LoginRequest(email, password), authenticated: false, ct);

    public Task<MessageResponse> RequestMagicLinkAsync(string email, string? client, CancellationToken ct = default)
        => SendJsonAsync<MagicLinkRequest, MessageResponse>(HttpMethod.Post, "/api/auth/magic-link",
            new MagicLinkRequest(email, client), authenticated: false, ct);

    public Task<AuthResponse> VerifyMagicLinkAsync(string token, CancellationToken ct = default)
        => SendJsonAsync<VerifyMagicLinkRequest, AuthResponse>(HttpMethod.Post, "/api/auth/verify-magic",
            new VerifyMagicLinkRequest(token), authenticated: false, ct);

    public Task<User> GetCurrentUserAsync(CancellationToken ct = default)
        => SendAsync<User>(HttpMethod.Get, "/api/auth/me", ct: ct);

    public Task<MessageResponse> ChangePasswordAsync(string current, string next, CancellationToken ct = default)
        => SendJsonAsync<ChangePasswordRequest, MessageResponse>(HttpMethod.Post, "/api/settings/change-password",
            new ChangePasswordRequest(current, next), ct: ct);

    public async Task<MessageResponse> LogoutAsync(string? refreshToken, CancellationToken ct = default)
    {
        var body = new LogoutRequest(refreshToken);
        try
        {
            return await SendJsonAsync<LogoutRequest, MessageResponse>(HttpMethod.Post, "/api/auth/logout", body, ct: ct).ConfigureAwait(false);
        }
        finally
        {
            SetAccessToken(null);
            SetRefreshToken(null);
        }
    }

    public Task<MessageResponse> DeleteAccountAsync(CancellationToken ct = default)
        => SendAsync<MessageResponse>(HttpMethod.Delete, "/api/auth/me", ct: ct);

    // ----- settings -----------------------------------------------------

    public Task<UserSettings> GetSettingsAsync(CancellationToken ct = default)
        => SendAsync<UserSettings>(HttpMethod.Get, "/api/settings", ct: ct);

    public Task<TranscriptionOptions> GetTranscriptionOptionsAsync(CancellationToken ct = default)
        => SendAsync<TranscriptionOptions>(HttpMethod.Get, "/api/settings/transcription-options", ct: ct);

    public Task<UserSettings> UpdateSettingsAsync(UpdateSettingsRequest request, CancellationToken ct = default)
        => SendJsonAsync<UpdateSettingsRequest, UserSettings>(HttpMethod.Patch, "/api/settings", request, ct: ct);

    public Task<UserIdentity> GetIdentityAsync(CancellationToken ct = default)
        => SendAsync<UserIdentity>(HttpMethod.Get, "/api/settings/identity", ct: ct);

    public Task<UserIdentity> UpdateIdentityAsync(UpdateIdentityRequest request, CancellationToken ct = default)
        => SendJsonAsync<UpdateIdentityRequest, UserIdentity>(HttpMethod.Patch, "/api/settings/identity", request, ct: ct);

    public Task<VoiceSharingState> GetVoiceSharingAsync(CancellationToken ct = default)
        => SendAsync<VoiceSharingState>(HttpMethod.Get, "/api/settings/voice-sharing", ct: ct);

    public Task<VoiceSharingState> EnableVoiceSharingAsync(CancellationToken ct = default)
        => SendAsync<VoiceSharingState>(HttpMethod.Post, "/api/settings/voice-sharing", ct: ct);

    public Task<VoiceSharingState> DisableVoiceSharingAsync(CancellationToken ct = default)
        => SendAsync<VoiceSharingState>(HttpMethod.Delete, "/api/settings/voice-sharing", ct: ct);

    // ----- recordings ---------------------------------------------------

    public Task<IReadOnlyList<Recording>> ListRecordingsAsync(int skip = 0, int limit = 50, bool? starred = null, CancellationToken ct = default)
    {
        var qs = $"?skip={skip}&limit={limit}" + (starred is bool s ? $"&is_starred={(s ? "true" : "false")}" : string.Empty);
        return SendAsync<IReadOnlyList<Recording>>(HttpMethod.Get, "/api/recordings" + qs, ct: ct);
    }

    public Task<Recording> CreateRecordingAsync(CreateRecordingRequest request, CancellationToken ct = default)
        => SendJsonAsync<CreateRecordingRequest, Recording>(HttpMethod.Post, "/api/recordings", request, ct: ct);

    public Task<RecordingDetail> GetRecordingAsync(string id, CancellationToken ct = default)
        => SendAsync<RecordingDetail>(HttpMethod.Get, $"/api/recordings/{Uri.EscapeDataString(id)}", ct: ct);

    public Task<Recording> UpdateRecordingAsync(string id, UpdateRecordingRequest request, CancellationToken ct = default)
        => SendJsonAsync<UpdateRecordingRequest, Recording>(HttpMethod.Patch, $"/api/recordings/{Uri.EscapeDataString(id)}", request, ct: ct);

    public async Task DeleteRecordingAsync(string id, bool permanent = false, CancellationToken ct = default)
    {
        var qs = permanent ? "?permanent=true" : string.Empty;
        await SendNoContentAsync(HttpMethod.Delete, $"/api/recordings/{Uri.EscapeDataString(id)}{qs}", ct).ConfigureAwait(false);
    }

    public Task<Recording> RestoreRecordingAsync(string id, CancellationToken ct = default)
        => SendAsync<Recording>(HttpMethod.Post, $"/api/recordings/{Uri.EscapeDataString(id)}/restore", ct: ct);

    public Task<RecordingShareLink> CreateRecordingShareLinkAsync(string id, CancellationToken ct = default)
        => SendAsync<RecordingShareLink>(HttpMethod.Post, $"/api/recordings/{Uri.EscapeDataString(id)}/share", ct: ct);

    public Task<IReadOnlyList<Segment>> GetTranscriptAsync(string recordingId, CancellationToken ct = default)
        => SendAsync<IReadOnlyList<Segment>>(HttpMethod.Get, $"/api/recordings/{Uri.EscapeDataString(recordingId)}/transcript", ct: ct);

    public Task<Recording> StarRecordingAsync(string id, CancellationToken ct = default)
        => SendAsync<Recording>(HttpMethod.Post, $"/api/recordings/{Uri.EscapeDataString(id)}/star", ct: ct);

    public Task<Recording> UnstarRecordingAsync(string id, CancellationToken ct = default)
        => SendAsync<Recording>(HttpMethod.Delete, $"/api/recordings/{Uri.EscapeDataString(id)}/star", ct: ct);

    public async Task<RecordingDetail> UploadRecordingAudioAsync(
        string recordingId,
        Stream audioStream,
        long contentLength,
        string fileName,
        string contentType,
        IProgress<long>? progress = null,
        CancellationToken ct = default)
    {
        if (contentLength > 200L * 1024 * 1024)
        {
            throw new ApiError.InvalidUrl($"Recording payload {contentLength} bytes exceeds 200 MB limit");
        }

        using var form = new MultipartFormDataContent();
        var stream = progress is null ? audioStream : new ProgressStream(audioStream, progress);
        var fileContent = new StreamContent(stream);
        fileContent.Headers.ContentType = MediaTypeHeaderValue.Parse(contentType);
        fileContent.Headers.ContentLength = contentLength;
        form.Add(fileContent, "file", fileName); // backend route expects the part named "file"

        using var req = new HttpRequestMessage(HttpMethod.Post, ResolveUri($"/api/recordings/{Uri.EscapeDataString(recordingId)}/upload"))
        {
            Content = form,
        };
        AttachBearer(req);

        try
        {
            using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            return await ReadOrThrowAsync<RecordingDetail>(resp, ct).ConfigureAwait(false);
        }
        catch (HttpRequestException ex)
        {
            throw new ApiError.Network(ex.Message, ex);
        }
        catch (TaskCanceledException) when (!ct.IsCancellationRequested)
        {
            throw new ApiError.Network("Upload timed out");
        }
    }

    public Task<RecordingDetail> SaveLiveTranscriptAsync(
        string recordingId,
        IReadOnlyList<LiveTranscriptSegment> segments,
        int durationSeconds,
        CancellationToken ct = default)
        => SendJsonAsync<SaveTranscriptRequest, RecordingDetail>(
            HttpMethod.Post,
            $"/api/recordings/{Uri.EscapeDataString(recordingId)}/transcript",
            new SaveTranscriptRequest(segments, durationSeconds),
            ct: ct);

    public Task<RecordingDetail> AssignSpeakerAsync(
        string recordingId,
        AssignSpeakerRequest request,
        CancellationToken ct = default)
        => SendJsonAsync<AssignSpeakerRequest, RecordingDetail>(
            HttpMethod.Post,
            $"/api/recordings/{Uri.EscapeDataString(recordingId)}/assign-speaker",
            request,
            ct: ct);

    public Task<RematchSpeakersResponse> RematchSpeakersAsync(
        string recordingId,
        CancellationToken ct = default)
        => SendAsync<RematchSpeakersResponse>(
            HttpMethod.Post,
            $"/api/recordings/{Uri.EscapeDataString(recordingId)}/rematch",
            ct: ct);

    // ----- people -------------------------------------------------------

    public Task<IReadOnlyList<Person>> ListPeopleAsync(CancellationToken ct = default)
        => SendAsync<IReadOnlyList<Person>>(HttpMethod.Get, "/api/people", ct: ct);

    public Task<Person> CreatePersonAsync(CreatePersonRequest request, CancellationToken ct = default)
        => SendJsonAsync<CreatePersonRequest, Person>(HttpMethod.Post, "/api/people", request, ct: ct);

    public Task<Person> UpdatePersonAsync(string id, UpdatePersonRequest request, CancellationToken ct = default)
        => SendJsonAsync<UpdatePersonRequest, Person>(HttpMethod.Patch, $"/api/people/{Uri.EscapeDataString(id)}", request, ct: ct);

    public Task DeletePersonAsync(string id, CancellationToken ct = default)
        => SendNoContentAsync(HttpMethod.Delete, $"/api/people/{Uri.EscapeDataString(id)}", ct);

    public Task<Person> MergePersonAsync(string sourceId, MergePersonRequest request, CancellationToken ct = default)
        => SendJsonAsync<MergePersonRequest, Person>(HttpMethod.Post, $"/api/people/{Uri.EscapeDataString(sourceId)}/merge", request, ct: ct);

    // ----- summary / export ---------------------------------------------

    public Task<Summary> GetSummaryAsync(string recordingId, CancellationToken ct = default)
        => SendAsync<Summary>(HttpMethod.Get, $"/api/recordings/{Uri.EscapeDataString(recordingId)}/summary", ct: ct);

    public Task<Summary> GenerateSummaryAsync(string recordingId, CancellationToken ct = default)
        => SendAsync<Summary>(HttpMethod.Post, $"/api/recordings/{Uri.EscapeDataString(recordingId)}/generate-summary", ct: ct);

    public async Task<string> ExportRecordingAsync(string id, string format, CancellationToken ct = default)
    {
        using var req = new HttpRequestMessage(HttpMethod.Get,
            ResolveUri($"/api/recordings/{Uri.EscapeDataString(id)}/export?format={Uri.EscapeDataString(format)}"));
        AttachBearer(req);
        using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseContentRead, ct).ConfigureAwait(false);
        if (resp.StatusCode == HttpStatusCode.Unauthorized && await TryRecoverAuthAsync(ct).ConfigureAwait(false))
        {
            return await ExportRecordingAsync(id, format, ct).ConfigureAwait(false);
        }
        await EnsureSuccessAsync(resp, ct).ConfigureAwait(false);
        return await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
    }

    // ----- search -------------------------------------------------------

    public Task<SearchResponse> SearchAsync(string query, int limit = 20, int offset = 0, CancellationToken ct = default)
        => SendAsync<SearchResponse>(HttpMethod.Get,
            $"/api/search?q={Uri.EscapeDataString(query)}&limit={limit}&offset={offset}", ct: ct);

    public Task<SearchResponse> SemanticSearchAsync(string query, int limit = 20, double threshold = 0.3, CancellationToken ct = default)
        => SendAsync<SearchResponse>(HttpMethod.Get,
            $"/api/search/semantic?q={Uri.EscapeDataString(query)}&limit={limit}&threshold={threshold.ToString(CultureInfo.InvariantCulture)}", ct: ct);

    public Task<SearchResponse> FullTextSearchAsync(string query, int limit = 20, int offset = 0, CancellationToken ct = default)
        => SendAsync<SearchResponse>(HttpMethod.Get,
            $"/api/search/fts?q={Uri.EscapeDataString(query)}&limit={limit}&offset={offset}", ct: ct);

    // ----- action items -------------------------------------------------

    public Task<IReadOnlyList<ActionItem>> ListActionItemsAsync(ActionItemStatus? status = null, ActionItemPriority? priority = null, CancellationToken ct = default)
    {
        var qs = new StringBuilder("?");
        if (status is { } s) qs.Append("status=").Append(s.ToString().ToLowerInvariant()).Append('&');
        if (priority is { } p) qs.Append("priority=").Append(p.ToString().ToLowerInvariant()).Append('&');
        var query = qs.Length > 1 ? qs.ToString().TrimEnd('&', '?') : string.Empty;
        return SendAsync<IReadOnlyList<ActionItem>>(HttpMethod.Get, "/api/action-items" + (string.IsNullOrEmpty(query) ? string.Empty : "?" + query), ct: ct);
    }

    public Task<ActionItem> UpdateActionItemAsync(string id, UpdateActionItemRequest request, CancellationToken ct = default)
        => SendJsonAsync<UpdateActionItemRequest, ActionItem>(HttpMethod.Patch, $"/api/action-items/{Uri.EscapeDataString(id)}", request, ct: ct);

    public Task DeleteActionItemAsync(string id, CancellationToken ct = default)
        => SendNoContentAsync(HttpMethod.Delete, $"/api/action-items/{Uri.EscapeDataString(id)}", ct);

    // ----- dictation ----------------------------------------------------

    public Task<IReadOnlyList<DictationEntryDto>> ListDictationEntriesAsync(CancellationToken ct = default)
        => SendAsync<IReadOnlyList<DictationEntryDto>>(HttpMethod.Get, "/api/dictation/entries", ct: ct);

    public Task<DictationEntryDto> CreateDictationEntryAsync(CreateDictationEntryRequest request, CancellationToken ct = default)
        => SendJsonAsync<CreateDictationEntryRequest, DictationEntryDto>(HttpMethod.Post, "/api/dictation/entries", request, ct: ct);

    public Task DeleteDictationEntryAsync(Guid clientEntryId, CancellationToken ct = default)
        => SendNoContentAsync(HttpMethod.Delete, $"/api/dictation/entries/{clientEntryId}", ct);

    public Task<IReadOnlyList<DictionaryWordDto>> ListDictionaryAsync(CancellationToken ct = default)
        => SendAsync<IReadOnlyList<DictionaryWordDto>>(HttpMethod.Get, "/api/dictation/dictionary", ct: ct);

    public Task<DictionaryWordDto> CreateDictionaryWordAsync(CreateDictionaryWordRequest request, CancellationToken ct = default)
        => SendJsonAsync<CreateDictionaryWordRequest, DictionaryWordDto>(HttpMethod.Post, "/api/dictation/dictionary", request, ct: ct);

    public Task DeleteDictionaryWordAsync(Guid clientWordId, CancellationToken ct = default)
        => SendNoContentAsync(HttpMethod.Delete, $"/api/dictation/dictionary/{clientWordId}", ct);

    public async Task<string> CleanupDictationAsync(string text, IReadOnlyList<string> vocabulary, CancellationToken ct = default)
    {
        var body = new { text, vocabulary };
        var json = JsonSerializer.Serialize(body, WaiJson.Options);
        using var req = new HttpRequestMessage(HttpMethod.Post, ResolveUri("/api/dictation/cleanup"))
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        };
        AttachBearer(req);
        using var resp = await _http.SendAsync(req, ct).ConfigureAwait(false);
        if (resp.StatusCode == HttpStatusCode.Unauthorized && await TryRecoverAuthAsync(ct).ConfigureAwait(false))
        {
            return await CleanupDictationAsync(text, vocabulary, ct).ConfigureAwait(false);
        }
        await EnsureSuccessAsync(resp, ct).ConfigureAwait(false);
        using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
        return doc.RootElement.GetProperty("text").GetString() ?? text;
    }

    // ----- companion ----------------------------------------------------

    public Task<CompanionConversation> CreateCompanionChatAsync(CreateCompanionChatRequest request, CancellationToken ct = default)
        => SendJsonAsync<CreateCompanionChatRequest, CompanionConversation>(HttpMethod.Post, "/api/companion/chats", request, ct: ct);

    public Task<CompanionConversationList> ListCompanionChatsAsync(int? limit = null, string? before = null, CancellationToken ct = default)
    {
        var qs = new StringBuilder("?");
        if (limit is { } l) qs.Append("limit=").Append(l).Append('&');
        if (before is not null) qs.Append("before=").Append(Uri.EscapeDataString(before)).Append('&');
        var query = qs.Length > 1 ? qs.ToString().TrimEnd('&', '?') : string.Empty;
        return SendAsync<CompanionConversationList>(HttpMethod.Get, "/api/companion/chats" + (string.IsNullOrEmpty(query) ? string.Empty : "?" + query), ct: ct);
    }

    public Task<CompanionConversation> GetCompanionChatAsync(string chatId, CancellationToken ct = default)
        => SendAsync<CompanionConversation>(HttpMethod.Get, $"/api/companion/chats/{Uri.EscapeDataString(chatId)}", ct: ct);

    public Task<CompanionConversation> PatchCompanionChatAsync(string chatId, PatchCompanionChatRequest request, CancellationToken ct = default)
        => SendJsonAsync<PatchCompanionChatRequest, CompanionConversation>(HttpMethod.Patch, $"/api/companion/chats/{Uri.EscapeDataString(chatId)}", request, ct: ct);

    public Task DeleteCompanionChatAsync(string chatId, CancellationToken ct = default)
        => SendNoContentAsync(HttpMethod.Delete, $"/api/companion/chats/{Uri.EscapeDataString(chatId)}", ct);

    public async IAsyncEnumerable<string> StreamCompanionMessageAsync(string chatId, string content, [EnumeratorCancellation] CancellationToken ct = default)
    {
        var body = new { content };
        var json = JsonSerializer.Serialize(body, WaiJson.Options);
        using var req = new HttpRequestMessage(HttpMethod.Post,
            ResolveUri($"/api/companion/chats/{Uri.EscapeDataString(chatId)}/messages"))
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        };
        req.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
        AttachBearer(req);

        using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (resp.StatusCode == HttpStatusCode.Unauthorized && await TryRecoverAuthAsync(ct).ConfigureAwait(false))
        {
            await foreach (var s in StreamCompanionMessageAsync(chatId, content, ct).ConfigureAwait(false))
            {
                yield return s;
            }
            yield break;
        }
        await EnsureSuccessAsync(resp, ct).ConfigureAwait(false);

        await using var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var reader = new StreamReader(stream, Encoding.UTF8);
        while (!reader.EndOfStream)
        {
            ct.ThrowIfCancellationRequested();
            var line = await reader.ReadLineAsync(ct).ConfigureAwait(false);
            if (line is null) continue;
            if (!line.StartsWith("data:", StringComparison.Ordinal)) continue;
            var payload = line[5..].TrimStart();
            if (payload == "[DONE]") yield break;
            yield return payload;
        }
    }

    // ----- realtime -----------------------------------------------------

    public Task<RealtimeTranscriptionSessionConfig> CreateRealtimeTranscriptionSessionAsync(
        CreateRealtimeTranscriptionSessionRequest request,
        CancellationToken ct = default)
        => SendJsonAsync<CreateRealtimeTranscriptionSessionRequest, RealtimeTranscriptionSessionConfig>(
            HttpMethod.Post, "/api/transcription/session", request, ct: ct);

    // ----- folders ------------------------------------------------------

    public Task<IReadOnlyList<Folder>> ListFoldersAsync(CancellationToken ct = default)
        => SendAsync<IReadOnlyList<Folder>>(HttpMethod.Get, "/api/folders", ct: ct);

    public Task<Folder> CreateFolderAsync(CreateFolderRequest request, CancellationToken ct = default)
        => SendJsonAsync<CreateFolderRequest, Folder>(HttpMethod.Post, "/api/folders", request, ct: ct);

    public Task<Folder> UpdateFolderAsync(string id, UpdateFolderRequest request, CancellationToken ct = default)
        => SendJsonAsync<UpdateFolderRequest, Folder>(HttpMethod.Patch, $"/api/folders/{Uri.EscapeDataString(id)}", request, ct: ct);

    public Task DeleteFolderAsync(string id, CancellationToken ct = default)
        => SendNoContentAsync(HttpMethod.Delete, $"/api/folders/{Uri.EscapeDataString(id)}", ct);

    // ----- entities -----------------------------------------------------

    public Task<IReadOnlyList<Entity>> ListEntitiesAsync(EntityType? type = null, CancellationToken ct = default)
        => SendAsync<IReadOnlyList<Entity>>(HttpMethod.Get,
            "/api/entities" + (type is { } t ? $"?type={t.ToString().ToLowerInvariant()}" : string.Empty), ct: ct);

    // ----- apps ---------------------------------------------------------

    public Task<IReadOnlyList<App>> ListAppsAsync(CancellationToken ct = default)
        => SendAsync<IReadOnlyList<App>>(HttpMethod.Get, "/api/apps", ct: ct);

    public Task<App> GetAppAsync(string id, CancellationToken ct = default)
        => SendAsync<App>(HttpMethod.Get, $"/api/apps/{Uri.EscapeDataString(id)}", ct: ct);

    public Task<IReadOnlyList<AppItem>> ListAppItemsAsync(string id, CancellationToken ct = default)
        => SendAsync<IReadOnlyList<AppItem>>(HttpMethod.Get, $"/api/apps/{Uri.EscapeDataString(id)}/items", ct: ct);

    public Task<AppStats> GetAppStatsAsync(string id, CancellationToken ct = default)
        => SendAsync<AppStats>(HttpMethod.Get, $"/api/apps/{Uri.EscapeDataString(id)}/stats", ct: ct);

    // ============== internals ==========================================

    private Uri ResolveUri(string path)
    {
        if (Uri.TryCreate(_baseUrl, path, out var resolved))
        {
            return resolved;
        }
        throw new ApiError.InvalidUrl(path);
    }

    private void AttachBearer(HttpRequestMessage request)
    {
        var token = GetAccessToken();
        if (!string.IsNullOrEmpty(token))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }
    }

    private async Task<T> SendJsonAsync<TBody, T>(HttpMethod method, string path, TBody body,
        bool authenticated = true, CancellationToken ct = default)
    {
        var json = JsonSerializer.Serialize(body, WaiJson.Options);
        using var req = new HttpRequestMessage(method, ResolveUri(path))
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        };
        if (authenticated) AttachBearer(req);
        return await ExecuteWithRefreshAsync<T>(req, retryFactory: () =>
        {
            var retry = new HttpRequestMessage(method, ResolveUri(path))
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json"),
            };
            if (authenticated) AttachBearer(retry);
            return retry;
        }, ct).ConfigureAwait(false);
    }

    private Task<T> SendAsync<T>(HttpMethod method, string path, CancellationToken ct = default)
    {
        return ExecuteWithRefreshAsync<T>(
            BuildRequest(method, path),
            () => BuildRequest(method, path),
            ct);
    }

    private async Task SendNoContentAsync(HttpMethod method, string path, CancellationToken ct = default)
    {
        var req = BuildRequest(method, path);
        try
        {
            try
            {
                using var resp = await _http.SendAsync(req, ct).ConfigureAwait(false);
                if (resp.StatusCode == HttpStatusCode.Unauthorized && await TryRecoverAuthAsync(ct).ConfigureAwait(false))
                {
                    using var retry = BuildRequest(method, path);
                    using var retryResp = await _http.SendAsync(retry, ct).ConfigureAwait(false);
                    await EnsureSuccessAsync(retryResp, ct).ConfigureAwait(false);
                    return;
                }
                await EnsureSuccessAsync(resp, ct).ConfigureAwait(false);
            }
            catch (HttpRequestException ex)
            {
                throw new ApiError.Network(ex.Message, ex);
            }
            catch (TaskCanceledException) when (!ct.IsCancellationRequested)
            {
                throw new ApiError.Network("Request timed out");
            }
        }
        finally
        {
            req.Dispose();
        }
    }

    private HttpRequestMessage BuildRequest(HttpMethod method, string path)
    {
        var req = new HttpRequestMessage(method, ResolveUri(path));
        AttachBearer(req);
        return req;
    }

    private async Task<T> ExecuteWithRefreshAsync<T>(
        HttpRequestMessage request,
        Func<HttpRequestMessage> retryFactory,
        CancellationToken ct)
    {
        try
        {
            using var resp = await _http.SendAsync(request, HttpCompletionOption.ResponseContentRead, ct).ConfigureAwait(false);
            if (resp.StatusCode == HttpStatusCode.Unauthorized && await TryRecoverAuthAsync(ct).ConfigureAwait(false))
            {
                using var retry = retryFactory();
                using var retryResp = await _http.SendAsync(retry, HttpCompletionOption.ResponseContentRead, ct).ConfigureAwait(false);
                return await ReadOrThrowAsync<T>(retryResp, ct).ConfigureAwait(false);
            }
            return await ReadOrThrowAsync<T>(resp, ct).ConfigureAwait(false);
        }
        catch (HttpRequestException ex)
        {
            throw new ApiError.Network(ex.Message, ex);
        }
        catch (TaskCanceledException) when (!ct.IsCancellationRequested)
        {
            throw new ApiError.Network("Request timed out");
        }
        finally
        {
            request.Dispose();
        }
    }

    private async Task<bool> TryRecoverAuthAsync(CancellationToken ct)
    {
        var rt = GetRefreshToken();
        if (string.IsNullOrEmpty(rt))
        {
            AuthenticationFailed?.Invoke();
            return false;
        }
        try
        {
            var refreshed = await _refresher.RefreshAsync(rt, ct).ConfigureAwait(false);
            SetAccessToken(refreshed.AccessToken);
            if (!string.IsNullOrEmpty(refreshed.RefreshToken))
            {
                SetRefreshToken(refreshed.RefreshToken);
            }
            TokenRefreshed?.Invoke(refreshed.AccessToken, refreshed.RefreshToken);
            return true;
        }
        catch
        {
            AuthenticationFailed?.Invoke();
            return false;
        }
    }

    private async Task<AuthResponse> RefreshOnceAsync(string refreshToken, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, ResolveUri("/api/auth/refresh"))
        {
            Content = new StringContent(
                JsonSerializer.Serialize(new RefreshTokenRequest(refreshToken), WaiJson.Options),
                Encoding.UTF8,
                "application/json"),
        };
        using var resp = await _http.SendAsync(req, ct).ConfigureAwait(false);
        return await ReadOrThrowAsync<AuthResponse>(resp, ct).ConfigureAwait(false);
    }

    private static async Task EnsureSuccessAsync(HttpResponseMessage resp, CancellationToken ct)
    {
        if (resp.IsSuccessStatusCode) return;
        string? message = null;
        try
        {
            using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
            if (doc.RootElement.TryGetProperty("detail", out var d) && d.ValueKind == JsonValueKind.String)
            {
                message = d.GetString();
            }
            else if (doc.RootElement.TryGetProperty("message", out var m) && m.ValueKind == JsonValueKind.String)
            {
                message = m.GetString();
            }
        }
        catch (JsonException) { /* non-JSON body, leave message null */ }

        if (resp.StatusCode == HttpStatusCode.Unauthorized)
        {
            throw new ApiError.Unauthorized();
        }
        throw new ApiError.HttpError((int)resp.StatusCode, message);
    }

    private static async Task<T> ReadOrThrowAsync<T>(HttpResponseMessage resp, CancellationToken ct)
    {
        if (resp.StatusCode == HttpStatusCode.Unauthorized)
        {
            throw new ApiError.Unauthorized();
        }
        if (!resp.IsSuccessStatusCode)
        {
            await EnsureSuccessAsync(resp, ct).ConfigureAwait(false);
        }
        try
        {
            var json = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new ApiError.NoData();
            }
            var value = JsonSerializer.Deserialize<T>(json, WaiJson.Options);
            return value ?? throw new ApiError.NoData();
        }
        catch (JsonException ex)
        {
            throw new ApiError.Decoding(ex.Message, ex);
        }
    }

    public void Dispose()
    {
        if (_ownsHttp)
        {
            _http.Dispose();
        }
    }

    private sealed class ProgressStream : Stream
    {
        private readonly Stream _inner;
        private readonly IProgress<long> _progress;
        private long _written;
        public ProgressStream(Stream inner, IProgress<long> progress) { _inner = inner; _progress = progress; }
        public override bool CanRead => _inner.CanRead;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => _inner.Length;
        public override long Position { get => _inner.Position; set => throw new NotSupportedException(); }
        public override void Flush() => _inner.Flush();
        public override int Read(byte[] buffer, int offset, int count)
        {
            var n = _inner.Read(buffer, offset, count);
            if (n > 0) { _written += n; _progress.Report(_written); }
            return n;
        }
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken ct = default)
        {
            var n = await _inner.ReadAsync(buffer, ct).ConfigureAwait(false);
            if (n > 0) { _written += n; _progress.Report(_written); }
            return n;
        }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}
