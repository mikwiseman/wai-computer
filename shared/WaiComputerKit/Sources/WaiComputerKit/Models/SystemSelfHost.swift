import Foundation

public enum DeploymentMode: String, Codable, Sendable {
    case waiCloud = "wai_cloud"
    case selfHost = "self_host"
    case provisioning
}

public struct SystemInfo: Codable, Sendable, Equatable {
    public let appName: String
    public let deploymentMode: DeploymentMode
    public let publicBaseURL: String
    public let cloudBaseURL: String
    public let mcpURL: String
    public let gitSHA: String?
    public let gitDirty: Bool
    public let audioRetentionPolicy: String
    public let selfHostingAvailable: Bool
    public let billingMode: String

    public init(
        appName: String,
        deploymentMode: DeploymentMode,
        publicBaseURL: String,
        cloudBaseURL: String,
        mcpURL: String,
        gitSHA: String?,
        gitDirty: Bool,
        audioRetentionPolicy: String,
        selfHostingAvailable: Bool,
        billingMode: String
    ) {
        self.appName = appName
        self.deploymentMode = deploymentMode
        self.publicBaseURL = publicBaseURL
        self.cloudBaseURL = cloudBaseURL
        self.mcpURL = mcpURL
        self.gitSHA = gitSHA
        self.gitDirty = gitDirty
        self.audioRetentionPolicy = audioRetentionPolicy
        self.selfHostingAvailable = selfHostingAvailable
        self.billingMode = billingMode
    }

    private enum CodingKeys: String, CodingKey {
        case appName = "app_name"
        case deploymentMode = "deployment_mode"
        case publicBaseURL = "public_base_url"
        case cloudBaseURL = "cloud_base_url"
        case mcpURL = "mcp_url"
        case gitSHA = "git_sha"
        case gitDirty = "git_dirty"
        case audioRetentionPolicy = "audio_retention_policy"
        case selfHostingAvailable = "self_hosting_available"
        case billingMode = "billing_mode"
    }
}

public enum OwnershipClassification: String, Codable, Sendable {
    case ownedExportable = "owned_exportable"
    case selfHostLocal = "self_host_local"
    case hostedControlPlane = "hosted_control_plane"
    case reconnectRequired = "reconnect_required"
    case excludedWithReason = "excluded_with_reason"
}

public struct OwnershipEntry: Codable, Sendable, Equatable, Identifiable {
    public let name: String
    public let table: String?
    public let classification: OwnershipClassification
    public let reason: String
    public let containsUserContent: Bool
    public let requiresReconnect: Bool
    public let pathHint: String?

    public var id: String { name }

    public init(
        name: String,
        table: String?,
        classification: OwnershipClassification,
        reason: String,
        containsUserContent: Bool,
        requiresReconnect: Bool,
        pathHint: String?
    ) {
        self.name = name
        self.table = table
        self.classification = classification
        self.reason = reason
        self.containsUserContent = containsUserContent
        self.requiresReconnect = requiresReconnect
        self.pathHint = pathHint
    }

    private enum CodingKeys: String, CodingKey {
        case name
        case table
        case classification
        case reason
        case containsUserContent = "contains_user_content"
        case requiresReconnect = "requires_reconnect"
        case pathHint = "path_hint"
    }
}

public struct DataOwnershipMap: Codable, Sendable, Equatable {
    public let audioRetentionPolicy: String
    public let tables: [OwnershipEntry]
    public let artifacts: [OwnershipEntry]

    public init(
        audioRetentionPolicy: String,
        tables: [OwnershipEntry],
        artifacts: [OwnershipEntry]
    ) {
        self.audioRetentionPolicy = audioRetentionPolicy
        self.tables = tables
        self.artifacts = artifacts
    }

    private enum CodingKeys: String, CodingKey {
        case audioRetentionPolicy = "audio_retention_policy"
        case tables
        case artifacts
    }
}

public enum SelfHostAuthMethod: String, Codable, Sendable, CaseIterable, Identifiable {
    case password
    case sshKey = "ssh_key"

    public var id: String { rawValue }
}

public struct SelfHostProvisionRequest: Codable, Sendable {
    public let hostname: String?
    public let vpsIP: String
    public let sshUsername: String
    public let authMethod: SelfHostAuthMethod
    public let sshPublicKey: String?
    public let sshPassword: String?

    public init(
        hostname: String?,
        vpsIP: String,
        sshUsername: String,
        authMethod: SelfHostAuthMethod,
        sshPublicKey: String?,
        sshPassword: String?
    ) {
        self.hostname = hostname
        self.vpsIP = vpsIP
        self.sshUsername = sshUsername
        self.authMethod = authMethod
        self.sshPublicKey = sshPublicKey
        self.sshPassword = sshPassword
    }

    private enum CodingKeys: String, CodingKey {
        case hostname
        case vpsIP = "vps_ip"
        case sshUsername = "ssh_username"
        case authMethod = "auth_method"
        case sshPublicKey = "ssh_public_key"
        case sshPassword = "ssh_password"
    }
}

public struct SelfHostProvisionStep: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let label: String
    public let status: String

    public init(id: String, label: String, status: String) {
        self.id = id
        self.label = label
        self.status = status
    }
}

public struct SelfHostProvisionResponse: Codable, Sendable, Equatable {
    public let jobID: String
    public let status: String
    public let hostname: String?
    public let vpsIP: String
    public let steps: [SelfHostProvisionStep]
    public let message: String

    public init(
        jobID: String,
        status: String,
        hostname: String?,
        vpsIP: String,
        steps: [SelfHostProvisionStep],
        message: String
    ) {
        self.jobID = jobID
        self.status = status
        self.hostname = hostname
        self.vpsIP = vpsIP
        self.steps = steps
        self.message = message
    }

    private enum CodingKeys: String, CodingKey {
        case jobID = "job_id"
        case status
        case hostname
        case vpsIP = "vps_ip"
        case steps
        case message
    }
}
