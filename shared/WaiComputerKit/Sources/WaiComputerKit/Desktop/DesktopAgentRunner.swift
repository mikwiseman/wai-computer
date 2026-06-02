#if canImport(AppKit)
import AppKit
import Foundation

/// Drives the Mac-edge channel for this device: builds a ``MacEdgeCoordinator``
/// (this app's API client as transport, the tiered ``DesktopActionExecutor``
/// over the deterministic Tier-A actuator) and polls it on an interval —
/// heartbeat → drain approved desktop actions → execute → report.
///
/// Opt-in and lifecycle live in the app: it should run only while the user is on
/// the assistant surface AND has enabled computer-use (default off), never a
/// silent 24/7 loop. The channel only ever executes actions the user already
/// approved in-app, and the safety policy excludes WaiComputer's own bundle.
/// Errors are surfaced (``lastError``), not swallowed; a transient failure does
/// not kill the loop.
@MainActor
public final class DesktopAgentRunner: ObservableObject {
    private let pollInterval: Duration
    private let deviceName: String?
    private var coordinator: MacEdgeCoordinator?
    private var task: Task<Void, Never>?

    @Published public private(set) var isRunning = false
    @Published public private(set) var lastError: String?

    public init(deviceName: String? = nil, pollInterval: Duration = .seconds(5)) {
        self.deviceName = deviceName
        self.pollInterval = pollInterval
    }

    /// Begin polling with this app's API client. Idempotent — a second call
    /// while running is a no-op. The coordinator (and its device identity) is
    /// built once and reused across start/stop cycles.
    public func start(apiClient: APIClient) {
        guard task == nil else { return }
        let coordinator = self.coordinator
            ?? Self.makeCoordinator(apiClient: apiClient, deviceName: deviceName)
        self.coordinator = coordinator
        isRunning = true
        let interval = pollInterval
        task = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    _ = try await coordinator.pollOnce()
                    self?.lastError = nil
                } catch {
                    // Surface, don't swallow; keep polling through transient blips.
                    self?.lastError = String(describing: error)
                }
                try? await Task.sleep(for: interval)
            }
        }
    }

    /// Stop polling. Idempotent.
    public func stop() {
        task?.cancel()
        task = nil
        isRunning = false
    }

    private static func makeCoordinator(
        apiClient: APIClient, deviceName: String?
    ) -> MacEdgeCoordinator {
        let ownBundleId = Bundle.main.bundleIdentifier ?? "is.waiwai.computer"
        let executor = DesktopActionExecutor(
            router: DesktopActionRouter(safety: DesktopSafetyPolicy(ownBundleId: ownBundleId)),
            actuator: DeterministicDesktopActuator()
        )
        return MacEdgeCoordinator(
            transport: apiClient, executor: executor, deviceName: deviceName
        )
    }
}
#endif
