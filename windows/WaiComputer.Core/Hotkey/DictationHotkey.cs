namespace WaiComputer.Core.Hotkey;

/// <summary>
/// Available push-to-talk hotkeys. Windows equivalents of the macOS modifier-only
/// hotkeys in <c>GlobalHotkeyManager.swift</c>.
/// </summary>
public enum DictationHotkey
{
    /// <summary>Right Alt — default. Closest 1:1 to macOS Right Option.</summary>
    RightAlt,
    /// <summary>Left Alt — risky (Alt is a Windows accelerator). Warn the user.</summary>
    LeftAlt,
    /// <summary>Right Ctrl — works but used by some screen readers.</summary>
    RightCtrl,
    /// <summary>Right Windows key — risky (opens Start menu when released alone).</summary>
    RightWin,
    /// <summary>Caps Lock — re-purposed; Windows has no Fn-key equivalent.</summary>
    CapsLock,
    /// <summary>Combo: Ctrl + Alt (any side).</summary>
    CtrlAlt,
}

public static class DictationHotkeyExtensions
{
    public static string DisplayLabel(this DictationHotkey h) => h switch
    {
        DictationHotkey.RightAlt => "Right Alt",
        DictationHotkey.LeftAlt => "Left Alt",
        DictationHotkey.RightCtrl => "Right Ctrl",
        DictationHotkey.RightWin => "Right Win",
        DictationHotkey.CapsLock => "Caps Lock",
        DictationHotkey.CtrlAlt => "Ctrl + Alt",
        _ => h.ToString(),
    };
}
