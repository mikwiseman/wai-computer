using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class OpenAISessionTests
{
    private static RealtimeTranscriptionSessionConfig Cfg() => new(
        RealtimeProvider.OpenAi,
        Token: "sk-test",
        ExpiresInSeconds: 3600,
        SampleRate: 24000,
        AudioFormat: "pcm_24000",
        Language: "multi",
        Channels: 1,
        Model: "gpt-realtime-whisper",
        KeepAliveIntervalSeconds: null,
        CommitStrategy: CommitStrategy.Manual,
        NoVerbatim: false,
        WebSocketUrl: "wss://api.openai.test/v1/realtime",
        AuthScheme: AuthScheme.Bearer);

    [Fact]
    public async Task SessionUpdateSentOnOpen()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new OpenAISession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);
        transport.SentText.Should().ContainSingle(s =>
            s.Contains("\"type\":\"session.update\"")
            && s.Contains("\"type\":\"transcription\"")
            && s.Contains("\"model\":\"gpt-realtime-whisper\""));
    }

    [Fact]
    public async Task PcmIsBase64Encoded()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new OpenAISession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);
        var pcm = new byte[] { 1, 2, 3, 4 };
        await session.SendPcmAsync(pcm, CancellationToken.None);

        var payload = transport.SentText.Last();
        payload.Should().Contain("\"type\":\"input_audio_buffer.append\"");
        payload.Should().Contain(Convert.ToBase64String(pcm));
    }

    [Fact]
    public async Task EndTurnSendsCommit()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new OpenAISession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);
        await session.EndTurnAsync();
        transport.SentText.Should().Contain(s => s.Contains("input_audio_buffer.commit"));
    }

    [Fact]
    public async Task DeltasConcatenateUntilCompleted()
    {
        var transport = new FakeWebSocketTransport();
        await using var session = new OpenAISession(Cfg(), transport);
        await session.OpenAsync(CancellationToken.None);

        transport.PushText("""{"type":"conversation.item.input_audio_transcription.delta","item_id":"i1","delta":"hello "}""");
        transport.PushText("""{"type":"conversation.item.input_audio_transcription.delta","item_id":"i1","delta":"world"}""");
        transport.PushText("""{"type":"conversation.item.input_audio_transcription.completed","item_id":"i1","transcript":"hello world"}""");

        await Task.Delay(200);
        session.CollectedSegments.Should().ContainSingle(s => s.Text == "hello world" && s.IsFinal);
    }
}
