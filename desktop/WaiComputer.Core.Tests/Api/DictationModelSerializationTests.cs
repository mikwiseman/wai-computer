using System;
using System.Text.Json;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using Xunit;

namespace WaiComputer.Core.Tests.Api;

public class DictationModelSerializationTests
{
    [Fact]
    public void DictationEntryDeserializesBackendShape()
    {
        const string body = """
        {
          "client_entry_id": "11111111-1111-1111-1111-111111111111",
          "raw_text": "hello world",
          "cleaned_text": null,
          "duration_seconds": 3.5,
          "word_count": 2,
          "occurred_at": "2026-05-18T14:30:45Z"
        }
        """;
        var e = JsonSerializer.Deserialize<DictationEntryDto>(body, WaiJson.Options)!;
        e.ClientEntryId.Should().Be(Guid.Parse("11111111-1111-1111-1111-111111111111"));
        e.RawText.Should().Be("hello world");
        e.CleanedText.Should().BeNull();
        e.DurationSeconds.Should().Be(3.5);
        e.WordCount.Should().Be(2);
        e.OccurredAt.Should().Be(new DateTimeOffset(2026, 5, 18, 14, 30, 45, TimeSpan.Zero));
    }

    [Fact]
    public void CreateDictationEntrySerializesBackendShape()
    {
        var req = new CreateDictationEntryRequest(
            Guid.Parse("22222222-2222-2222-2222-222222222222"),
            RawText: "raw", CleanedText: "clean", DurationSeconds: 1.5, WordCount: 1,
            OccurredAt: new DateTimeOffset(2026, 5, 18, 14, 30, 45, TimeSpan.Zero));
        var json = JsonSerializer.Serialize(req, WaiJson.Options);
        json.Should().Contain("\"client_entry_id\":\"22222222-2222-2222-2222-222222222222\"");
        json.Should().Contain("\"raw_text\":\"raw\"");
        json.Should().Contain("\"cleaned_text\":\"clean\"");
        json.Should().Contain("\"duration_seconds\":1.5");
        json.Should().Contain("\"word_count\":1");
        json.Should().Contain("\"occurred_at\":");
        json.Should().NotContain("language");
        json.Should().NotContain("target_app");
    }

    [Fact]
    public void DictionaryWordRoundTripsBackendShape()
    {
        const string body = """
        {
          "client_word_id": "33333333-3333-3333-3333-333333333333",
          "word": "WaiComputer",
          "replacement": null,
          "occurred_at": "2026-05-18T14:30:45Z"
        }
        """;
        var w = JsonSerializer.Deserialize<DictionaryWordDto>(body, WaiJson.Options)!;
        w.ClientWordId.Should().Be(Guid.Parse("33333333-3333-3333-3333-333333333333"));
        w.Word.Should().Be("WaiComputer");
        w.Replacement.Should().BeNull();
        w.OccurredAt.Should().Be(new DateTimeOffset(2026, 5, 18, 14, 30, 45, TimeSpan.Zero));

        var create = new CreateDictionaryWordRequest(w.ClientWordId, "term", "replacement", w.OccurredAt);
        var json = JsonSerializer.Serialize(create, WaiJson.Options);
        json.Should().Contain("\"client_word_id\":");
        json.Should().Contain("\"replacement\":\"replacement\"");
        json.Should().NotContain("case_sensitive");
    }
}
