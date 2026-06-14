// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "WaiComputerKit",
    platforms: [
        .iOS(.v17),
        .macOS(.v13)
    ],
    products: [
        .library(
            name: "WaiComputerKit",
            targets: ["WaiComputerKit"]
        ),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-async-algorithms", from: "1.0.0"),
        .package(url: "https://github.com/getsentry/sentry-cocoa", from: "8.45.0"),
    ],
    targets: [
        .target(
            name: "WaiComputerKitObjC",
            path: "Sources/WaiComputerKitObjC",
            publicHeadersPath: "include"
        ),
        .target(
            name: "WaiComputerKit",
            dependencies: [
                "WaiComputerKitObjC",
                .product(name: "AsyncAlgorithms", package: "swift-async-algorithms"),
                .product(name: "Sentry", package: "sentry-cocoa"),
            ],
            path: "Sources/WaiComputerKit"
        ),
        .testTarget(
            name: "WaiComputerKitTests",
            dependencies: ["WaiComputerKit"],
            path: "Tests/WaiComputerKitTests"
        ),
    ]
)
