using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class InworldSessionTests
{
    private static RealtimeTranscriptionSessionConfig Cfg() => new(
        RealtimeProvider.Inworld,
        Token: "iw-jwt",
        ExpiresInSeconds: 900,
        SampleRate: 16000,
        AudioFormat: "linear16_16000",
        Language: "multi",
        Channels: 1,
        Model: "inworld/inworld-stt-1",
        KeepAliveIntervalSeconds: null,
        CommitStrategy: CommitStrategy.Vad,
        NoVerbatim: false,
        WebSocketUrl: "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
        AuthScheme: AuthScheme.Bearer);

    [Fact]
    public async Task OpenSendsCamelCaseTranscribeConfigFirst()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new InworldSession(Cfg(), transport);

        await session.OpenAsync(CancellationToken.None);

        var payload = transport.SentText.Should().ContainSingle().Subject;
        payload.Should().Contain("\"transcribeConfig\"");
        payload.Should().Contain("\"modelId\":\"inworld/inworld-stt-1\"");
        payload.Should().Contain("\"audioEncoding\":\"LINEAR16\"");
        payload.Should().Contain("\"sampleRateHertz\":16000");
        payload.Should().Contain("\"numberOfChannels\":1");
        payload.Should().Contain("\"language\":\"\"");
        payload.Should().NotContain("transcribe_config");
    }

    [Fact]
    public async Task SendPcmUsesAudioChunkJson()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new InworldSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        await session.SendPcmAsync(new byte[] { 1, 2, 3 }, CancellationToken.None);

        transport.SentBinary.Should().BeEmpty();
        transport.SentText.Last().Should().Contain("\"audioChunk\"");
        transport.SentText.Last().Should().Contain("\"content\":\"AQID\"");
    }

    [Fact]
    public async Task CloseSendsEndTurnAndCloseStream()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new InworldSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        await session.CloseAsync(TimeSpan.FromMilliseconds(100));

        transport.SentText.Should().Contain(s => s.Contains("\"endTurn\""));
        transport.SentText.Should().Contain(s => s.Contains("\"closeStream\""));
    }

    [Fact]
    public async Task CamelCaseTranscriptionIsCollected()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new InworldSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""
        {"transcription":{"transcript":"hello world","isFinal":true,"wordTimestamps":[{"startMs":100,"endMs":900,"speaker":"Speaker 1"}],"confidence":0.92}}
        """);

        await Task.Delay(100);
        session.CollectedSegments.Should().ContainSingle(s =>
            s.Text == "hello world" && s.IsFinal && s.StartMs == 100 && s.EndMs == 900);
    }

    [Fact]
    public async Task WrappedResultTranscriptionIsCollected()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new InworldSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""
        {"result":{"transcription":{"transcript":"hello from wrapped result","isFinal":true,"wordTimestamps":[]}}}
        """);

        await Task.Delay(100);
        session.CollectedSegments.Should().ContainSingle(s =>
            s.Text == "hello from wrapped result" && s.IsFinal);
    }
}
