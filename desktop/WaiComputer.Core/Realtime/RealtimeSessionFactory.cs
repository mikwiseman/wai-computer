using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

public static class RealtimeSessionFactory
{
    public static IRealtimeTranscriptionSession Create(RealtimeTranscriptionSessionConfig config, IWebSocketTransport? transport = null)
        => config.Provider switch
        {
            RealtimeProvider.Deepgram => new DeepgramSession(config, transport),
            _ => throw new NotSupportedException($"Unknown realtime provider: {config.Provider}"),
        };

    /// <summary>
    /// A resilient session that auto-reconnects on transient drops. <paramref name="remintAsync"/>
    /// re-mints a fresh session config per reconnect (wrap
    /// <c>IApiClient.CreateRealtimeTranscriptionSessionAsync</c>) so the wrapper stays
    /// orchestrator-agnostic. Use this for the recording path.
    /// </summary>
    public static IRealtimeTranscriptionSession CreateReconnecting(
        RealtimeTranscriptionSessionConfig initialConfig,
        Func<CancellationToken, Task<RealtimeTranscriptionSessionConfig>> remintAsync,
        ReconnectOptions? options = null)
        => new ReconnectingRealtimeSession(initialConfig, cfg => Create(cfg), remintAsync, options);
}
