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
}
