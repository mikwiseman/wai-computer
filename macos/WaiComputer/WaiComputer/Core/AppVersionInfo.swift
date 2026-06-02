import Foundation

struct AppVersionInfo: Equatable {
    enum Error: Swift.Error, Equatable, CustomStringConvertible {
        case missingInfoDictionary
        case missingMarketingVersion
        case missingBuildNumber

        var description: String {
            switch self {
            case .missingInfoDictionary:
                return "Bundle info dictionary is missing"
            case .missingMarketingVersion:
                return "CFBundleShortVersionString is missing"
            case .missingBuildNumber:
                return "CFBundleVersion is missing"
            }
        }
    }

    let marketingVersion: String
    let buildNumber: String

    init(marketingVersion: String, buildNumber: String) {
        self.marketingVersion = marketingVersion
        self.buildNumber = buildNumber
    }

    init(infoDictionary: [String: Any]?) throws {
        guard let infoDictionary else {
            throw Error.missingInfoDictionary
        }
        guard
            let marketingVersion = infoDictionary["CFBundleShortVersionString"] as? String,
            !marketingVersion.isEmpty
        else {
            throw Error.missingMarketingVersion
        }
        guard
            let buildNumber = infoDictionary["CFBundleVersion"] as? String,
            !buildNumber.isEmpty
        else {
            throw Error.missingBuildNumber
        }

        self.init(marketingVersion: marketingVersion, buildNumber: buildNumber)
    }

    static var main: AppVersionInfo {
        do {
            return try AppVersionInfo(infoDictionary: Bundle.main.infoDictionary)
        } catch {
            preconditionFailure("Invalid app version metadata: \(error)")
        }
    }

    var displayText: String {
        "\(marketingVersion) (\(buildNumber))"
    }

    var accessibilityText: String {
        "Version \(marketingVersion), build \(buildNumber)"
    }
}
