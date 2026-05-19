using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class SonioxSessionTests
{
    private static RealtimeTranscriptionSessionConfig Cfg() => new(
        RealtimeProvider.Soniox,
        Token: "soniox-temp-key",
        ExpiresInSeconds: 600,
        SampleRate: 16000,
        AudioFormat: "pcm_s16le_16000",
        Language: "multi",
        Channels: 1,
        Model: "stt-rt-v4",
        KeepAliveIntervalSeconds: null,
        CommitStrategy: CommitStrategy.Vad,
        NoVerbatim: false,
        WebSocketUrl: "wss://stt-rt.soniox.com/transcribe-websocket",
        AuthScheme: AuthScheme.MessageApiKey);

    [Fact]
    public async Task OpenSendsTemporaryKeyConfigFirst()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new SonioxSession(Cfg(), transport);

        await session.OpenAsync(CancellationToken.None);

        transport.ConnectedTo!.AbsoluteUri.Should().Be("wss://stt-rt.soniox.com/transcribe-websocket");
        var payload = transport.SentText.Should().ContainSingle().Subject;
        payload.Should().Contain("\"api_key\":\"soniox-temp-key\"");
        payload.Should().Contain("\"model\":\"stt-rt-v4\"");
        payload.Should().Contain("\"audio_format\":\"pcm_s16le\"");
        payload.Should().Contain("\"sample_rate\":16000");
        payload.Should().Contain("\"num_channels\":1");
        transport.ConnectedTo!.Query.Should().NotContain("soniox-temp-key");
    }

    [Fact]
    public async Task SendsBinaryPcmFrames()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new SonioxSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        await session.SendPcmAsync(new byte[] { 1, 2, 3 }, CancellationToken.None);

        transport.SentBinary.Should().ContainSingle().Which.Should().Equal(1, 2, 3);
    }

    [Fact]
    public async Task EndTurnSendsSilenceAndFinalize()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new SonioxSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        await session.EndTurnAsync();

        transport.SentBinary.Should().ContainSingle().Which.Length.Should().Be(6400);
        transport.SentText.Should().Contain("""{"type":"finalize"}""");
    }

    [Fact]
    public async Task FinalTokensAreCollected()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new SonioxSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""
        {"tokens":[{"text":"hello ","is_final":true,"start_ms":100,"end_ms":400,"speaker":"Speaker 0","confidence":0.9},{"text":"world","is_final":true,"start_ms":500,"end_ms":900,"speaker":"Speaker 0","confidence":0.92},{"text":"<fin>","is_final":true,"start_ms":900,"end_ms":900,"speaker":"Speaker 0","confidence":1.0}]}
        """);

        await Task.Delay(100);
        session.CollectedSegments.Should().ContainSingle(s =>
            s.Text == "hello world" && s.IsFinal && s.Speaker == "Speaker 0" && s.StartMs == 100 && s.EndMs == 900);
    }
}
