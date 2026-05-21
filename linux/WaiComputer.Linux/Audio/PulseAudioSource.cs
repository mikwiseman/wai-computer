namespace WaiComputer.Linux.Audio;

public sealed record PulseAudioSource(
    string Name,
    string Driver,
    string SampleSpec,
    bool IsMonitor,
    bool IsDefault);

public sealed record PulseAudioSourceSnapshot(
    string? DefaultSink,
    string? DefaultSource,
    IReadOnlyList<PulseAudioSource> Sources)
{
    public PulseAudioSource? DefaultMicrophone =>
        Sources.FirstOrDefault(s => !s.IsMonitor && s.IsDefault)
        ?? Sources.FirstOrDefault(s => !s.IsMonitor);

    public PulseAudioSource? DefaultSystemMonitor
    {
        get
        {
            if (!string.IsNullOrWhiteSpace(DefaultSink))
            {
                var expected = DefaultSink + ".monitor";
                var exact = Sources.FirstOrDefault(s => s.IsMonitor && string.Equals(s.Name, expected, StringComparison.Ordinal));
                if (exact is not null)
                {
                    return exact;
                }
            }

            return Sources.FirstOrDefault(s => s.IsMonitor && s.IsDefault)
                ?? Sources.FirstOrDefault(s => s.IsMonitor);
        }
    }
}

public static class PulseAudioSourceParser
{
    public static PulseAudioSourceSnapshot Parse(string pactlInfo, string shortSources)
    {
        var defaultSink = ExtractInfoValue(pactlInfo, "Default Sink:");
        var defaultSource = ExtractInfoValue(pactlInfo, "Default Source:");
        var sources = ParseShortSources(shortSources, defaultSource);
        return new PulseAudioSourceSnapshot(defaultSink, defaultSource, sources);
    }

    public static IReadOnlyList<PulseAudioSource> ParseShortSources(string shortSources, string? defaultSource)
    {
        var sources = new List<PulseAudioSource>();
        foreach (var rawLine in shortSources.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var columns = rawLine.Split('\t', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            if (columns.Length < 4)
            {
                columns = rawLine.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            }
            if (columns.Length < 4)
            {
                continue;
            }

            var name = columns[1];
            var driver = columns[2];
            var sampleSpec = columns[3];
            sources.Add(new PulseAudioSource(
                name,
                driver,
                sampleSpec,
                name.EndsWith(".monitor", StringComparison.Ordinal),
                string.Equals(name, defaultSource, StringComparison.Ordinal)));
        }

        return sources;
    }

    private static string? ExtractInfoValue(string pactlInfo, string key)
    {
        foreach (var line in pactlInfo.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (line.StartsWith(key, StringComparison.Ordinal))
            {
                var value = line[key.Length..].Trim();
                return string.IsNullOrWhiteSpace(value) ? null : value;
            }
        }

        return null;
    }
}
