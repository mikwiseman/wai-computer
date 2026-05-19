using System.Threading.Channels;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using NAudio.CoreAudioApi;
using NAudio.Wave;
using WaiComputer.Core.Audio;

namespace WaiComputer.Native.Audio;

/// <summary>
/// System-audio capture via WASAPI loopback on the default render device.
/// Captures everything Windows plays through speakers/headphones; resamples to
/// 16 kHz mono int16. Windows 10 1809+ supported without driver.
///
/// For process-isolated loopback (exclude WaiComputer's own playback) see
/// the ProcessLoopback path planned for v1.1.
/// </summary>
public sealed class WasapiSystemAudioCapture : ISystemAudioCapture
{
    private readonly int _sampleRate;
    private readonly int _frameSizeSamples;
    private readonly int _frameSizeBytes;
    private readonly ILogger<WasapiSystemAudioCapture> _logger;
    private readonly Channel<AudioFrame> _frames = Channel.CreateBounded<AudioFrame>(
        new BoundedChannelOptions(64) { FullMode = BoundedChannelFullMode.DropOldest, SingleReader = true });
    private readonly byte[] _frameBuffer;
    private int _bufferedBytes;
    private WasapiLoopbackCapture? _loopback;
    private BufferedWaveProvider? _sourceProvider;
    private MediaFoundationResampler? _resampler;

    public WasapiSystemAudioCapture(int sampleRate = 16000, int frameSizeSamples = 1600, ILogger<WasapiSystemAudioCapture>? logger = null)
    {
        _sampleRate = sampleRate;
        _frameSizeSamples = frameSizeSamples;
        _frameSizeBytes = frameSizeSamples * 2;
        _logger = logger ?? NullLogger<WasapiSystemAudioCapture>.Instance;
        _frameBuffer = new byte[_frameSizeBytes];
    }

    public AudioSource Source => AudioSource.SystemAudio;
    public bool IsCapturing => _loopback is { CaptureState: CaptureState.Capturing };
    public bool HasReceivedAudio { get; private set; }
    public DateTimeOffset? LastAudibleAt { get; private set; }
    public ChannelReader<AudioFrame> Frames => _frames.Reader;

    public Task StartAsync(CancellationToken ct)
    {
        var enumerator = new MMDeviceEnumerator();
        var device = enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia)
                    ?? throw new InvalidOperationException("No default audio render device — system audio loopback unavailable.");
        _loopback = new WasapiLoopbackCapture(device);
        _sourceProvider = new BufferedWaveProvider(_loopback.WaveFormat)
        {
            BufferDuration = TimeSpan.FromSeconds(2),
            DiscardOnBufferOverflow = true,
        };
        _resampler = new MediaFoundationResampler(_sourceProvider, new WaveFormat(_sampleRate, 16, 1))
        {
            ResamplerQuality = 60,
        };
        _loopback.DataAvailable += OnDataAvailable;
        _loopback.RecordingStopped += (_, e) =>
        {
            if (e.Exception is not null) _logger.LogWarning(e.Exception, "Loopback stopped with exception");
            _frames.Writer.TryComplete();
        };
        _loopback.StartRecording();
        return Task.CompletedTask;
    }

    public Task StopAsync()
    {
        _loopback?.StopRecording();
        return Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        _resampler?.Dispose();
        _loopback?.Dispose();
        return ValueTask.CompletedTask;
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs e)
    {
        if (_sourceProvider is null || _resampler is null) return;

        _sourceProvider.AddSamples(e.Buffer, 0, e.BytesRecorded);

        var temp = new byte[_frameSizeBytes];
        int read;
        while ((read = _resampler.Read(temp, 0, temp.Length)) > 0)
        {
            Buffer.BlockCopy(temp, 0, _frameBuffer, _bufferedBytes, read);
            _bufferedBytes += read;
            while (_bufferedBytes >= _frameSizeBytes)
            {
                var copy = new byte[_frameSizeBytes];
                Buffer.BlockCopy(_frameBuffer, 0, copy, 0, _frameSizeBytes);
                _bufferedBytes -= _frameSizeBytes;
                if (_bufferedBytes > 0)
                {
                    Buffer.BlockCopy(_frameBuffer, _frameSizeBytes, _frameBuffer, 0, _bufferedBytes);
                }
                if (AudioMixer.ExceedsThreshold(copy, threshold: 32))
                {
                    HasReceivedAudio = true;
                    LastAudibleAt = DateTimeOffset.UtcNow;
                }
                _frames.Writer.TryWrite(new AudioFrame(copy, DateTimeOffset.UtcNow.TimeOfDay, _frameSizeSamples));
            }
        }
    }
}
