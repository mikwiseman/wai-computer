using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Auth;

namespace WaiComputer.Core.ViewModels;

/// <summary>High-level auth lifecycle the app shell binds to decide which surface to show.</summary>
public enum AuthStatus
{
    /// <summary>Launch state before <see cref="AuthViewModel.RestoreSessionAsync"/> resolves.</summary>
    Unknown,
    SignedOut,
    Authenticating,
    SignedIn,
}

/// <summary>
/// Portable auth/session ViewModel shared by the Windows (WinUI) and Linux
/// (Avalonia) shells. Ports the macOS sign-in flow: password login, magic-link
/// request + <c>waicomputer://auth/verify</c> URL verification, session restore on
/// launch, and sign-out. Persists tokens to <see cref="SessionStore"/> on every
/// auth success and whenever the API client transparently refreshes them, so a
/// cdhash/ACL-stable file survives restarts. Errors surface on
/// <see cref="ErrorMessage"/> — no silent degradation.
/// </summary>
public sealed partial class AuthViewModel : ObservableObject, IDisposable
{
    private readonly IApiClient _api;
    private readonly SessionStore _sessionStore;
    private readonly string _client;
    private readonly ILogger<AuthViewModel> _logger;

    [ObservableProperty] private AuthStatus _status = AuthStatus.Unknown;
    [ObservableProperty] private User? _currentUser;
    [ObservableProperty] private string _email = string.Empty;
    [ObservableProperty] private string _password = string.Empty;
    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private string? _errorMessage;
    [ObservableProperty] private string? _infoMessage;

    public IAsyncRelayCommand SignInCommand { get; }
    public IAsyncRelayCommand SendMagicLinkCommand { get; }
    public IAsyncRelayCommand SignOutCommand { get; }

    /// <summary>Raised when the user becomes authenticated (shell navigates to the main surface).</summary>
    public event Action<User>? SignedIn;
    /// <summary>Raised when the session ends or restore finds none (shell navigates to sign-in).</summary>
    public event Action? SignedOut;

    public AuthViewModel(IApiClient api, SessionStore sessionStore, string client, ILogger<AuthViewModel>? logger = null)
    {
        _api = api;
        _sessionStore = sessionStore;
        _client = client;
        _logger = logger ?? NullLogger<AuthViewModel>.Instance;
        _api.TokenRefreshed += OnTokenRefreshed;

        SignInCommand = new AsyncRelayCommand(() => SignInWithPasswordAsync(CancellationToken.None));
        SendMagicLinkCommand = new AsyncRelayCommand(() => SendMagicLinkAsync(CancellationToken.None));
        SignOutCommand = new AsyncRelayCommand(() => SignOutAsync(CancellationToken.None));
    }

    public bool IsSignedIn => Status == AuthStatus.SignedIn;

    /// <summary>Launch path: restore a persisted session and validate it against the server.</summary>
    public async Task RestoreSessionAsync(CancellationToken ct = default)
    {
        var session = _sessionStore.Load();
        if (session is null)
        {
            TransitionSignedOut();
            return;
        }

        _api.SetAccessToken(session.AccessToken);
        _api.SetRefreshToken(session.RefreshToken);
        try
        {
            var user = await _api.GetCurrentUserAsync(ct).ConfigureAwait(false);
            TransitionSignedIn(user);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            // Token rejected / network down at launch: clear it and fall back to sign-in.
            _logger.LogInformation(ex, "Session restore failed; clearing stored session");
            _sessionStore.Clear();
            _api.SetAccessToken(null);
            _api.SetRefreshToken(null);
            TransitionSignedOut();
        }
    }

