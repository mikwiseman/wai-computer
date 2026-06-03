namespace WaiComputer.Linux.Updates;

public enum LinuxUpdateChannel
{
    Stable,
    Beta,
}

public sealed record LinuxUpdateFeed(string FeedUrl, string Channel);

public static class LinuxUpdatePolicy
{
    public const string StableChannel = "linux";
    public const string BetaChannel = "linux-beta";

    public static LinuxUpdateFeed Resolve(string feedUrl, LinuxUpdateChannel channel)
    {
        if (string.IsNullOrWhiteSpace(feedUrl))
        {
            throw new ArgumentException("Linux update feed URL must not be empty.", nameof(feedUrl));
        }

        return new LinuxUpdateFeed(feedUrl.TrimEnd('/'), channel == LinuxUpdateChannel.Beta ? BetaChannel : StableChannel);
    }
}
