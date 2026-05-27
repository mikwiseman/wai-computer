using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class DeepgramSessionTests
{
    private static RealtimeTranscriptionSessionConfig Cfg() => new(
        RealtimeProvider.Deepgram,
        Token: "deepgram-temporary-token",
        ExpiresInSeconds: 60,
        SampleRate: 16000,
        AudioFormat: "linear16",
        Language: "multi",
        Channels: 1,
        Model: "nova-3",
        KeepAliveIntervalSeconds: 4,
        CommitStrategy: null,
        NoVerbatim: false,
        WebSocketUrl: "wss://wai.computer/api/transcription/stream",
        AuthScheme: AuthScheme.Bearer);

    [Fact]
    public async Task OpenConnectsToDeepgramUrlWithoutSessionUpdate()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new DeepgramSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);
        transport.ConnectedTo.Should().Be(new Uri(Cfg().WebSocketUrl!));
        transport.SentText.Should().BeEmpty();
    }

    [Fact]
    public async Task PcmIsSentAsBinaryFrame()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new DeepgramSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);
        var pcm = new byte[] { 1, 2, 3, 4 };
        await session.SendPcmAsync(pcm, CancellationToken.None);

        transport.SentBinary.Should().ContainSingle(frame => frame.SequenceEqual(pcm));
        transport.SentText.Should().BeEmpty();
    }

    [Fact]
    public async Task EndTurnSendsFinalize()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new DeepgramSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);
        await session.EndTurnAsync();
        transport.SentText.Should().Contain(s => s.Contains("\"type\":\"Finalize\""));
    }

    [Fact]
    public async Task DeepgramFinalResultsAreCollected()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new DeepgramSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""
        {"type":"Results","is_final":false,"speech_final":false,"start":0.0,"duration":0.5,"channel":{"alternatives":[{"transcript":"hello","confidence":0.91}]}}
        """);
        transport.PushText("""
        {"type":"Results","is_final":true,"speech_final":true,"start":0.0,"duration":0.9,"channel":{"alternatives":[{"transcript":"hello world","confidence":0.97}]}}
        """);

        await Task.Delay(200);
        session.CollectedSegments.Should().ContainSingle(s =>
            s.Text == "hello world"
            && s.IsFinal
            && s.StartMs == 0
            && s.EndMs == 900
            && s.Confidence == 0.97);
    }

    [Fact]
    public async Task CloseSendsCloseStream()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new DeepgramSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        await session.CloseAsync(TimeSpan.FromSeconds(1));

        transport.SentText.Should().Contain(s => s.Contains("\"type\":\"CloseStream\""));
    }
}
