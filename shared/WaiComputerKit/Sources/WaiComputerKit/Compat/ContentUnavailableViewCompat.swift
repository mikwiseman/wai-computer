#if canImport(SwiftUI)
import SwiftUI

/// Back-compatible `ContentUnavailableView` for a single binary spanning macOS 13 -> 26.
///
/// `ContentUnavailableView` is macOS 14.0 / iOS 17.0 only. On macOS 13 this renders an
/// equivalent centered icon + title + description so empty states look right rather than
/// crash-at-compile. On macOS 14+/iOS 17+ it delegates to the native view verbatim.
///
/// Matches the `(title, systemImage:, description:)` initializer used across the app.
public struct ContentUnavailableViewCompat: View {
    private let title: String
    private let systemImage: String
    private let description: Text?

    public init(_ title: String, systemImage: String, description: Text? = nil) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
    }

    public var body: some View {
        if #available(macOS 14.0, iOS 17.0, *) {
            if let description {
                ContentUnavailableView(title, systemImage: systemImage, description: description)
            } else {
                ContentUnavailableView(title, systemImage: systemImage)
            }
        } else {
            VStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 36, weight: .regular))
                    .foregroundStyle(.secondary)
                    .padding(.bottom, 2)
                Text(title)
                    .font(.title2)
                    .fontWeight(.semibold)
                    .multilineTextAlignment(.center)
                if let description {
                    description
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding()
        }
    }
}
#endif
