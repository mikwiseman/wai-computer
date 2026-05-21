using System.Text;

namespace WaiComputer.Linux.Platform;

public sealed record LinuxDesktopIntegrationPlan(
    string DesktopFilePath,
    string DesktopFileContent,
    string SchemeMimeType);

public sealed class LinuxDesktopIntegration
{
    private const string DesktopFileName = "is.waiwai.computer.desktop";
    private readonly LinuxDesktopEnvironment _environment;

    public LinuxDesktopIntegration(LinuxDesktopEnvironment environment)
    {
        _environment = environment;
    }

    public LinuxDesktopIntegrationPlan CreatePlan(string executablePath, string iconPath)
    {
        if (string.IsNullOrWhiteSpace(executablePath))
        {
            throw new ArgumentException("Executable path must not be empty.", nameof(executablePath));
        }

        var applicationsDir = Path.Combine(_environment.XdgDataHome, "applications");
        var desktopPath = Path.Combine(applicationsDir, DesktopFileName);
        var content = new StringBuilder()
            .AppendLine("[Desktop Entry]")
            .AppendLine("Type=Application")
            .AppendLine("Name=WaiComputer")
            .AppendLine("Comment=AI second brain for recordings, transcription, search, and summaries")
            .AppendLine($"Exec={executablePath} %u")
            .AppendLine($"Icon={iconPath}")
            .AppendLine("Terminal=false")
            .AppendLine("Categories=Office;AudioVideo;Utility;")
            .AppendLine("StartupNotify=true")
            .AppendLine("MimeType=x-scheme-handler/waicomputer;")
            .ToString();

        return new LinuxDesktopIntegrationPlan(desktopPath, content, "x-scheme-handler/waicomputer");
    }

    public async Task InstallAsync(LinuxDesktopIntegrationPlan plan, ICommandRunner commands, CancellationToken ct = default)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(plan.DesktopFilePath)!);
        await File.WriteAllTextAsync(plan.DesktopFilePath, plan.DesktopFileContent, ct).ConfigureAwait(false);
        var result = await commands.RunAsync("xdg-mime", ["default", DesktopFileName, plan.SchemeMimeType], ct: ct).ConfigureAwait(false);
        if (!result.Succeeded)
        {
            throw new CommandException("xdg-mime", result);
        }
    }
}