    public async Task SignInWithPasswordAsync(CancellationToken ct = default)
    {
        if (IsBusy)
        {
            return;
        }
        var email = Email.Trim();
        if (email.Length == 0 || !email.Contains('@'))
        {
            ErrorMessage = "Enter a valid email address.";
            return;
        }
        if (Password.Length == 0)
        {
            ErrorMessage = "Enter your password.";
            return;
        }

        IsBusy = true;
        ErrorMessage = null;
        InfoMessage = null;
        Status = AuthStatus.Authenticating;
        try
        {
            var auth = await _api.LoginAsync(email, Password, ct).ConfigureAwait(false);
            await CompleteAuthenticationAsync(auth, ct).ConfigureAwait(false);
            Password = string.Empty;
        }
        catch (OperationCanceledException)
        {
            Status = AuthStatus.SignedOut;
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Password sign-in failed");
            ErrorMessage = "Sign-in failed. Check your email and password.";
            Status = AuthStatus.SignedOut;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task SendMagicLinkAsync(CancellationToken ct = default)
    {
        if (IsBusy)
        {
            return;
        }
        var email = Email.Trim();
        if (email.Length == 0 || !email.Contains('@'))
        {
            ErrorMessage = "Enter a valid email address.";
            return;
        }

        IsBusy = true;
        ErrorMessage = null;
        InfoMessage = null;
        try
        {
            var response = await _api.RequestMagicLinkAsync(email, _client, ct).ConfigureAwait(false);
            InfoMessage = string.IsNullOrWhiteSpace(response.Message)
                ? "Check your email for a sign-in link."
                : response.Message;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Magic-link request failed");
            ErrorMessage = "Couldn't send the sign-in link. Try again.";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>Handle an incoming <c>waicomputer://auth/verify?token=...</c> deep link.</summary>
    public async Task<bool> HandleMagicLinkUrlAsync(string url, CancellationToken ct = default)
    {
        if (!MagicLinkUrl.TryParse(url, out var token))
        {
            ErrorMessage = "That sign-in link is invalid or expired.";
            return false;
        }

        IsBusy = true;
        ErrorMessage = null;
        InfoMessage = null;
        Status = AuthStatus.Authenticating;
        try
        {
            var auth = await _api.VerifyMagicLinkAsync(token, ct).ConfigureAwait(false);
            await CompleteAuthenticationAsync(auth, ct).ConfigureAwait(false);
            return true;
        }
        catch (OperationCanceledException)
        {
            Status = AuthStatus.SignedOut;
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Magic-link verification failed");
            ErrorMessage = "That sign-in link is invalid or expired.";
            Status = AuthStatus.SignedOut;
            return false;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task SignOutAsync(CancellationToken ct = default)
    {
        try
        {
            await _api.LogoutAsync(_api.GetRefreshToken(), ct).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            // Best-effort server revoke; local sign-out must always succeed.
            _logger.LogInformation(ex, "Server logout failed; clearing local session anyway");
        }

        _sessionStore.Clear();
        _api.SetAccessToken(null);
        _api.SetRefreshToken(null);
        Password = string.Empty;
        TransitionSignedOut();
    }

    private async Task CompleteAuthenticationAsync(AuthResponse auth, CancellationToken ct)
    {
        _sessionStore.Save(auth.AccessToken, auth.RefreshToken);
        _api.SetAccessToken(auth.AccessToken);
        _api.SetRefreshToken(auth.RefreshToken);
        var user = await _api.GetCurrentUserAsync(ct).ConfigureAwait(false);
        TransitionSignedIn(user);
    }

    private void TransitionSignedIn(User user)
    {
        CurrentUser = user;
        ErrorMessage = null;
        Status = AuthStatus.SignedIn;
        OnPropertyChanged(nameof(IsSignedIn));
        SignedIn?.Invoke(user);
    }

    private void TransitionSignedOut()
    {
        CurrentUser = null;
        Status = AuthStatus.SignedOut;
        OnPropertyChanged(nameof(IsSignedIn));
        SignedOut?.Invoke();
    }

    private void OnTokenRefreshed(string accessToken, string? refreshToken)
    {
        // The API client transparently refreshed the access token — persist it so the
        // next launch restores the live session rather than a stale one.
        try
        {
            _sessionStore.Save(accessToken, refreshToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Persisting refreshed token failed");
        }
    }

    public void Dispose() => _api.TokenRefreshed -= OnTokenRefreshed;
}
