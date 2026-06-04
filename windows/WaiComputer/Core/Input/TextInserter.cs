using System.Runtime.InteropServices;
using Microsoft.UI.Xaml;
using Windows.ApplicationModel.DataTransfer;
using WaiComputer.Native.Hotkey;

namespace WaiComputer.Native.Input;

/// <summary>
/// Clipboard + simulated Ctrl+V text insertion. Mirrors the macOS
/// <c>TextInserter</c>:
/// <list type="number">
///   <item>Set clipboard</item>
///   <item>Restore focus to the previously-focused window</item>
///   <item>Wait up to 500 ms for any held modifier to release</item>
///   <item><see cref="SendInput"/> Ctrl+V</item>
/// </list>
/// On any failure the text remains on the clipboard so the user can paste manually.
/// </summary>
public static class TextInserter
{
    public enum InsertionFailure
    {
        EmptyText,
        ClipboardWriteFailed,
        ModifierStuck,
        SendInputFailed,
    }

    public sealed class InsertionResult
    {
        public bool Success { get; init; }
        public InsertionFailure? Failure { get; init; }
        public string? UserMessage { get; init; }
        public static InsertionResult Ok() => new() { Success = true };
        public static InsertionResult Fail(InsertionFailure f, string msg) =>
            new() { Success = false, Failure = f, UserMessage = msg };
    }

    public static async Task<InsertionResult> InsertAsync(string text, IntPtr targetWindow)
    {
        if (string.IsNullOrEmpty(text))
        {
            return InsertionResult.Fail(InsertionFailure.EmptyText, "Nothing to insert.");
        }

        if (!SetClipboardText(text))
        {
            return InsertionResult.Fail(InsertionFailure.ClipboardWriteFailed,
                "Failed to copy text to clipboard.");
        }

        if (targetWindow != IntPtr.Zero)
        {
            SetForegroundWindow(targetWindow);
        }

        await Task.Delay(200);

        if (!await WaitForModifierReleaseAsync(TimeSpan.FromMilliseconds(500)))
        {
            return InsertionResult.Fail(InsertionFailure.ModifierStuck,
                "Text is on your clipboard — press Ctrl+V to paste manually.");
        }

        if (!SendCtrlV())
        {
            return InsertionResult.Fail(InsertionFailure.SendInputFailed,
                "Text is on your clipboard — press Ctrl+V to paste manually.");
        }
        return InsertionResult.Ok();
    }

    private static bool SetClipboardText(string text)
    {
        try
        {
            var dp = new DataPackage();
            dp.SetText(text);
            Clipboard.SetContent(dp);
            return true;
        }
        catch { return false; }
    }

    private static async Task<bool> WaitForModifierReleaseAsync(TimeSpan timeout)
    {
        var deadline = DateTimeOffset.UtcNow + timeout;
        while (DateTimeOffset.UtcNow < deadline)
        {
            if (NoModifierHeld()) return true;
            await Task.Delay(10);
        }
        return NoModifierHeld();
    }

    private static bool NoModifierHeld()
    {
        return (GetAsyncKeyState(Win32Constants.VK_LCONTROL) & 0x8000) == 0
            && (GetAsyncKeyState(Win32Constants.VK_RCONTROL) & 0x8000) == 0
            && (GetAsyncKeyState(Win32Constants.VK_LSHIFT) & 0x8000) == 0
            && (GetAsyncKeyState(Win32Constants.VK_RSHIFT) & 0x8000) == 0
            && (GetAsyncKeyState(Win32Constants.VK_LMENU) & 0x8000) == 0
            && (GetAsyncKeyState(Win32Constants.VK_RMENU) & 0x8000) == 0
            && (GetAsyncKeyState(Win32Constants.VK_LWIN) & 0x8000) == 0
            && (GetAsyncKeyState(Win32Constants.VK_RWIN) & 0x8000) == 0;
    }

    private static bool SendCtrlV()
    {
        var inputs = new INPUT[]
        {
            MakeKey(Win32Constants.VK_CONTROL, false),
            MakeKey(Win32Constants.VK_V, false),
            MakeKey(Win32Constants.VK_V, true),
            MakeKey(Win32Constants.VK_CONTROL, true),
        };
        var sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<INPUT>());
        return sent == inputs.Length;
    }

    private static INPUT MakeKey(int vk, bool up) => new()
    {
        type = 1,
        union = new INPUTUNION
        {
            ki = new KEYBDINPUT
            {
                wVk = (ushort)vk,
                dwFlags = up ? 2u : 0u,
                time = 0,
                dwExtraInfo = IntPtr.Zero,
            },
        },
    };

    [StructLayout(LayoutKind.Explicit)]
    private struct INPUTUNION
    {
        [FieldOffset(0)] public KEYBDINPUT ki;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct INPUT
    {
        public uint type;
        public INPUTUNION union;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern short GetAsyncKeyState(int vKey);

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetForegroundWindow(IntPtr hWnd);
}
