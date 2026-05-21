namespace WaiComputer.Core.Hotkey;

/// <summary>
/// Push-to-talk / hands-free state logic. Pure: takes timestamped key events
/// as input and emits callback decisions. Mirrors the Swift
/// <c>GlobalHotkeyManager</c>: 150 ms hold threshold, 400 ms double-tap
/// window, "abort if other key pressed" guard. Lifting Win32 mechanics out
/// of the state machine lets us unit-test on macOS without any Windows
/// dependencies.
/// </summary>
public sealed class HotkeyStateMachine
{
    private readonly TimeSpan _holdThreshold;
    private readonly TimeSpan _doubleTapWindow;

    private bool _heldDown;
    private DateTimeOffset _downAt;
    private DateTimeOffset? _lastTapAt;
    private bool _otherKeyPressedDuringHold;
    private bool _inPushToTalk;
    private DateTimeOffset _holdElapsedTriggerAt;
    private bool _holdElapsedPending;

    public HotkeyStateMachine(TimeSpan? holdThreshold = null, TimeSpan? doubleTapWindow = null)
    {
        _holdThreshold = holdThreshold ?? TimeSpan.FromMilliseconds(150);
        _doubleTapWindow = doubleTapWindow ?? TimeSpan.FromMilliseconds(400);
    }

    public event Action? PushToTalkStart;
    public event Action? PushToTalkStop;
    public event Action? HandsFreeToggle;
    public event Action? SingleTap;
    public event Action? Cancelled;

    public bool IsHeld => _heldDown;
    public bool InPushToTalk => _inPushToTalk;

    public void OnKeyDown(DateTimeOffset at)
    {
        if (_heldDown) return;
        _heldDown = true;
        _downAt = at;
        _otherKeyPressedDuringHold = false;
        _holdElapsedPending = true;
        _holdElapsedTriggerAt = at + _holdThreshold;
    }

    /// <summary>
    /// Drives time-based transitions (the "hold threshold passed" point).
    /// Call from your tick driver, or directly from <see cref="OnKeyUp"/>.
    /// </summary>
    public void Tick(DateTimeOffset now)
    {
        if (!_holdElapsedPending) return;
        if (now < _holdElapsedTriggerAt) return;
        _holdElapsedPending = false;
        if (_heldDown && !_otherKeyPressedDuringHold && !_inPushToTalk)
        {
            _inPushToTalk = true;
            PushToTalkStart?.Invoke();
        }
    }

    public void OnKeyUp(DateTimeOffset at)
    {
        if (!_heldDown) return;
        Tick(at); // ensure hold threshold transition resolved before deciding tap vs hold
        var heldFor = at - _downAt;
        _heldDown = false;
        _holdElapsedPending = false;

        if (_inPushToTalk)
        {
            _inPushToTalk = false;
            if (_otherKeyPressedDuringHold) Cancelled?.Invoke();
            else PushToTalkStop?.Invoke();
        }
        else if (_otherKeyPressedDuringHold)
        {
            Cancelled?.Invoke();
        }
        else if (heldFor < _holdThreshold)
        {
            if (_lastTapAt is { } prev && (at - prev) < _doubleTapWindow)
            {
                _lastTapAt = null;
                HandsFreeToggle?.Invoke();
            }
            else
            {
                _lastTapAt = at;
                SingleTap?.Invoke();
            }
        }

        _otherKeyPressedDuringHold = false;
    }

    public void OnOtherKeyPressed()
    {
        if (_heldDown) _otherKeyPressedDuringHold = true;
    }
}
