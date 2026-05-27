using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

[JsonConverter(typeof(JsonStringEnumConverter<RealtimeProvider>))]
public enum RealtimeProvider
{
    [JsonStringEnumMemberName("deepgram")] Deepgram,
}

[JsonConverter(typeof(JsonStringEnumConverter<AuthScheme>))]
public enum AuthScheme
{
    [JsonStringEnumMemberName("bearer")] Bearer,
}

[JsonConverter(typeof(JsonStringEnumConverter<CommitStrategy>))]
public enum CommitStrategy
{
    [JsonStringEnumMemberName("manual")] Manual,
    [JsonStringEnumMemberName("vad")] Vad,
}

public sealed record CreateRealtimeTranscriptionSessionRequest(
    string Language,
    int Channels,
    string Purpose);

public sealed record RealtimeTranscriptionSessionConfig(
    RealtimeProvider Provider,
    string Token,
    [property: JsonPropertyName("expires_in_seconds")] int ExpiresInSeconds,
    [property: JsonPropertyName("sample_rate")] int SampleRate,
    [property: JsonPropertyName("audio_format")] string AudioFormat,
    string Language,
    int Channels,
    string Model,
    [property: JsonPropertyName("keep_alive_interval_seconds")] int? KeepAliveIntervalSeconds,
    [property: JsonPropertyName("commit_strategy")] CommitStrategy? CommitStrategy,
    [property: JsonPropertyName("no_verbatim")] bool NoVerbatim,
    [property: JsonPropertyName("websocket_url")] string? WebSocketUrl,
    [property: JsonPropertyName("auth_scheme")] AuthScheme AuthScheme);
