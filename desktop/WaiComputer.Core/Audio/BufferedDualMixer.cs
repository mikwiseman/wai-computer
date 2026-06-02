namespace WaiComputer.Core.Audio;

/// <summary>
/// Buffered, sample-accurate mixer porting the macOS <c>flushDualBuffers</c>
/// logic. Per-source accumulators are aligned on each flush so the microphone is
/// never blocked by missing or jittery system audio, while emitted frames stay
/// sample-accurate. Pure and synchronous — drive it from a single producer
/// (DualAudioCapture's pumps + flush pump). Not thread-safe.
/// </summary>
internal sealed class BufferedDualMixer
{
    private readonly AudioCaptureConfig _config;
    private readonly AudioSourceBuffer _mic = new();
    private readonly AudioSourceBuffer _system = new();
    private long _emittedSamples;

    public BufferedDualMixer(AudioCaptureConfig config) => _config = config;

    public void AppendMic(ReadOnlySpan<byte> pcm16) => _mic.Append(pcm16);

    public void AppendSystem(ReadOnlySpan<byte> pcm16) => _system.Append(pcm16);

    public void Reset()
    {
        _mic.Clear();
        _system.Clear();
    }

    /// <summary>
    /// How many aligned samples to emit this flush, porting Mac's four cases:
    /// (d) mic below the 80 ms floor — emit nothing (mic never blocked, no tiny
    /// chunk); (a) both ready — <c>min(mic, sys)</c> to stay in sync; (b) system
    /// stalled (no samples) — cap mic at 1 s; (c) system partial — <c>min(mic,
    /// max(sys, minFlush))</c>.
    /// </summary>
    internal static int ComputeFrames(int micCount, int sysCount, int minFlush, int maxStallPad)
    {
        if (micCount < minFlush)
        {
            return 0; // (d)
        }
        if (sysCount >= minFlush)
        {
            return Math.Min(micCount, sysCount); // (a)
        }
        if (sysCount == 0)
        {
            return Math.Min(micCount, maxStallPad); // (b)
        }
        return Math.Min(micCount, Math.Max(sysCount, minFlush)); // (c)
    }

    /// <summary>
    /// Emit the next aligned frame, or null when there is not enough mic audio yet.
    /// <paramref name="hasSystemSource"/> is false for mic-only recordings;
    /// <paramref name="systemUsable"/> is false when system audio is configured
    /// but has never produced audible audio / is stalled.
    /// </summary>
    public AudioFrame? TryFlush(bool hasSystemSource, bool systemUsable)
    {
        var frames = ComputeFrames(_mic.CountSamples, _system.CountSamples, _config.MinFlushSamples, _config.MaxStallPadSamples);
        if (frames <= 0)
        {
            return null;
        }

        var micSlice = new byte[frames * 2];
        _mic.TakeInto(frames, micSlice);

        var timestamp = TimeSpan.FromMilliseconds(_emittedSamples * 1000.0 / _config.SampleRate);
        _emittedSamples += frames;

        if (!hasSystemSource)
        {
            return new AudioFrame(micSlice, timestamp, frames);
        }

        // Always drain the system buffer in lockstep so it can't grow unbounded.
        var sysSlice = new byte[frames * 2];
        _system.TakeInto(frames, sysSlice);

        if (_config.SeparateChannels)
        {
            var stereo = new byte[frames * 4];
            AudioMixer.InterleaveStereo(micSlice, sysSlice, stereo);
            return new AudioFrame(stereo, timestamp, frames);
        }

        if (!systemUsable)
        {
            // System present but not yet audible / stalled — mic verbatim, no
            // attenuation (Mac monoMixedSample with hasSystemAudio == false).
            return new AudioFrame(micSlice, timestamp, frames);
        }

        var mono = new byte[frames * 2];
        AudioMixer.MixToMonoAverage(micSlice, sysSlice, mono);
        return new AudioFrame(mono, timestamp, frames);
    }
}
