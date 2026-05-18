using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

public sealed record Person(
    string Id,
    [property: JsonPropertyName("display_name")] string DisplayName,
    string? Color,
    IReadOnlyList<string>? Aliases,
    [property: JsonPropertyName("voiceprint_count")] int VoiceprintCount,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);

public sealed record CreatePersonRequest(
    [property: JsonPropertyName("display_name")] string DisplayName,
    string? Color,
    IReadOnlyList<string>? Aliases);

public sealed record UpdatePersonRequest(
    [property: JsonPropertyName("display_name")] string? DisplayName,
    string? Color,
    IReadOnlyList<string>? Aliases);

public sealed record MergePersonRequest(
    [property: JsonPropertyName("into_person_id")] string IntoPersonId);
