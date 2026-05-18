using FluentAssertions;
using WaiComputer.Core.Hotkey;
using Xunit;

namespace WaiComputer.Core.Tests.Recording;

public class HotkeyStateMachineTests
{
    private static DateTimeOffset T0 => new(2026, 5, 18, 12, 0, 0, TimeSpan.Zero);

    [Fact]
    public void HoldBeyondThresholdFiresPushToTalkStartAndStop()
    {
        var machine = new HotkeyStateMachine();
        int starts = 0, stops = 0;
        machine.PushToTalkStart += () => starts++;
        machine.PushToTalkStop += () => stops++;

        machine.OnKeyDown(T0);
        machine.Tick(T0 + TimeSpan.FromMilliseconds(200));
        machine.OnKeyUp(T0 + TimeSpan.FromMilliseconds(800));

        starts.Should().Be(1);
        stops.Should().Be(1);
    }

    [Fact]
    public void ShortTapFiresSingleTap()
    {
        var machine = new HotkeyStateMachine();
        int single = 0, ptt = 0;
        machine.SingleTap += () => single++;
        machine.PushToTalkStart += () => ptt++;

        machine.OnKeyDown(T0);
        machine.OnKeyUp(T0 + TimeSpan.FromMilliseconds(50));

        single.Should().Be(1);
        ptt.Should().Be(0);
    }

    [Fact]
    public void DoubleTapWithinWindowFiresHandsFreeToggle()
    {
        var machine = new HotkeyStateMachine();
        int toggle = 0;
        machine.HandsFreeToggle += () => toggle++;

        machine.OnKeyDown(T0);
        machine.OnKeyUp(T0 + TimeSpan.FromMilliseconds(40));
        machine.OnKeyDown(T0 + TimeSpan.FromMilliseconds(200));
        machine.OnKeyUp(T0 + TimeSpan.FromMilliseconds(240));

        toggle.Should().Be(1);
    }

    [Fact]
    public void OtherKeyDuringHoldCancels()
    {
        var machine = new HotkeyStateMachine();
        int cancelled = 0, stops = 0;
        machine.Cancelled += () => cancelled++;
        machine.PushToTalkStop += () => stops++;

        machine.OnKeyDown(T0);
        machine.Tick(T0 + TimeSpan.FromMilliseconds(200)); // enter PTT
        machine.OnOtherKeyPressed();
        machine.OnKeyUp(T0 + TimeSpan.FromMilliseconds(600));

        cancelled.Should().Be(1);
        stops.Should().Be(0);
    }

    [Fact]
    public void DoubleDownIgnored()
    {
        var machine = new HotkeyStateMachine();
        int starts = 0;
        machine.PushToTalkStart += () => starts++;

        machine.OnKeyDown(T0);
        machine.OnKeyDown(T0 + TimeSpan.FromMilliseconds(5));   // ignored
        machine.Tick(T0 + TimeSpan.FromMilliseconds(200));
        machine.OnKeyUp(T0 + TimeSpan.FromMilliseconds(400));

        starts.Should().Be(1);
    }

    [Fact]
    public void TapOutsideDoubleTapWindowIsSingleTap()
    {
        var machine = new HotkeyStateMachine();
        int single = 0, toggle = 0;
        machine.SingleTap += () => single++;
        machine.HandsFreeToggle += () => toggle++;

        machine.OnKeyDown(T0);
        machine.OnKeyUp(T0 + TimeSpan.FromMilliseconds(50));
        machine.OnKeyDown(T0 + TimeSpan.FromMilliseconds(600));
        machine.OnKeyUp(T0 + TimeSpan.FromMilliseconds(650));

        single.Should().Be(2);
        toggle.Should().Be(0);
    }
}
