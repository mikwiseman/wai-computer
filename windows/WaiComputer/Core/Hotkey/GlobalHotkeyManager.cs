using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Hotkey;

namespace WaiComputer.Native.Hotkey;

/// <summary>
/// Global low-level keyboard hook (<c>WH_KEYBOARD_LL</c>) that drives a
/// <see cref="HotkeyStateMachine"/>. No Accessibility-equivalent privacy
/// permission is required on Windows — this is the well-trodden path used by
/// PowerToys, AutoHotkey, Wispr Flow's Windows client, etc.
/// </summary>
public sealed class GlobalHotkeyManager : IDisposable
{
    private readonly HotkeyStateMachine _machine;
    private readonly ILogger<GlobalHotkeyManager> _logger;
    private readonly LowLevelKeyboardProc _proc;
    private IntPtr _hookId = IntPtr.Zero;
    private DictationHotkey _hotkey = DictationHotkey.RightAlt;

    public event Action? PushToTalkStart { add => _machine.PushToTalkStart += value; remove => _machine.PushToTalkStart -= value; }
    public event Action? PushToTalkStop { add => _machine.PushToTalkStop += value; remove => _machine.PushToTalkStop -= value; }
    public event Action? HandsFreeToggle { add => _machine.HandsFreeToggle += value; remove => _machine.HandsFreeToggle -= value; }
    public event Action? SingleTap { add => _machine.SingleTap += value; remove => _machine.SingleTap -= value; }
    public event Action? Cancelled { add => _machine.Cancelled += value; remove => _machine.Cancelled -= value; }

    public DictationHotkey Hotkey
    {
        get => _hotkey;
        set { _hotkey = value; _logger.LogInformation("Push-to-talk hotkey set to {Hotkey}", value); }
    }

    public bool IsRunning => _hookId != IntPtr.Zero;

    public GlobalHotkeyManager(HotkeyStateMachine machine, ILogger<GlobalHotkeyManager>? logger = null)
    {
        _machine = machine;
        _logger = logger ?? NullLogger<GlobalHotkeyManager>.Instance;
        _proc = HookCallback;
    }

    public void Start()
    {
        if (IsRunning) return;
        using var curProcess = Process.GetCurrentProcess();
        using var curModule = curProcess.MainModule!;
        _hookId = SetWindowsHookEx(Win32Constants.WH_KEYBOARD_LL, _proc, GetModuleHandle(curModule.ModuleName!), 0);
        if (_hookId == IntPtr.Zero)
        {
            throw new InvalidOperationException($"SetWindowsHookEx failed: {Marshal.GetLastWin32Error()}");
        }
        _logger.LogInformation("Low-level keyboard hook installed");
    }

    public void Stop()
    {
        if (_hookId == IntPtr.Zero) return;
        UnhookWindowsHookEx(_hookId);
        _hookId = IntPtr.Zero;
    }

    public void Dispose() => Stop();

    private IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode < 0) return CallNextHookEx(_hookId, nCode, wParam, lParam);

        var msg = wParam.ToInt32();
        var data = Marshal.PtrToStructure<KBDLLHOOKSTRUCT>(lParam);
        var vk = (int)data.vkCode;
        var now = DateTimeOffset.UtcNow;
        var isDown = msg == Win32Constants.WM_KEYDOWN || msg == Win32Constants.WM_SYSKEYDOWN;
        var isUp = msg == Win32Constants.WM_KEYUP || msg == Win32Constants.WM_SYSKEYUP;

        if (Matches(vk))
        {
            if (isDown) _machine.OnKeyDown(now);
            else if (isUp) _machine.OnKeyUp(now);
        }
        else if (isDown)
        {
            _machine.OnOtherKeyPressed();
        }

        return CallNextHookEx(_hookId, nCode, wParam, lParam);
    }

    private bool Matches(int vk) => _hotkey switch
    {
        DictationHotkey.RightAlt => vk == Win32Constants.VK_RMENU,
        DictationHotkey.LeftAlt => vk == Win32Constants.VK_LMENU,
        DictationHotkey.RightCtrl => vk == Win32Constants.VK_RCONTROL,
        DictationHotkey.RightWin => vk == Win32Constants.VK_RWIN,
        DictationHotkey.CapsLock => vk == Win32Constants.VK_CAPITAL,
        DictationHotkey.CtrlAlt => vk == Win32Constants.VK_LCONTROL || vk == Win32Constants.VK_RCONTROL
                                  || vk == Win32Constants.VK_LMENU || vk == Win32Constants.VK_RMENU,
        _ => false,
    };

    [StructLayout(LayoutKind.Sequential)]
    private struct KBDLLHOOKSTRUCT
    {
        public uint vkCode;
        public uint scanCode;
        public uint flags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    private delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(int idHook, LowLevelKeyboardProc lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern IntPtr GetModuleHandle(string lpModuleName);
}
