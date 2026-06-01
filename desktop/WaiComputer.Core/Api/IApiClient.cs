using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Api;

/// <summary>
/// Surface of the WaiComputer REST + SSE client. Mirrors the methods on the
/// Swift <c>APIClient</c> 1:1 so the macOS reference behaviour stays in sync.
/// </summary>
public interface IApiClient
{
    // Session
    void SetAccessToken(string? token);
    void SetRefreshToken(string? token);
    string? GetAccessToken();
    string? GetRefreshToken();

    /// <summary>
    /// Invoked when a 401-triggered refresh succeeds. Persist the new pair via
    /// your SessionStore and schedule any pending recording sync.
    /// </summary>
    event Action<string, string?>? TokenRefreshed;

    /// <summary>
    /// Invoked when a 401 cannot be recovered (no refresh token, or refresh
    /// itself failed). Subscribers must clear the session and route to login.
    /// </summary>
    event Action? AuthenticationFailed;

    // Auth
    Task<AuthResponse> RegisterAsync(string email, string password, CancellationToken ct = default);
    Task<AuthResponse> LoginAsync(string email, string password, CancellationToken ct = default);
    Task<MessageResponse> RequestMagicLinkAsync(string email, string? client, CancellationToken ct = default);
    Task<AuthResponse> VerifyMagicLinkAsync(string token, CancellationToken ct = default);
    Task<User> GetCurrentUserAsync(CancellationToken ct = default);
    Task<MessageResponse> ChangePasswordAsync(string current, string next, CancellationToken ct = default);
    Task<MessageResponse> LogoutAsync(string? refreshToken, CancellationToken ct = default);
    Task<MessageResponse> DeleteAccountAsync(CancellationToken ct = default);

    // Settings
    Task<UserSettings> GetSettingsAsync(CancellationToken ct = default);
    Task<TranscriptionOptions> GetTranscriptionOptionsAsync(CancellationToken ct = default);
    Task<UserSettings> UpdateSettingsAsync(UpdateSettingsRequest request, CancellationToken ct = default);

    // Identity & Voice sharing
    Task<UserIdentity> GetIdentityAsync(CancellationToken ct = default);
    Task<UserIdentity> UpdateIdentityAsync(UpdateIdentityRequest request, CancellationToken ct = default);
    Task<VoiceSharingState> GetVoiceSharingAsync(CancellationToken ct = default);
    Task<VoiceSharingState> EnableVoiceSharingAsync(CancellationToken ct = default);
    Task<VoiceSharingState> DisableVoiceSharingAsync(CancellationToken ct = default);

    // Recordings
    Task<IReadOnlyList<Recording>> ListRecordingsAsync(int skip = 0, int limit = 50, bool? starred = null, RecordingType? type = null, string? folderId = null, bool trashed = false, CancellationToken ct = default);
    Task<BulkRecordingOperationResponse> BulkRecordingOperationAsync(BulkRecordingOperationRequest request, CancellationToken ct = default);
    Task<Recording> CreateRecordingAsync(CreateRecordingRequest request, CancellationToken ct = default);
    Task<RecordingDetail> GetRecordingAsync(string id, CancellationToken ct = default);
    Task<Recording> UpdateRecordingAsync(string id, UpdateRecordingRequest request, CancellationToken ct = default);
    Task DeleteRecordingAsync(string id, bool permanent = false, CancellationToken ct = default);
    Task<Recording> RestoreRecordingAsync(string id, CancellationToken ct = default);
    Task<RecordingShareLink> CreateRecordingShareLinkAsync(string id, CancellationToken ct = default);
    Task<IReadOnlyList<Segment>> GetTranscriptAsync(string recordingId, CancellationToken ct = default);
    Task<Recording> StarRecordingAsync(string id, CancellationToken ct = default);
    Task<Recording> UnstarRecordingAsync(string id, CancellationToken ct = default);
    Task<RecordingDetail> UploadRecordingAudioAsync(
        string recordingId,
        Stream audioStream,
        long contentLength,
        string fileName,
        string contentType,
        IProgress<long>? progress = null,
        CancellationToken ct = default);
    Task<RecordingDetail> SaveLiveTranscriptAsync(
        string recordingId,
        IReadOnlyList<LiveTranscriptSegment> segments,
        int durationSeconds,
        CancellationToken ct = default);
    Task<RecordingDetail> AssignSpeakerAsync(
        string recordingId,
        AssignSpeakerRequest request,
        CancellationToken ct = default);
    Task<RematchSpeakersResponse> RematchSpeakersAsync(string recordingId, CancellationToken ct = default);

