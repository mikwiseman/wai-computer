using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

[JsonConverter(typeof(JsonStringEnumConverter<CompanionScopeKind>))]
public enum CompanionScopeKind
{
    [JsonStringEnumMemberName("all")] All,
    [JsonStringEnumMemberName("recording")] Recording,
    [JsonStringEnumMemberName("folder")] Folder,
    [JsonStringEnumMemberName("date_range")] DateRange,
}

public sealed record CompanionScope(
    CompanionScopeKind Kind,
    [property: JsonPropertyName("recording_id")] string? RecordingId,
    [property: JsonPropertyName("folder_id")] string? FolderId,
    [property: JsonPropertyName("date_from")] DateTimeOffset? DateFrom,
    [property: JsonPropertyName("date_to")] DateTimeOffset? DateTo);

public sealed record CompanionConversation(
    string Id,
    string Title,
    CompanionScope? Scope,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    IReadOnlyList<CompanionMessage> Messages);

public sealed record CompanionMessage(
    string Id,
    string Role,
    string Content,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

public sealed record CompanionConversationList(
    IReadOnlyList<CompanionConversation> Conversations,
    [property: JsonPropertyName("next_before")] string? NextBefore);

public sealed record CreateCompanionChatRequest(CompanionScope? Scope);

public sealed record PatchCompanionChatRequest(string? Title);
