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
/// </summary>
public sealed class WasapiMicrophoneCapture : IMicrophoneCapture
{
    private readonly int _sampleRate;
    private readonly int _frameSizeSamples;
    private readonly ILogger<WasapiMicrophoneCapture> _logger;
    private readonly Channel<AudioFrame> _frames = Channel.CreateBounded<AudioFrame>(
        new BoundedChannelOptions(64) { FullMode = BoundedChannelFullMode.DropOldest, SingleReader = true });
    private readonly byte[] _frameBuffer;

    private WasapiCapture? _capture;
    private MediaFoundationResampler? _resampler;
    private int _bufferedBytes;

    public WasapiMicrophoneCapture(int sampleRate = 16000, int frameSizeSamples = 1600, ILogger<WasapiMicrophoneCapture>? logger = null)
    {
        _sampleRate = sampleRate;
        _frameSizeSamples = frameSizeSamples;
        _logger = logger ?? NullLogger<WasapiMicrophoneCapture>.Instance;
        _frameBuffer = new byte[frameSizeSamples * 2];
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
        _capture.WaveFormat = device.AudioClient.MixFormat; // capture in device format, resample down
        _resampler = new MediaFoundationResampler(
            new WaveFormatConversionProvider(_capture.WaveFormat),
            new WaveFormat(_sampleRate, 16, 1));
        _resampler.ResamplerQuality = 60;

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
        _capture?.Dispose();
        _resampler?.Dispose();
        return ValueTask.CompletedTask;
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs e)
    {
        if (_resampler is null) return;

        // Feed source into the resampler via its internal source, then read 16k mono PCM.
        // NAudio's MediaFoundationResampler doesn't accept push input directly — we wrap
        // the buffer in a BufferedWaveProvider for streaming.
        // For brevity we use BufferedWaveProvider here.
        var sourceProvider = new BufferedWaveProvider(_capture!.WaveFormat)
        {
            BufferLength = e.BytesRecorded * 4,
            DiscardOnBufferOverflow = true,
        };
        sourceProvider.AddSamples(e.Buffer, 0, e.BytesRecorded);

        using var resampler = new MediaFoundationResampler(sourceProvider, new WaveFormat(_sampleRate, 16, 1)) { ResamplerQuality = 60 };

        var temp = new byte[_frameSizeSamples * 2];
        int read;
        while ((read = resampler.Read(temp, 0, temp.Length)) > 0)
        {
            Buffer.BlockCopy(temp, 0, _frameBuffer, _bufferedBytes, read);
            _bufferedBytes += read;
            while (_bufferedBytes >= _frameBuffer.Length)
            {
                var copy = new byte[_frameBuffer.Length];
                Buffer.BlockCopy(_frameBuffer, 0, copy, 0, _frameBuffer.Length);
                _bufferedBytes -= _frameBuffer.Length;
                if (_bufferedBytes > 0)
                {
                    Buffer.BlockCopy(_frameBuffer, _frameBuffer.Length, _frameBuffer, 0, _bufferedBytes);
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

/// <summary>
/// Helper to satisfy <see cref="MediaFoundationResampler"/> which wants an
/// <see cref="IWaveProvider"/>. The WaveFormat is the only field accessed
/// during construction; the actual data is pushed via BufferedWaveProvider
/// in <see cref="WasapiMicrophoneCapture.OnDataAvailable"/>.
/// </summary>
internal sealed class WaveFormatConversionProvider : IWaveProvider
{
    public WaveFormat WaveFormat { get; }
    public WaveFormatConversionProvider(WaveFormat format) { WaveFormat = format; }
    public int Read(byte[] buffer, int offset, int count) => 0;
}
