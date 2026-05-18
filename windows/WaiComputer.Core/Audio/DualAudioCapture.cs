using System.Threading.Channels;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace WaiComputer.Core.Audio;

/// <summary>
/// Combines a microphone and an optional system-audio source into a single
/// stream consumed by the realtime WS + local WAV writer. Direct port of the
/// Swift <c>DualAudioCapture</c> behavioural contract: stall detection,
/// graceful degradation to mic-only, mono/stereo configuration.
/// </summary>
public sealed class DualAudioCapture : IAsyncDisposable
{
    private readonly IMicrophoneCapture _mic;
    private readonly ISystemAudioCapture? _system;
    private readonly AudioCaptureConfig _config;
    private readonly ILogger<DualAudioCapture> _logger;
    private readonly TimeSpan _stallTimeout = TimeSpan.FromSeconds(3);
    private static readonly short AudibilityThreshold = 32;

    private readonly Channel<AudioFrame> _output = Channel.CreateBounded<AudioFrame>(
        new BoundedChannelOptions(64)
        {
            FullMode = BoundedChannelFullMode.DropOldest,
            SingleReader = true,
            SingleWriter = false,
        });

    private Task? _micPump;
    private Task? _systemPump;
    private CancellationTokenSource? _cts;

    public ChannelReader<AudioFrame> Frames => _output.Reader;
    public bool HasSystemAudio => _system is not null;
    public bool SystemAudioStalled { get; private set; }
    public bool SystemAudioReceivedAny => _system?.HasReceivedAudio == true;
    public DateTimeOffset? LastAudibleSystemAudioAt => _system?.LastAudibleAt;

    public event Action? SystemAudioStallDetected;

    public DualAudioCapture(IMicrophoneCapture mic, ISystemAudioCapture? system, AudioCaptureConfig config, ILogger<DualAudioCapture>? logger = null)
    {
        _mic = mic;
        _system = system;
        _config = config;
        _logger = logger ?? NullLogger<DualAudioCapture>.Instance;
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
            _systemPump = Task.Run(() => SystemPump(_cts.Token), _cts.Token);
        }
    }

    public async Task StopAsync()
    {
        _cts?.Cancel();
        try { await _mic.StopAsync().ConfigureAwait(false); } catch { /* ignore */ }
        if (_system is not null)
        {
            try { await _system.StopAsync().ConfigureAwait(false); } catch { /* ignore */ }
        }
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
        await foreach (var micFrame in _mic.Frames.ReadAllAsync(ct).ConfigureAwait(false))
        {
            if (_system is null)
            {
                await _output.Writer.WriteAsync(micFrame, ct).ConfigureAwait(false);
                continue;
            }

            // We mix synchronously per-mic-frame: read the most recent system
            // frame if available, otherwise emit silence-padded mic only. This
            // matches the Swift implementation's "stall detection" path —
            // missing system audio doesn't block recording.
            if (_system.Frames.TryRead(out var sysFrame) && sysFrame.SampleCount == micFrame.SampleCount)
            {
                EmitMixed(micFrame, sysFrame, ct);
            }
            else
            {
                EmitMixed(micFrame, new AudioFrame(new byte[micFrame.SizeBytes], micFrame.Timestamp, micFrame.SampleCount), ct);
            }
        }
    }

    private async Task SystemPump(CancellationToken ct)
    {
        if (_system is null) return;
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(_stallTimeout, ct).ConfigureAwait(false);
            }
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

    private void EmitMixed(AudioFrame mic, AudioFrame system, CancellationToken ct)
    {
        if (_config.SeparateChannels)
        {
            var dst = new byte[mic.SizeBytes * 2];
            AudioMixer.InterleaveStereo(mic.Pcm16, system.Pcm16, dst);
            _ = _output.Writer.TryWrite(new AudioFrame(dst, mic.Timestamp, mic.SampleCount));
        }
        else
        {
            var dst = new byte[mic.SizeBytes];
            AudioMixer.MixToMono(mic.Pcm16, system.Pcm16, dst);
            _ = _output.Writer.TryWrite(new AudioFrame(dst, mic.Timestamp, mic.SampleCount));
        }
    }
}
