using FluentAssertions;
using WaiComputer.Core.Api;
using Xunit;

namespace WaiComputer.Core.Tests.Api;

public class ApiErrorTests
{
    [Fact]
    public void UnauthorizedAuthContextReadsAsInvalidCredentials()
    {
        new ApiError.Unauthorized().UserFacingMessage(ErrorContext.Authentication)
            .Should().Be("Invalid credentials");
    }

    [Fact]
    public void HttpErrorPrefersServerMessage()
    {
        new ApiError.HttpError(400, "Title required")
            .UserFacingMessage(ErrorContext.Generic).Should().Be("Title required");
    }

    [Fact]
    public void Server5xxFallsBackToFriendlyMessage()
    {
        new ApiError.HttpError(500, null)
            .UserFacingMessage(ErrorContext.Generic).Should().Contain("trouble");
    }

    [Fact]
    public void RateLimitedHasOwnPhrase()
    {
        new ApiError.HttpError(429, null)
            .UserFacingMessage(ErrorContext.Generic).Should().Contain("Too many");
    }

    [Fact]
    public void NetworkSurfacesReason()
    {
        new ApiError.Network("DNS lookup failed")
            .UserFacingMessage(ErrorContext.Generic).Should().Contain("DNS lookup failed");
    }
}
