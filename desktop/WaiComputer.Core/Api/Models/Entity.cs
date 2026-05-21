using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

[JsonConverter(typeof(JsonStringEnumConverter<EntityType>))]
public enum EntityType
{
    [JsonStringEnumMemberName("recording")] Recording,
    [JsonStringEnumMemberName("folder")] Folder,
    [JsonStringEnumMemberName("person")] Person,
    [JsonStringEnumMemberName("app")] App,
}

public sealed record Entity(
    string Id,
    EntityType Type,
    string Title,
    string? Subtitle,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);
