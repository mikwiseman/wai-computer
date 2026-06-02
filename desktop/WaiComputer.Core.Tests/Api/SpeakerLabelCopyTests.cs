using FluentAssertions;
using WaiComputer.Core.Api.Models;
using Xunit;

namespace WaiComputer.Core.Tests.Api;

public class SpeakerLabelCopyTests
{
    [Theory]
    [InlineData("You", "ru", "Ты")]
    [InlineData("You", "en", "You")]
    [InlineData("you", "en", "You")]
    [InlineData("Speaker", "ru", "Говорящий")]
    [InlineData("Speaker", "en", "Speaker")]
    [InlineData("Speaker 1", "ru", "Говорящий 1")]
    [InlineData("Speaker 1", "en", "Speaker 1")]
    [InlineData("speaker_0", "ru", "Говорящий 0")]
    [InlineData("speaker_0", "en", "Speaker 0")]
    [InlineData("speaker-2", "en", "Speaker 2")]
    [InlineData("Оля", "ru", "Оля")]
    [InlineData("Mik", "en", "Mik")]
    public void RendersLocalizedLabel(string raw, string lang, string expected)
        => SpeakerLabelCopy.UserFacingLabel(raw, lang).Should().Be(expected);

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void ReturnsNullForBlank(string? raw)
        => SpeakerLabelCopy.UserFacingLabel(raw, "en").Should().BeNull();

    [Fact]
    public void RussianMatchedByLanguageRegionTag()
        => SpeakerLabelCopy.UserFacingLabel("speaker_3", "ru-RU").Should().Be("Говорящий 3");

    [Fact]
    public void NullLanguageDefaultsToEnglish()
        => SpeakerLabelCopy.UserFacingLabel("speaker_1", null).Should().Be("Speaker 1");
}
