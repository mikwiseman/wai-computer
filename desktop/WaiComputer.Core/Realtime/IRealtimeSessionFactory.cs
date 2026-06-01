using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Injectable wrapper over <see cref="RealtimeSessionFactory"/> so orchestrators
/// (dictation, recording) can have a fake session substituted in tests.
/// </summary>
public interface IRealtimeSessionFactory
{
    IRealtimeTranscriptionSession Create(RealtimeTranscriptionSessionConfig config);
}

/// <summary>Production factory — delegates to <see cref="RealtimeSessionFactory.Create"/>.</summary>
public sealed class DefaultRealtimeSessionFactory : IRealtimeSessionFactory
{
    public IRealtimeTranscriptionSession Create(RealtimeTranscriptionSessionConfig config)
        => RealtimeSessionFactory.Create(config);
}
