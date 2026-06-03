using System;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Recordings;
using WaiComputer.Core.ViewModels;
using Xunit;

namespace WaiComputer.Core.Tests.ViewModels;

public class RecordingViewModelTests
{
    private static (RecordingViewModel vm, FakeRecordingSession session) Build()
    {
        var session = new FakeRecordingSession();
        var vm = new RecordingViewModel(session); // ImmediateUiDispatcher by default
        return (vm, session);
    }

    private static RecordingSessionState Recording(bool paused = false, int duration = 0,
        string committed = "", string interim = "", bool offline = false,
        RealtimeConnectionState connection = RealtimeConnectionState.Connected, string? error = null)
        => RecordingSessionState.Idle with
        {
            Phase = RecordingPhase.Recording,
            IsPaused = paused,
            DurationSeconds = duration,
            CommittedTranscript = committed,
            InterimTranscript = interim,
            LiveTranscriptionOffline = offline,
            ConnectionState = connection,
            Error = error,
        };

    [Fact]
    public void StateChangeUpdatesDerivedProps()
    {
        var (vm, session) = Build();

        session.Emit(Recording(duration: 12, committed: "hello world", interim: "and"));

        vm.IsRecording.Should().BeTrue();
        vm.IsIdle.Should().BeFalse();
        vm.IsActive.Should().BeTrue();
        vm.DurationSeconds.Should().Be(12);
        vm.CommittedTranscript.Should().Be("hello world");
        vm.InterimTranscript.Should().Be("and");
    }

    [Fact]
    public async Task StartCommandStartsWithSelectedOptions()
    {
        var (vm, session) = Build();
        vm.RecordingType = RecordingType.Note;
        vm.InputSource = RecordingInputSource.Microphone;
        vm.Language = "ru";
        vm.FolderId = "f1";

        await vm.StartCommand.ExecuteAsync(null);

        session.StartCount.Should().Be(1);
        session.StartedType.Should().Be(RecordingType.Note);
        session.StartedSource.Should().Be(RecordingInputSource.Microphone);
        session.StartedLanguage.Should().Be("ru");
        session.StartedFolder.Should().Be("f1");
    }

    [Fact]
    public void CommandsAreGatedByPhase()
    {
        var (vm, session) = Build();

        // Idle: only Start.
        vm.StartCommand.CanExecute(null).Should().BeTrue();
        vm.StopCommand.CanExecute(null).Should().BeFalse();
        vm.PauseResumeCommand.CanExecute(null).Should().BeFalse();
        vm.DiscardCommand.CanExecute(null).Should().BeFalse();

        // Recording: Stop/Pause/Discard, not Start.
        session.Emit(Recording());
        vm.StartCommand.CanExecute(null).Should().BeFalse();
        vm.StopCommand.CanExecute(null).Should().BeTrue();
        vm.PauseResumeCommand.CanExecute(null).Should().BeTrue();
        vm.DiscardCommand.CanExecute(null).Should().BeTrue();
    }

    [Fact]
    public async Task PauseResumeTogglesByPausedState()
    {
        var (vm, session) = Build();

        session.Emit(Recording(paused: false));
        await vm.PauseResumeCommand.ExecuteAsync(null);
        session.PauseCount.Should().Be(1);
        session.ResumeCount.Should().Be(0);

        session.Emit(Recording(paused: true));
        await vm.PauseResumeCommand.ExecuteAsync(null);
        session.ResumeCount.Should().Be(1);
    }

    [Fact]
    public async Task StopAndDiscardForwardToSession()
    {
        var (vm, session) = Build();
        session.Emit(Recording());

        await vm.StopCommand.ExecuteAsync(null);
        await vm.DiscardCommand.ExecuteAsync(null);

        session.StopCount.Should().Be(1);
        session.DiscardCount.Should().Be(1);
    }

    [Fact]
    public void ErrorSurfacesAndClearErrorForwards()
    {
        var (vm, session) = Build();

        session.Emit(RecordingSessionState.Idle with { Error = "Microphone unavailable" });

        vm.ErrorMessage.Should().Be("Microphone unavailable");
        vm.ClearErrorCommand.CanExecute(null).Should().BeTrue();

        vm.ClearErrorCommand.Execute(null);
        session.ClearErrorCount.Should().Be(1);
    }

    [Fact]
    public void OfflineAndConnectionStateReflectSnapshot()
    {
        var (vm, session) = Build();

        session.Emit(Recording(offline: true, connection: RealtimeConnectionState.Reconnecting));

        vm.LiveTranscriptionOffline.Should().BeTrue();
        vm.ConnectionState.Should().Be(RealtimeConnectionState.Reconnecting);
    }

    private sealed class FakeRecordingSession : IRecordingSession
    {
        public RecordingSessionState State { get; private set; } = RecordingSessionState.Idle;
        public event Action<RecordingSessionState>? StateChanged;

        public int StartCount { get; private set; }
        public int StopCount { get; private set; }
        public int PauseCount { get; private set; }
        public int ResumeCount { get; private set; }
        public int DiscardCount { get; private set; }
        public int ClearErrorCount { get; private set; }
        public RecordingType? StartedType { get; private set; }
        public RecordingInputSource? StartedSource { get; private set; }
        public string? StartedLanguage { get; private set; }
        public string? StartedFolder { get; private set; }

        public Task StartAsync(RecordingType type, RecordingInputSource source, string language, string? folderId, CancellationToken ct = default)
        {
            StartCount++;
            StartedType = type;
            StartedSource = source;
            StartedLanguage = language;
            StartedFolder = folderId;
            return Task.CompletedTask;
        }

        public Task StopAsync() { StopCount++; return Task.CompletedTask; }
        public Task DiscardAsync() { DiscardCount++; return Task.CompletedTask; }
        public Task PauseAsync() { PauseCount++; return Task.CompletedTask; }
        public Task ResumeAsync() { ResumeCount++; return Task.CompletedTask; }
        public void ClearError() => ClearErrorCount++;
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;

        public void Emit(RecordingSessionState snapshot)
        {
            State = snapshot;
            StateChanged?.Invoke(snapshot);
        }
    }
}
