using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

[JsonConverter(typeof(JsonStringEnumConverter<SummaryStyle>))]
public enum SummaryStyle
{
    [JsonStringEnumMemberName("brief")] Brief,
    [JsonStringEnumMemberName("medium")] Medium,
    [JsonStringEnumMemberName("detailed")] Detailed,
}

public sealed record UserSettings(
    [property: JsonPropertyName("default_language")] string DefaultLanguage,
    [property: JsonPropertyName("summary_language")] string SummaryLanguage,
    [property: JsonPropertyName("summary_style")] SummaryStyle SummaryStyle,
    [property: JsonPropertyName("dictation_live_stt_provider")] string DictationLiveSttProvider,
    [property: JsonPropertyName("dictation_live_stt_model")] string DictationLiveSttModel,
    [property: JsonPropertyName("recording_live_stt_provider")] string RecordingLiveSttProvider,
    [property: JsonPropertyName("recording_live_stt_model")] string RecordingLiveSttModel,
    [property: JsonPropertyName("file_stt_provider")] string FileSttProvider,
    [property: JsonPropertyName("file_stt_model")] string FileSttModel,
    [property: JsonPropertyName("dictation_post_filter_enabled")] bool DictationPostFilterEnabled,
    [property: JsonPropertyName("dictation_post_filter_provider")] string? DictationPostFilterProvider,
    [property: JsonPropertyName("dictation_post_filter_model")] string? DictationPostFilterModel);

public sealed record UpdateSettingsRequest(
    [property: JsonPropertyName("default_language")] string? DefaultLanguage = null,
    [property: JsonPropertyName("summary_language")] string? SummaryLanguage = null,
    [property: JsonPropertyName("summary_style")] SummaryStyle? SummaryStyle = null,
    [property: JsonPropertyName("dictation_live_stt_provider")] string? DictationLiveSttProvider = null,
    [property: JsonPropertyName("dictation_live_stt_model")] string? DictationLiveSttModel = null,
    [property: JsonPropertyName("recording_live_stt_provider")] string? RecordingLiveSttProvider = null,
    [property: JsonPropertyName("recording_live_stt_model")] string? RecordingLiveSttModel = null,
    [property: JsonPropertyName("file_stt_provider")] string? FileSttProvider = null,
    [property: JsonPropertyName("file_stt_model")] string? FileSttModel = null,
    [property: JsonPropertyName("dictation_post_filter_enabled")] bool? DictationPostFilterEnabled = null,
    [property: JsonPropertyName("dictation_post_filter_provider")] string? DictationPostFilterProvider = null,
    [property: JsonPropertyName("dictation_post_filter_model")] string? DictationPostFilterModel = null);

public sealed record TranscriptionProviderOption(string Provider, string Model);

public sealed record TranscriptionOptions(
    [property: JsonPropertyName("dictation_live_stt")] IReadOnlyList<TranscriptionProviderOption> DictationLiveStt,
    [property: JsonPropertyName("recording_live_stt")] IReadOnlyList<TranscriptionProviderOption> RecordingLiveStt,
    [property: JsonPropertyName("file_stt")] IReadOnlyList<TranscriptionProviderOption> FileStt,
    [property: JsonPropertyName("post_filter")] IReadOnlyList<TranscriptionProviderOption> PostFilter);
