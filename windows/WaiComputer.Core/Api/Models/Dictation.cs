using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

public sealed record DictationEntryDto(
    [property: JsonPropertyName("client_entry_id")] Guid ClientEntryId,
    string Text,
    string Language,
    [property: JsonPropertyName("target_app_bundle_id")] string? TargetAppBundleId,
    [property: JsonPropertyName("target_app_name")] string? TargetAppName,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

public sealed record CreateDictationEntryRequest(
    [property: JsonPropertyName("client_entry_id")] Guid ClientEntryId,
    string Text,
    string Language,
    [property: JsonPropertyName("target_app_bundle_id")] string? TargetAppBundleId,
    [property: JsonPropertyName("target_app_name")] string? TargetAppName);

public sealed record DictionaryWordDto(
    [property: JsonPropertyName("client_word_id")] Guid ClientWordId,
    string Word,
    string Replacement,
    [property: JsonPropertyName("case_sensitive")] bool CaseSensitive,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

public sealed record CreateDictionaryWordRequest(
    [property: JsonPropertyName("client_word_id")] Guid ClientWordId,
    string Word,
    string Replacement,
    [property: JsonPropertyName("case_sensitive")] bool CaseSensitive);
