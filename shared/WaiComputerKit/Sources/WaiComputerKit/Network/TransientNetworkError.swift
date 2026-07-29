import Foundation

public extension Error {
    /// True for failures that a settling network resolves by itself within
    /// seconds — waking from sleep, a Wi-Fi handoff, a dropped VPN. Callers
    /// with cached content on screen retry these silently instead of flashing
    /// an error banner at the user; anything else stays loud.
    var isTransientNetworkError: Bool {
        var candidate: any Error = self
        if let apiError = self as? APIError, case let .networkError(inner) = apiError {
            candidate = inner
        }
        guard let urlError = candidate as? URLError else { return false }
        switch urlError.code {
        case .notConnectedToInternet,
             .networkConnectionLost,
             .timedOut,
             .cannotConnectToHost,
             .cannotFindHost,
             .dnsLookupFailed,
             .dataNotAllowed,
             .internationalRoamingOff:
            return true
        default:
            return false
        }
    }
}
