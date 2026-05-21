using System.Diagnostics;
using System.Threading.Channels;
using WaiComputer.Core.Audio;

namespace WaiComputer.Linux.Audio;

public abstract class ProcessPcmCapture : IAudioCapture
{
    private readonly string _deviceName;
    private readonly int _sampleRate;
    private readonly int _frameSizeSamples;
    private readonly int _frameSizeBytes;
    private readonly Channel<AudioFrame> _frames = Channel.CreateBounded<AudioFrame>(
        new BoundedChannelOptions(64) { FullMode = BoundedChannelFullMode.DropOldest, SingleReader = true });

    private Process? _process;
    private Task? _pump;
    private CancellationTokenSource? _cts;

    protected ProcessPcmCapture(string deviceName, int sampleRate, int frameSizeSamples)
    {
        _deviceName = deviceName;
        _sampleRate = sampleRate;
        _frameSizeSamples = frameSizeSamples;
        _frameSizeBytes = frameSizeSamples * 2;
    }

    public string DeviceName => _deviceName;
    public abstract AudioSource Source { get; }
    public bool IsCapturing => _process is { HasExited: false };
    public bool HasReceivedAudio { get; private set; }
    public DateTimeOffset? LastAudibleAt { get; private set; }
    public ChannelReader<AudioFrame> Frames => _frames.Reader;

    public Task StartAsync(CancellationToken ct)
    {
        if (_process is not null)
        {
            throw new InvalidOperationException("Capture is already running.");
        }

        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var startInfo = new ProcessStartInfo("parec")
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        startInfo.ArgumentList.Add("--raw");
        startInfo.ArgumentList.Add("--format=s16le");
        startInfo.ArgumentList.Add($"--rate={_sampleRate}");
        startInfo.ArgumentList.Add("--channels=1");
        startInfo.ArgumentList.Add($"--device={_deviceName}");

        _process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("Failed to start parec for Linux audio capture.");

        _pump = Task.Run(() => ReadLoopAsync(_process, _cts.Token), _cts.Token);
        return Task.CompletedTask;
    }

    public async Task StopAsync()
    {
        _cts?.Cancel();
        if (_process is { HasExited: false } process)
        {
            process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync().ConfigureAwait(false);
        }

        _frames.Writer.TryComplete();
        if (_pump is not null)
        {
            try { await _pump.ConfigureAwait(false); }
            catch (OperationCanceledException) { }
        }
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync().ConfigureAwait(false);
        _cts?.Dispose();
        _process?.Dispose();
    }

    private async Task ReadLoopAsync(Process process, CancellationToken ct)
    {
        var buffer = new byte[_frameSizeBytes];
        try
        {
            while (!ct.IsCancellationRequested)
            {
                var read = 0;
                while (read < buffer.Length)
                {
                    var chunk = await process.StandardOutput.BaseStream.ReadAsync(buffer.AsMemory(read, buffer.Length - read), ct).ConfigureAwait(false);
                    if (chunk == 0)
                    {
                        var error = await process.StandardError.ReadToEndAsync(ct).ConfigureAwait(false);
                        throw new InvalidOperationException($"parec stopped before producing a full audio frame: {error.Trim()}");
                    }
                    read += chunk;
                }

                var copy = new byte[buffer.Length];
                Buffer.BlockCopy(buffer, 0, copy, 0, buffer.Length);
                if (AudioMixer.ExceedsThreshold(copy, threshold: 32))
                {
                    HasReceivedAudio = true;
                    LastAudibleAt = DateTimeOffset.UtcNow;
                }

                await _frames.Writer.WriteAsync(new AudioFrame(copy, DateTimeOffset.UtcNow.TimeOfDay, _frameSizeSamples), ct).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
            _frames.Writer.TryComplete();
        }
        catch (Exception ex)
        {
            _frames.Writer.TryComplete(ex);
        }
    }
}
