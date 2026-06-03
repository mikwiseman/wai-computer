using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using WaiComputer.Features.Onboarding.Slides;

namespace WaiComputer.Features.Onboarding;

public sealed partial class OnboardingWindow : Window
{
    private static readonly Type[] Slides =
    {
        typeof(WelcomeSlide),
        typeof(ValuePropsSlide),
        typeof(HotkeyPickerSlide),
        typeof(LanguagesSlide),
        typeof(PermissionSlide),
        typeof(DictationSandboxSlide),
    };

    private int _index;

    public OnboardingWindow()
    {
        InitializeComponent();
        SlideFrame.Navigate(Slides[0]);
        UpdateButtons();
    }

    private void OnBack(object sender, RoutedEventArgs e)
    {
        if (_index == 0) return;
        _index--;
        SlideFrame.Navigate(Slides[_index]);
        UpdateButtons();
    }

    private void OnNext(object sender, RoutedEventArgs e)
    {
        if (_index >= Slides.Length - 1)
        {
            Close();
            return;
        }
        _index++;
        SlideFrame.Navigate(Slides[_index]);
        UpdateButtons();
    }

    private void UpdateButtons()
    {
        BackButton.IsEnabled = _index > 0;
        NextButton.Content = _index == Slides.Length - 1 ? "Finish" : "Next";
    }
}
