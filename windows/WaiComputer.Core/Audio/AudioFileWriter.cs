using System.Buffers.Binary;

namespace WaiComputer.Core.Audio;

/// <summary>
/// Writes a streamable WAV file (RIFF, 16-bit PCM, configurable channels +
/// sample rate). Header is emitted at open with placeholder sizes; sizes are
/// patched atomically on <see cref="Finalize"/>. Thread-safe.
/// Direct port of <c>AudioFileWriter.swift</c> (120 lines).
/// </summary>
public sealed class AudioFileWriter : IAsyncDisposable
{
    private readonly Stream _stream;
    private readonly bool _ownsStream;
    private readonly uint _sampleRate;
    private readonly ushort _channels;
    private readonly object _lock = new();
    private long _bytesWritten;
    private bool _finalized;

    public uint SampleRate => _sampleRate;
    public ushort Channels => _channels;
    public long BytesWritten { get { lock (_lock) { return _bytesWritten; } } }

    public double DurationSeconds
    {
        get
        {
            lock (_lock)
            {
                return _channels == 0 || _sampleRate == 0
                    ? 0.0
                    : (double)_bytesWritten / (2.0 * _channels * _sampleRate);
            }
        }
    }

    public AudioFileWriter(string path, uint sampleRate = 16000, ushort channels = 1)
        : this(new FileStream(path, FileMode.Create, FileAccess.ReadWrite, FileShare.Read), sampleRate, channels, ownsStream: true) { }

    public AudioFileWriter(Stream stream, uint sampleRate, ushort channels, bool ownsStream)
    {
        if (!stream.CanWrite || !stream.CanSeek)
        {
            throw new ArgumentException("Stream must be writable and seekable.", nameof(stream));
        }
        _stream = stream;
        _ownsStream = ownsStream;
        _sampleRate = sampleRate;
        _channels = channels;
        WriteHeader(initial: true);
    }

    public void WriteEncodedPcm(ReadOnlySpan<byte> pcm)
    {
        if (pcm.IsEmpty) return;
        lock (_lock)
        {
            if (_finalized) throw new InvalidOperationException("Cannot write after Finalize().");
            _stream.Write(pcm);
            _bytesWritten += pcm.Length;
        }
    }

    public void Finalize()
    {
        lock (_lock)
        {
            if (_finalized) return;
            _finalized = true;
            PatchSizes();
            _stream.Flush();
        }
    }

    public ValueTask DisposeAsync()
    {
        try { Finalize(); } catch { /* swallow on dispose */ }
        if (_ownsStream)
        {
            _stream.Dispose();
        }
        return ValueTask.CompletedTask;
    }

    private void WriteHeader(bool initial)
    {
        Span<byte> header = stackalloc byte[44];
        header[0] = (byte)'R'; header[1] = (byte)'I'; header[2] = (byte)'F'; header[3] = (byte)'F';
        BinaryPrimitives.WriteUInt32LittleEndian(header[4..8], 36); // patched
        header[8] = (byte)'W'; header[9] = (byte)'A'; header[10] = (byte)'V'; header[11] = (byte)'E';
        header[12] = (byte)'f'; header[13] = (byte)'m'; header[14] = (byte)'t'; header[15] = (byte)' ';
        BinaryPrimitives.WriteUInt32LittleEndian(header[16..20], 16);     // fmt chunk size
        BinaryPrimitives.WriteUInt16LittleEndian(header[20..22], 1);      // PCM
        BinaryPrimitives.WriteUInt16LittleEndian(header[22..24], _channels);
        BinaryPrimitives.WriteUInt32LittleEndian(header[24..28], _sampleRate);
        BinaryPrimitives.WriteUInt32LittleEndian(header[28..32], _sampleRate * _channels * 2u); // byte rate
        BinaryPrimitives.WriteUInt16LittleEndian(header[32..34], (ushort)(_channels * 2));      // block align
        BinaryPrimitives.WriteUInt16LittleEndian(header[34..36], 16);                            // bits/sample
        header[36] = (byte)'d'; header[37] = (byte)'a'; header[38] = (byte)'t'; header[39] = (byte)'a';
        BinaryPrimitives.WriteUInt32LittleEndian(header[40..44], 0); // patched

        if (initial)
        {
            _stream.Write(header);
        }
        else
        {
            _stream.Seek(0, SeekOrigin.Begin);
            _stream.Write(header);
        }
    }

    private void PatchSizes()
    {
        var data = (uint)_bytesWritten;
        var riff = 36u + data;

        _stream.Seek(4, SeekOrigin.Begin);
        Span<byte> riffSizeBytes = stackalloc byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(riffSizeBytes, riff);
        _stream.Write(riffSizeBytes);

        _stream.Seek(40, SeekOrigin.Begin);
        Span<byte> dataSizeBytes = stackalloc byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(dataSizeBytes, data);
        _stream.Write(dataSizeBytes);
    }
}
