using System.Threading.Channels;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using NAudio.CoreAudioApi;
using NAudio.Wave;
using WaiComputer.Core.Audio;

namespace WaiComputer.Native.Audio;

/// <summary>
/// Microphone capture via WASAPI shared mode. Output is 16 kHz mono int16 PCM
/// frames of <c>frameSizeSamples</c> samples each (default 1600 = 100 ms).
/// Resamples the device's native mix format down to the target inline.
/// </summary>
public sealed class WasapiMicrophoneCapture : IMicrophoneCapture
{
    private readonly int _sampleRate;
    private readonly int _frameSizeSamples;
    private readonly int _frameSizeBytes;
    private readonly ILogger<WasapiMicrophoneCapture> _logger;
    private readonly Channel<AudioFrame> _frames = Channel.CreateBounded<AudioFrame>(
        new BoundedChannelOptions(64) { FullMode = BoundedChannelFullMode.DropOldest, SingleReader = true });
    private readonly byte[] _frameBuffer;
    private int _bufferedBytes;

    private WasapiCapture? _capture;
    private BufferedWaveProvider? _sourceProvider;
    private MediaFoundationResampler? _resampler;

    public WasapiMicrophoneCapture(int sampleRate = 16000, int frameSizeSamples = 1600, ILogger<WasapiMicrophoneCapture>? logger = null)
    {
        _sampleRate = sampleRate;
        _frameSizeSamples = frameSizeSamples;
        _frameSizeBytes = frameSizeSamples * 2;
        _logger = logger ?? NullLogger<WasapiMicrophoneCapture>.Instance;
        _frameBuffer = new byte[_frameSizeBytes];
    }

    public AudioSource Source => AudioSource.Microphone;
    public bool IsCapturing => _capture is { CaptureState: CaptureState.Capturing };
    public bool HasReceivedAudio { get; private set; }
    public DateTimeOffset? LastAudibleAt { get; private set; }
    public ChannelReader<AudioFrame> Frames => _frames.Reader;

    public Task StartAsync(CancellationToken ct)
    {
        var enumerator = new MMDeviceEnumerator();
        var device = enumerator.GetDefaultAudioEndpoint(DataFlow.Capture, Role.Communications)
                    ?? throw new InvalidOperationException("No default audio capture device available.");

        _capture = new WasapiCapture(device);
        _sourceProvider = new BufferedWaveProvider(_capture.WaveFormat)
        {
            BufferDuration = TimeSpan.FromSeconds(2),
            DiscardOnBufferOverflow = true,
        };
        _resampler = new MediaFoundationResampler(_sourceProvider, new WaveFormat(_sampleRate, 16, 1))
        {
            ResamplerQuality = 60,
        };

        _capture.DataAvailable += OnDataAvailable;
        _capture.RecordingStopped += (_, e) =>
        {
            if (e.Exception is not null) _logger.LogWarning(e.Exception, "Mic capture stopped with exception");
            _frames.Writer.TryComplete();
        };
        _capture.StartRecording();
        return Task.CompletedTask;
    }

    public Task StopAsync()
    {
        _capture?.StopRecording();
        return Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        _resampler?.Dispose();
        _capture?.Dispose();
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
