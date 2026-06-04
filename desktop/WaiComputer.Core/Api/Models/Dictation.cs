using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

/// <summary>
/// Mirrors the backend <c>DictationEntryResponse</c>
/// (backend/app/api/routes/dictation.py): client_entry_id, raw_text,
/// cleaned_text?, duration_seconds, word_count, occurred_at. The history store
/// is idempotent by (user, client_entry_id).
/// </summary>
public sealed record DictationEntryDto(
    [property: JsonPropertyName("client_entry_id")] Guid ClientEntryId,
    [property: JsonPropertyName("raw_text")] string RawText,
    [property: JsonPropertyName("cleaned_text")] string? CleanedText,
    [property: JsonPropertyName("duration_seconds")] double DurationSeconds,
    [property: JsonPropertyName("word_count")] int WordCount,
    [property: JsonPropertyName("occurred_at")] DateTimeOffset OccurredAt);

public sealed record CreateDictationEntryRequest(
    [property: JsonPropertyName("client_entry_id")] Guid ClientEntryId,
    [property: JsonPropertyName("raw_text")] string RawText,
    [property: JsonPropertyName("cleaned_text")] string? CleanedText,
    [property: JsonPropertyName("duration_seconds")] double DurationSeconds,
    [property: JsonPropertyName("word_count")] int WordCount,
    [property: JsonPropertyName("occurred_at")] DateTimeOffset OccurredAt);

/// <summary>
/// Mirrors the backend <c>DictionaryWordResponse</c>: client_word_id, word,
/// replacement?, occurred_at. Idempotent by (user, client_word_id).
/// </summary>
public sealed record DictionaryWordDto(
    [property: JsonPropertyName("client_word_id")] Guid ClientWordId,
    string Word,
    string? Replacement,
    [property: JsonPropertyName("occurred_at")] DateTimeOffset OccurredAt);

public sealed record CreateDictionaryWordRequest(
    [property: JsonPropertyName("client_word_id")] Guid ClientWordId,
    string Word,
    string? Replacement,
    [property: JsonPropertyName("occurred_at")] DateTimeOffset OccurredAt);
