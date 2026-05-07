import XCTest
@testable import WaiSay

final class BetaChannelStoreTests: XCTestCase {
    func testAllowedChannelsIncludesBetaOnlyWhenOptedIn() {
        XCTAssertEqual(BetaChannelStore.allowedChannels(isOptedIn: false), Set<String>())
        XCTAssertEqual(BetaChannelStore.allowedChannels(isOptedIn: true), Set([BetaChannelStore.channelName]))
    }
}
