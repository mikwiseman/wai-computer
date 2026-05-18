namespace WaiComputer.Native.Hotkey;

internal static class Win32Constants
{
    public const int WH_KEYBOARD_LL = 13;
    public const int WM_KEYDOWN = 0x0100;
    public const int WM_KEYUP = 0x0101;
    public const int WM_SYSKEYDOWN = 0x0104;
    public const int WM_SYSKEYUP = 0x0105;

    // Virtual keys
    public const int VK_LMENU = 0xA4;
    public const int VK_RMENU = 0xA5; // Right Alt
    public const int VK_LCONTROL = 0xA2;
    public const int VK_RCONTROL = 0xA3;
    public const int VK_LSHIFT = 0xA0;
    public const int VK_RSHIFT = 0xA1;
    public const int VK_LWIN = 0x5B;
    public const int VK_RWIN = 0x5C;
    public const int VK_CAPITAL = 0x14;
    public const int VK_CONTROL = 0x11;
    public const int VK_V = 0x56;
}
