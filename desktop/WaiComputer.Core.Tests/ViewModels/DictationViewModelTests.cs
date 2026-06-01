using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Dictation;
using WaiComputer.Core.Hotkey;
using WaiComputer.Core.ViewModels;
using Xunit;

namespace WaiComputer.Core.Tests.ViewModels;

public class DictationViewModelTests
{
    private static (DictationViewModel vm, FakeOrchestrator orch) Build()
    {
        var orch = new FakeOrchestrator();
        var lang = new DictationLanguageStore(new FakePrefs());
        var vm = new DictationViewModel(orch, lang); // ImmediateUiDispatcher by default
        return (vm, orch);
    }

    private static DictationResult Result(string text, bool viaClipboard)
        => new("raw", text, 1.0, WasCleaned: false, InsertedViaClipboard: viaClipboard);

    [Fact]
    public void StateChangeUpdatesDerivedFlags()
    {
        var (vm, orch) = Build();

        orch.RaiseState(DictationState.Listening);
        vm.IsListening.Should().BeTrue();
        vm.IsIdle.Should().BeFalse();
        vm.IsBusy.Should().BeFalse();

        orch.RaiseState(DictationState.Connecting);
        vm.IsBusy.Should().BeTrue();
    }

    [Fact]
    public void InterimUpdatesLiveTranscript()
    {
        var (vm, orch) = Build();
        orch.RaiseInterim("hello wor");
        vm.LiveTranscript.Should().Be("hello wor");
    }

    [Fact]
    public void CompletedSetsLastInsertedTextAndClearsLive()
    {
        var (vm, orch) = Build();
        orch.RaiseInterim("partial");

        orch.RaiseCompleted(Result("final text", viaClipboard: false));

        vm.LastInsertedText.Should().Be("final text");
        vm.LiveTranscript.Should().BeEmpty();
        vm.RecoveryNotice.Should().BeNull();
    }

    [Fact]
    public void CompletedViaClipboardSetsRecoveryNotice()
    {
        var (vm, orch) = Build();
        orch.RaiseCompleted(Result("text", viaClipboard: true));
        vm.RecoveryNotice.Should().NotBeNull();
    }

    [Fact]
    public void RecoveryEventSetsNotice()
    {
        var (vm, orch) = Build();
        orch.RaiseRecovery("clipboard text");
        vm.RecoveryNotice.Should().NotBeNull();
    }

    [Fact]
    public void FailedSetsErrorMessage()
    {
        var (vm, orch) = Build();
        orch.RaiseFailed("provider exploded");
        vm.ErrorMessage.Should().Be("provider exploded");
    }

    [Fact]
    public async Task StartCommandClearsSurfaceAndStarts()
    {
        var (vm, orch) = Build();
        orch.RaiseFailed("old error");

        await vm.StartCommand.ExecuteAsync(null);

        orch.StartCount.Should().Be(1);
        vm.ErrorMessage.Should().BeNull();
        vm.LiveTranscript.Should().BeEmpty();
    }

    [Fact]
    public void CommandsAreGatedByState()
    {
        var (vm, orch) = Build();

        // Idle: only Start is available.
        vm.StartCommand.CanExecute(null).Should().BeTrue();
        vm.StopCommand.CanExecute(null).Should().BeFalse();
        vm.CancelCommand.CanExecute(null).Should().BeFalse();

        // Listening: Stop + Cancel available, Start not.
        orch.RaiseState(DictationState.Listening);
        vm.StartCommand.CanExecute(null).Should().BeFalse();
        vm.StopCommand.CanExecute(null).Should().BeTrue();
        vm.CancelCommand.CanExecute(null).Should().BeTrue();
    }

    [Fact]
    public async Task StopAndCancelCommandsForwardToOrchestrator()
    {
        var (vm, orch) = Build();

        orch.RaiseState(DictationState.Listening);
        await vm.StopCommand.ExecuteAsync(null);
        orch.StopCount.Should().Be(1);

        orch.RaiseState(DictationState.Connecting);
        await vm.CancelCommand.ExecuteAsync(null);
        orch.CancelCount.Should().Be(1);
    }

    [Fact]
    public void ToggleLanguageInvalidatesConfigCacheAndUpdatesSelection()
    {
        var (vm, orch) = Build();

        vm.IsAutoDetectLanguage.Should().BeTrue(); // default

        vm.ToggleLanguage("ru");
        orch.ClearConfigCount.Should().Be(1); // language change drops the prefetched config
        vm.IsAutoDetectLanguage.Should().BeFalse();
        vm.SelectedLanguages.Should().Contain("ru");

        vm.SetAutoDetectLanguage();
        orch.ClearConfigCount.Should().Be(2);
        vm.IsAutoDetectLanguage.Should().BeTrue();
    }

    // ----- fakes -----------------------------------------------------------

    private sealed class FakeOrchestrator : IDictationOrchestrator
    {
        public DictationState State { get; private set; } = DictationState.Idle;
        public int StartCount { get; private set; }
        public int StopCount { get; private set; }
        public int CancelCount { get; private set; }
        public int ClearConfigCount { get; private set; }

        public event Action<DictationState>? StateChanged;
        public event Action<string>? InterimTranscriptUpdated;
        public event Action<DictationResult>? Completed;
        public event Action<string>? ClipboardRecoveryRequired;
        public event Action<string>? Failed;

        public void Attach(HotkeyStateMachine hotkey) { }
        public Task PrewarmAsync(CancellationToken ct) => Task.CompletedTask;
        public Task StartAsync(bool handsFree, CancellationToken ct = default) { StartCount++; return Task.CompletedTask; }
        public Task StartAsync(CancellationToken ct = default) { StartCount++; return Task.CompletedTask; }
        public Task StopAndInsertAsync(CancellationToken ct = default) { StopCount++; return Task.CompletedTask; }
        public Task CancelAsync(CancellationToken ct = default) { CancelCount++; return Task.CompletedTask; }
        public void ClearConfigCache() => ClearConfigCount++;
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;

        public void RaiseState(DictationState s) { State = s; StateChanged?.Invoke(s); }
        public void RaiseInterim(string t) => InterimTranscriptUpdated?.Invoke(t);
        public void RaiseCompleted(DictationResult r) => Completed?.Invoke(r);
        public void RaiseRecovery(string t) => ClipboardRecoveryRequired?.Invoke(t);
        public void RaiseFailed(string m) => Failed?.Invoke(m);
    }

    private sealed class FakePrefs : IPreferences
    {
        private readonly Dictionary<string, string> _values = new();
        public string? Get(string key) => _values.TryGetValue(key, out var v) ? v : null;
        public void Set(string key, string value) => _values[key] = value;
    }
}
