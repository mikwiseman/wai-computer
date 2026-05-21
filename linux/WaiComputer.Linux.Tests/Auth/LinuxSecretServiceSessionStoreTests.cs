using FluentAssertions;
using WaiComputer.Linux.Auth;
using WaiComputer.Linux.Platform;
using WaiComputer.Linux.Tests.TestDoubles;

namespace WaiComputer.Linux.Tests.Auth;

public sealed class LinuxSecretServiceSessionStoreTests
{
    [Fact]
    public async Task Save_writes_session_json_to_secret_tool_stdin()
    {
        var commands = new FakeCommandRunner();
        commands.Enqueue(
            "secret-tool",
            ["store", "--label", "WaiComputer session", "app", "wai-computer", "session", "default"],
            new CommandResult(0, "", ""));
        var store = new LinuxSecretServiceSessionStore(commands);

        await store.SaveAsync("access-token", "refresh-token");

        commands.Calls.Should().ContainSingle();
        commands.Calls[0].StandardInput.Should().Contain("access-token");
        commands.Calls[0].StandardInput.Should().Contain("refresh-token");
    }

    [Fact]
    public async Task Load_surfaces_secret_service_errors()
    {
        var commands = new FakeCommandRunner();
        commands.Enqueue(
            "secret-tool",
            ["lookup", "app", "wai-computer", "session", "default"],
            new CommandResult(2, "", "No such interface"));
        var store = new LinuxSecretServiceSessionStore(commands);

        var act = async () => await store.LoadAsync();

        await act.Should().ThrowAsync<LinuxSecretServiceException>()
            .WithMessage("*lookup failed*");
    }
}
