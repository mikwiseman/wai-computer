using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class DeepgramSessionTests
{
    private static RealtimeTranscriptionSessionConfig Cfg() => new(
        RealtimeProvider.Deepgram,
        Token: "dg-token",
        ExpiresInSeconds: 900,
        SampleRate: 16000,
        AudioFormat: "linear16_16000",
        Language: "multi",
        Channels: 1,
        Model: "nova-3",
        KeepAliveIntervalSeconds: null,
        CommitStrategy: CommitStrategy.Vad,
        NoVerbatim: false,
        WebSocketUrl: "wss://api.deepgram.com/v1/listen?model=nova-3&encoding=linear16",
        AuthScheme: AuthScheme.Bearer);

    [Fact]
    public async Task SendsBinaryPcmFrames()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new DeepgramSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        await session.SendPcmAsync(new byte[] { 1, 2, 3 }, CancellationToken.None);

        transport.SentBinary.Should().ContainSingle().Which.Should().Equal(1, 2, 3);
    }

    [Fact]
    public async Task EndTurnSendsCloseStreamMessage()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new DeepgramSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        await session.EndTurnAsync();

        transport.SentText.Should().ContainSingle("""{"type":"CloseStream"}""");
    }

    [Fact]
    public async Task FinalResultIsCollectedWithWordTimingAndSpeaker()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new DeepgramSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""
        {"type":"Results","is_final":true,"channel":{"alternatives":[{"transcript":"hello world","confidence":0.91,"words":[{"word":"hello","start":0.1,"end":0.4,"speaker":0},{"punctuated_word":"world","start":0.5,"end":0.9,"speaker":0}]}]}}
        """);

        await Task.Delay(100);
        session.CollectedSegments.Should().ContainSingle(s =>
            s.Text == "hello world" && s.Speaker == "Speaker 0" && s.StartMs == 100 && s.EndMs == 900);
    }
}
