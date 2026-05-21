using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

public sealed record App(
    string Id,
    string Name,
    string? Description,
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("item_count")] int ItemCount);

public sealed record AppItem(
    string Id,
    [property: JsonPropertyName("app_id")] string AppId,
    System.Text.Json.JsonElement Data,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);

public sealed record AppStats(
    [property: JsonPropertyName("item_count")] int ItemCount,
    [property: JsonPropertyName("last_item_at")] DateTimeOffset? LastItemAt);
