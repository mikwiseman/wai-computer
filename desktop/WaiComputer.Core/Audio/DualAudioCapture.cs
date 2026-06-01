using System.Threading.Channels;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace WaiComputer.Core.Audio;

/// <summary>
/// Combines a microphone and an optional system-audio source into a single
/// stream consumed by the realtime WS + local WAV writer. Direct port of the
/// Swift <c>DualAudioCapture</c> behavioural contract: each source feeds a
/// <see cref="BufferedDualMixer"/> that aligns the two on a fixed flush cadence,
/// so the mic is never blocked by missing / jittery system audio, output stays
/// sample-accurate, and a stalled system source degrades to mic-only.
/// </summary>
public sealed class DualAudioCapture : IAsyncDisposable
{
    private readonly IMicrophoneCapture _mic;
    private readonly ISystemAudioCapture? _system;
    private readonly AudioCaptureConfig _config;
    private readonly ILogger<DualAudioCapture> _logger;
    private readonly IFlushClock _flushClock;
    private readonly TimeSpan _stallTimeout = TimeSpan.FromSeconds(3);

    private readonly BufferedDualMixer _mixer;
    private readonly object _mixerGate = new();

    private readonly Channel<AudioFrame> _output = Channel.CreateBounded<AudioFrame>(
        new BoundedChannelOptions(64)
        {
            FullMode = BoundedChannelFullMode.DropOldest,
            SingleReader = true,
            SingleWriter = false,
        });

    private Task? _micPump;
    private Task? _systemPump;
    private Task? _stallPump;
    private Task? _flushPump;
    private CancellationTokenSource? _cts;

    public ChannelReader<AudioFrame> Frames => _output.Reader;
    public bool HasSystemAudio => _system is not null;
    public bool SystemAudioStalled { get; private set; }
    public bool SystemAudioReceivedAny => _system?.HasReceivedAudio == true;
    public DateTimeOffset? LastAudibleSystemAudioAt => _system?.LastAudibleAt;

    public event Action? SystemAudioStallDetected;

    public DualAudioCapture(
        IMicrophoneCapture mic,
        ISystemAudioCapture? system,
        AudioCaptureConfig config,
        ILogger<DualAudioCapture>? logger = null,
        IFlushClock? flushClock = null)
    {
        _mic = mic;
        _system = system;
        _config = config;
        _logger = logger ?? NullLogger<DualAudioCapture>.Instance;
        _flushClock = flushClock ?? new PeriodicFlushClock(TimeSpan.FromMilliseconds(160));
        _mixer = new BufferedDualMixer(config);
    }

    public async Task StartAsync(CancellationToken ct)
    {
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);

        await _mic.StartAsync(_cts.Token).ConfigureAwait(false);
        if (_system is not null)
        {
            try { await _system.StartAsync(_cts.Token).ConfigureAwait(false); }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "System audio capture failed to start; falling back to mic-only");
            }
        }

        _micPump = Task.Run(() => MicPump(_cts.Token), _cts.Token);
        if (_system is not null)
        {
            _systemPump = Task.Run(() => SystemReadPump(_cts.Token), _cts.Token);
            _stallPump = Task.Run(() => StallPump(_cts.Token), _cts.Token);
        }
        _flushPump = Task.Run(() => FlushPump(_cts.Token), _cts.Token);
    }

    public async Task StopAsync()
    {
        _cts?.Cancel();
        try { await _mic.StopAsync().ConfigureAwait(false); } catch { /* ignore */ }
        if (_system is not null)
        {
            try { await _system.StopAsync().ConfigureAwait(false); } catch { /* ignore */ }
        }

        foreach (var pump in new[] { _micPump, _systemPump, _stallPump, _flushPump })
        {
            if (pump is not null)
            {
                try { await pump.ConfigureAwait(false); } catch { /* cancelled */ }
            }
        }

        DrainFlush(); // emit any remaining aligned audio
        _output.Writer.TryComplete();
    }

    public async ValueTask DisposeAsync()
    {
        try { await StopAsync().ConfigureAwait(false); } catch { /* ignore */ }
        _cts?.Dispose();
        await _mic.DisposeAsync().ConfigureAwait(false);
        if (_system is not null) await _system.DisposeAsync().ConfigureAwait(false);
    }

    private async Task MicPump(CancellationToken ct)
    {
        try
        {
            await foreach (var frame in _mic.Frames.ReadAllAsync(ct).ConfigureAwait(false))
            {
                lock (_mixerGate) { _mixer.AppendMic(frame.Pcm16); }
            }
        }
        catch (OperationCanceledException) { /* stopping */ }
    }

    private async Task SystemReadPump(CancellationToken ct)
    {
        if (_system is null) return;
        try
        {
            await foreach (var frame in _system.Frames.ReadAllAsync(ct).ConfigureAwait(false))
            {
                lock (_mixerGate) { _mixer.AppendSystem(frame.Pcm16); }
            }
        }
        catch (OperationCanceledException) { /* stopping */ }
    }

    private async Task StallPump(CancellationToken ct)
    {
        if (_system is null) return;
        while (!ct.IsCancellationRequested)
        {
            try { await Task.Delay(_stallTimeout, ct).ConfigureAwait(false); }
            catch (OperationCanceledException) { return; }

            var lastAt = _system.LastAudibleAt;
            var stalled = lastAt is null || DateTimeOffset.UtcNow - lastAt > _stallTimeout;
            if (stalled && !SystemAudioStalled)
            {
                SystemAudioStalled = true;
                _logger.LogWarning("System audio stalled — no audible frames in {Timeout}", _stallTimeout);
                SystemAudioStallDetected?.Invoke();
            }
            else if (!stalled && SystemAudioStalled)
            {
                SystemAudioStalled = false;
            }
        }
    }

    private async Task FlushPump(CancellationToken ct)
    {
        try
        {
            await foreach (var _ in _flushClock.Ticks(ct).ConfigureAwait(false))
            {
                DrainFlush();
            }
        }
        catch (OperationCanceledException) { /* stopping */ }
    }

    private void DrainFlush()
    {
        var systemUsable = SystemAudioReceivedAny && !SystemAudioStalled;
        while (true)
        {
            AudioFrame? frame;
            lock (_mixerGate) { frame = _mixer.TryFlush(HasSystemAudio, systemUsable); }
            if (frame is null)
            {
                break;
            }
            _output.Writer.TryWrite(frame.Value);
        }
    }
}
