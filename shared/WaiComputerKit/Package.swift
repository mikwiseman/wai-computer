// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "WaiComputerKit",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(
            name: "WaiComputerKit",
            targets: ["WaiComputerKit"]
        ),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-async-algorithms", from: "1.0.0"),
    ],
    targets: [
        .target(
            name: "WaiComputerKit",
            dependencies: [
                .product(name: "AsyncAlgorithms", package: "swift-async-algorithms"),
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
