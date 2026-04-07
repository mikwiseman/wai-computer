// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "WaiSayKit",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(
            name: "WaiSayKit",
            targets: ["WaiSayKit"]
        ),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-async-algorithms", from: "1.0.0"),
        .package(url: "https://github.com/getsentry/sentry-cocoa", from: "8.45.0"),
    ],
    targets: [
        .target(
            name: "WaiSayKit",
            dependencies: [
                .product(name: "AsyncAlgorithms", package: "swift-async-algorithms"),
                .product(name: "Sentry", package: "sentry-cocoa"),
            ],
            path: "Sources/WaiSayKit"
        ),
        .testTarget(
            name: "WaiSayKitTests",
            dependencies: ["WaiSayKit"],
            path: "Tests/WaiSayKitTests"
        ),
    ]
)
