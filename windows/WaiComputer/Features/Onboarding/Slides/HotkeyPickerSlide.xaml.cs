using Microsoft.UI.Xaml.Controls;
namespace WaiComputer.Features.Onboarding.Slides;
public sealed partial class HotkeyPickerSlide : Page
{
    public HotkeyPickerSlide()
    {
        InitializeComponent();
        HotkeyCombo.SelectionChanged += (_, _) =>
        {
            if (HotkeyCombo.SelectedItem is ComboBoxItem item)
            {
                WarnInfoBar.IsOpen = item.Tag is "LeftAlt" or "RightWin";
            }
        };
    }
}
