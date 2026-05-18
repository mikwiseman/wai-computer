using BenchmarkDotNet.Attributes;
using BenchmarkDotNet.Running;
using WaiComputer.Core.Audio;
using WaiComputer.Core.Monitoring;

BenchmarkRunner.Run<SanitizerBench>();
BenchmarkRunner.Run<MixerBench>();

[MemoryDiagnoser]
public class SanitizerBench
{
    private readonly Dictionary<string, object?> _payload = new()
    {
        ["email"] = "user@example.com",
        ["transcript"] = new string('x', 4096),
        ["nested"] = new Dictionary<string, object?>
        {
            ["title"] = "Sensitive Project Q1 plan",
            ["body"] = "Please email hi@mikwiseman.com if you have questions.",
            ["token"] = "sk-totally-secret",
        },
    };

    [Benchmark]
    public IDictionary<string, object?> SanitiseNested() => Sanitizer.SanitizeDictionary(_payload);
}

[MemoryDiagnoser]
public class MixerBench
{
    private readonly byte[] _a = new byte[3200];
    private readonly byte[] _b = new byte[3200];
    private readonly byte[] _dst = new byte[3200];

    [Benchmark]
    public void MixToMono100ms() => AudioMixer.MixToMono(_a, _b, _dst);
}
