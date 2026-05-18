using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.ApplicationModel.DataTransfer;

namespace WaiComputer.Features.Settings.Sections;

public sealed partial class McpConnectSection : UserControl
{
    private const string McpUrl = "https://wai.computer/mcp";
    public McpConnectSection() => InitializeComponent();

    private void Copy(string text)
    {
        var dp = new DataPackage();
        dp.SetText(text);
        Clipboard.SetContent(dp);
    }

    private void OnCopyUrl(object sender, RoutedEventArgs e) => Copy(McpUrl);

    private void OnCopyClaudeAi(object sender, RoutedEventArgs e) => Copy(
        $"In Claude.ai → Settings → Connectors → Add custom connector. URL: {McpUrl}. Sign in with your WaiComputer account.");

    private void OnCopyCursor(object sender, RoutedEventArgs e) => Copy(
        $"In Cursor, add to ~/.cursor/mcp.json: {{\"mcpServers\":{{\"waicomputer\":{{\"url\":\"{McpUrl}\"}}}}}}");

    private void OnCopyChatGpt(object sender, RoutedEventArgs e) => Copy(
        $"In ChatGPT (with custom GPT MCP support) → Add custom MCP connector. URL: {McpUrl}.");

    private void OnCopyClaudeCode(object sender, RoutedEventArgs e) => Copy(
        $"claude mcp add waicomputer {McpUrl}");

    private void OnCopyCodex(object sender, RoutedEventArgs e) => Copy(
        $"codex mcp add waicomputer {McpUrl}");
}