    // People
    Task<IReadOnlyList<Person>> ListPeopleAsync(CancellationToken ct = default);
    Task<Person> CreatePersonAsync(CreatePersonRequest request, CancellationToken ct = default);
    Task<Person> UpdatePersonAsync(string id, UpdatePersonRequest request, CancellationToken ct = default);
    Task DeletePersonAsync(string id, CancellationToken ct = default);
    Task<Person> MergePersonAsync(string sourceId, MergePersonRequest request, CancellationToken ct = default);

    // Summary / export
    Task<Summary> GetSummaryAsync(string recordingId, CancellationToken ct = default);
    Task<Summary> GenerateSummaryAsync(string recordingId, CancellationToken ct = default);
    Task<string> ExportRecordingAsync(string id, string format, string? locale = null, CancellationToken ct = default);
    Task<SummaryGenerationState> GetSummaryGenerationAsync(string recordingId, CancellationToken ct = default);

    // Search
    Task<SearchResponse> SearchAsync(string query, int limit = 20, int offset = 0, CancellationToken ct = default);
    Task<SearchResponse> SemanticSearchAsync(string query, int limit = 20, double threshold = 0.3, CancellationToken ct = default);
    Task<SearchResponse> FullTextSearchAsync(string query, int limit = 20, int offset = 0, CancellationToken ct = default);

    // Action items
    Task<IReadOnlyList<ActionItem>> ListActionItemsAsync(ActionItemStatus? status = null, ActionItemPriority? priority = null, CancellationToken ct = default);
    Task<ActionItem> UpdateActionItemAsync(string id, UpdateActionItemRequest request, CancellationToken ct = default);
    Task DeleteActionItemAsync(string id, CancellationToken ct = default);

    // Dictation
    Task<IReadOnlyList<DictationEntryDto>> ListDictationEntriesAsync(CancellationToken ct = default);
    Task<DictationEntryDto> CreateDictationEntryAsync(CreateDictationEntryRequest request, CancellationToken ct = default);
    Task DeleteDictationEntryAsync(Guid clientEntryId, CancellationToken ct = default);
    Task<IReadOnlyList<DictionaryWordDto>> ListDictionaryAsync(CancellationToken ct = default);
    Task<DictionaryWordDto> CreateDictionaryWordAsync(CreateDictionaryWordRequest request, CancellationToken ct = default);
    Task DeleteDictionaryWordAsync(Guid clientWordId, CancellationToken ct = default);
    Task<string> CleanupDictationAsync(string text, IReadOnlyList<string> vocabulary, CancellationToken ct = default);

    // Companion
    Task<CompanionConversation> CreateCompanionChatAsync(CreateCompanionChatRequest request, CancellationToken ct = default);
    Task<CompanionConversationList> ListCompanionChatsAsync(int? limit = null, string? before = null, CancellationToken ct = default);
    Task<CompanionConversation> GetCompanionChatAsync(string chatId, CancellationToken ct = default);
    Task<CompanionConversation> PatchCompanionChatAsync(string chatId, PatchCompanionChatRequest request, CancellationToken ct = default);
    Task DeleteCompanionChatAsync(string chatId, CancellationToken ct = default);
    IAsyncEnumerable<string> StreamCompanionMessageAsync(string chatId, string content, CancellationToken ct = default);

    // Realtime transcription
    Task<RealtimeTranscriptionSessionConfig> CreateRealtimeTranscriptionSessionAsync(
        CreateRealtimeTranscriptionSessionRequest request,
        CancellationToken ct = default);

    // Folders
    Task<IReadOnlyList<Folder>> ListFoldersAsync(CancellationToken ct = default);
    Task<Folder> CreateFolderAsync(CreateFolderRequest request, CancellationToken ct = default);
    Task<Folder> UpdateFolderAsync(string id, UpdateFolderRequest request, CancellationToken ct = default);
    Task DeleteFolderAsync(string id, CancellationToken ct = default);

    // Entities
    Task<IReadOnlyList<Entity>> ListEntitiesAsync(EntityType? type = null, CancellationToken ct = default);

    // Apps
    Task<IReadOnlyList<App>> ListAppsAsync(CancellationToken ct = default);
    Task<App> GetAppAsync(string id, CancellationToken ct = default);
    Task<IReadOnlyList<AppItem>> ListAppItemsAsync(string id, CancellationToken ct = default);
    Task<AppStats> GetAppStatsAsync(string id, CancellationToken ct = default);
}
