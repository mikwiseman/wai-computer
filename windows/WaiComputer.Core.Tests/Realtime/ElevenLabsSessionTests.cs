using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class ElevenLabsSessionTests
{
    private static RealtimeTranscriptionSessionConfig Cfg() => new(
        RealtimeProvider.ElevenLabs,
        Token: "tok-abc",
        ExpiresInSeconds: 900,
        SampleRate: 16000,
        AudioFormat: "pcm_16000",
        Language: "multi",
        Channels: 1,
        Model: "scribe-realtime",
        KeepAliveIntervalSeconds: null,
        CommitStrategy: null,
        NoVerbatim: false,
        WebSocketUrl: null,
        AuthScheme: AuthScheme.QueryToken);

    [Fact]
    public async Task ConnectUrlIncludesModelAndToken()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new ElevenLabsSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.ConnectedTo!.AbsoluteUri.Should().Contain("model_id=scribe-realtime");
        transport.ConnectedTo!.AbsoluteUri.Should().Contain("token=tok-abc");
        transport.ConnectedTo!.AbsoluteUri.Should().Contain("audio_format=pcm_16000");
    }

    [Fact]
    public async Task SendsBinaryFramesForPcm()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new ElevenLabsSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        var pcm = new byte[1600 * 2];
        await session.SendPcmAsync(pcm, CancellationToken.None);

        transport.SentBinary.Should().ContainSingle().Which.Length.Should().Be(pcm.Length);
    }

    [Fact]
    public async Task PartialTranscriptEmitsNonFinalSegment()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new ElevenLabsSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""{"message_type":"partial_transcript","text":"hello","start_ms":0,"end_ms":500,"confidence":0.7}""");

        await using var enumerator = session.Events.GetAsyncEnumerator();
        await enumerator.MoveNextAsync();
        enumerator.Current.Should().BeOfType<TranscriptionEvent.Connected>();
        await enumerator.MoveNextAsync();
        var ev = enumerator.Current.Should().BeOfType<TranscriptionEvent.Transcript>().Subject;
        ev.Segment.Text.Should().Be("hello");
        ev.Segment.IsFinal.Should().BeFalse();
    }

    [Fact]
    public async Task CommittedTranscriptIsCollected()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new ElevenLabsSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""{"message_type":"committed_transcript_with_timestamps","text":"hello world","start_ms":0,"end_ms":1500,"confidence":0.9}""");

        await Task.Delay(100); // let the read loop pump
        session.CollectedSegments.Should().ContainSingle(s => s.IsFinal && s.Text == "hello world");
    }

    [Fact]
    public async Task ErrorMessageBecomesProviderWarning()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new ElevenLabsSession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""{"message_type":"error","error":"quota_exceeded","message":"Monthly limit reached"}""");

        await Task.Delay(50);
        var collected = new List<TranscriptionEvent>();
        await foreach (var e in session.Events.WithCancellation(new CancellationTokenSource(TimeSpan.FromMilliseconds(200)).Token).ConfigureAwait(false))
        {
            collected.Add(e);
            if (e is TranscriptionEvent.ProviderWarning) break;
        }
        collected.OfType<TranscriptionEvent.ProviderWarning>().Should().ContainSingle()
            .Which.Code.Should().Be("quota_exceeded");
    }
}
