// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "TestSwiftClient",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/tolgaki/a2a-client-swift.git", from: "1.0.19"),
    ],
    targets: [
        .executableTarget(
            name: "TestSwiftClient",
            dependencies: [
                .product(name: "A2AClient", package: "a2a-client-swift"),
            ],
            path: "Sources"
        ),
    ]
)
