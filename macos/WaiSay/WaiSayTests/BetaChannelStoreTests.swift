import XCTest

final class BetaChannelStoreTests: XCTestCase {
    func testAllowedChannelsIncludesBetaOnlyWhenOptedIn() {
        XCTAssertEqual(BetaChannelStore.allowedChannels(isOptedIn: false), Set<String>())
        XCTAssertEqual(BetaChannelStore.allowedChannels(isOptedIn: true), Set([BetaChannelStore.channelName]))
    }
}
