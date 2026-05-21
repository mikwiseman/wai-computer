using WaiComputer.Linux.Platform;

namespace WaiComputer.Linux.Tests.TestDoubles;

public sealed class FakeCommandRunner : ICommandRunner
{
    private readonly Queue<(string FileName, IReadOnlyList<string> Arguments, CommandResult Result)> _responses = new();

    public List<(string FileName, IReadOnlyList<string> Arguments, string? StandardInput)> Calls { get; } = [];

    public void Enqueue(string fileName, IReadOnlyList<string> arguments, CommandResult result)
    {
        _responses.Enqueue((fileName, arguments, result));
    }

    public Task<CommandResult> RunAsync(
        string fileName,
        IReadOnlyList<string> arguments,
        string? standardInput = null,
        CancellationToken ct = default)
    {
        Calls.Add((fileName, arguments, standardInput));
        if (_responses.Count == 0)
        {
            throw new InvalidOperationException($"No fake response for {fileName} {string.Join(" ", arguments)}.");
        }

        var next = _responses.Dequeue();
        if (next.FileName != fileName || !next.Arguments.SequenceEqual(arguments))
        {
            throw new InvalidOperationException(
                $"Expected {next.FileName} {string.Join(" ", next.Arguments)}, got {fileName} {string.Join(" ", arguments)}.");
        }

        return Task.FromResult(next.Result);
    }
}
