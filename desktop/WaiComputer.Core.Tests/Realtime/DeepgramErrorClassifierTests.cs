using System.Text.Json;
using FluentAssertions;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class DeepgramErrorClassifierTests
{
    private static JsonElement Parse(string json) => JsonDocument.Parse(json).RootElement;

    [Theory]
    [InlineData("unauthorized")]
    [InlineData("UNAUTHORIZED")]
    [InlineData("invalid_api_key")]
    [InlineData("authentication_error")]
    [InlineData("Forbidden")]
    public void AuthCodesClassifyAsFatalAuthError(string raw)
    {
        var (code, _) = DeepgramErrorClassifier.Classify(Parse($$"""{"type":"Error","err_code":"{{raw}}","description":"bad key"}"""));

        code.Should().Be(TranscriptionErrorCodes.AuthError);
        TranscriptionErrorCodes.Fatal.Should().Contain(code); // reaches the orchestrator/wrapper fatal-stop path
    }

    [Theory]
    [InlineData("insufficient_quota", "quota_exceeded")]
    [InlineData("billing_hard_limit_reached", "quota_exceeded")]
    [InlineData("rate_limit_exceeded", "rate_limited")]
    [InlineData("too_many_requests", "rate_limited")]
    public void QuotaAndRateCodesMapToTypedNonFatalCodes(string raw, string expected)
    {
        var (code, _) = DeepgramErrorClassifier.Classify(Parse($$"""{"error":"{{raw}}"}"""));

        code.Should().Be(expected);
        TranscriptionErrorCodes.Fatal.Should().NotContain(code);
    }

    [Fact]
    public void UnknownCodeDefaultsToTranscriberErrorNotGeneric()
    {
        var (code, message) = DeepgramErrorClassifier.Classify(Parse("""{"type":"Error","description":"something odd happened"}"""));

        code.Should().Be(TranscriptionErrorCodes.TranscriberError);
        message.Should().Be("something odd happened");
    }

    [Fact]
    public void MessagePrefersDescriptionThenMessageThenReason()
    {
        DeepgramErrorClassifier.Classify(Parse("""{"type":"Error","description":"D","message":"M","reason":"R"}""")).Message.Should().Be("D");
        DeepgramErrorClassifier.Classify(Parse("""{"type":"Error","message":"M","reason":"R"}""")).Message.Should().Be("M");
        DeepgramErrorClassifier.Classify(Parse("""{"type":"Error","reason":"R"}""")).Message.Should().Be("R");
    }

    [Fact]
    public void CodePrefersErrorThenErrCodeThenType()
    {
        // explicit "error" wins over "type"
        DeepgramErrorClassifier.Classify(Parse("""{"type":"Error","error":"too_many_requests"}""")).Code
            .Should().Be(TranscriptionErrorCodes.RateLimited);
        // no code fields -> falls back to "type" ("error") -> transcriber error
        DeepgramErrorClassifier.Classify(Parse("""{"type":"Error"}""")).Code
            .Should().Be(TranscriptionErrorCodes.TranscriberError);
    }
}
