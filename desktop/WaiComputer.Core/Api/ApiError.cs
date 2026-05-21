namespace WaiComputer.Core.Api;

/// <summary>
/// Categorised failure modes returned by <see cref="ApiClient"/>.
/// Mirrors the Swift <c>APIError</c> enum in <c>WaiComputerKit</c>.
/// </summary>
public abstract class ApiError : Exception
{
    protected ApiError(string message) : base(message) { }
    protected ApiError(string message, Exception inner) : base(message, inner) { }

    public sealed class InvalidUrl : ApiError
    {
        public InvalidUrl(string detail) : base($"Invalid URL: {detail}") { }
    }

    public sealed class NoData : ApiError
    {
        public NoData() : base("Empty response body when one was expected.") { }
    }

    public sealed class Decoding : ApiError
    {
        public Decoding(string detail, Exception inner) : base($"Failed to decode response: {detail}", inner) { }
    }

    public sealed class HttpError : ApiError
    {
        public int StatusCode { get; }
        public string? ServerMessage { get; }
        public HttpError(int statusCode, string? serverMessage)
            : base($"HTTP {statusCode}{(serverMessage is null ? string.Empty : $": {serverMessage}")}")
        {
            StatusCode = statusCode;
            ServerMessage = serverMessage;
        }
    }

    public sealed class Network : ApiError
    {
        public string Reason { get; }
        public Network(string reason, Exception? inner = null)
            : base($"Network error: {reason}", inner ?? new InvalidOperationException(reason))
        {
            Reason = reason;
        }
    }

    public sealed class Unauthorized : ApiError
    {
        public Unauthorized() : base("Unauthorized — token refresh failed or missing.") { }
    }

    /// <summary>
    /// Human-facing message suitable for a banner / dialog. Keep terse; the
    /// backend's <c>detail</c> field is preferred when available.
    /// </summary>
    public string UserFacingMessage(ErrorContext context) => this switch
    {
        Unauthorized => context == ErrorContext.Authentication ? "Invalid credentials" : "Please sign in again.",
        HttpError h when h.ServerMessage is not null => h.ServerMessage,
        HttpError { StatusCode: >= 500 } => "The WaiComputer server is having trouble. Please try again.",
        HttpError { StatusCode: 429 } => "Too many requests. Please slow down for a moment.",
        HttpError h => $"Request failed with status {h.StatusCode}.",
        Network n => n.Reason,
        Decoding => "The response from WaiComputer wasn't understood. Please try again.",
        _ => "Something went wrong."
    };
}

public enum ErrorContext
{
    Generic,
    Authentication,
    Recording,
    Dictation,
}
