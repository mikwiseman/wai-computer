import Foundation
import os

/// Centralized logging namespace to keep diagnostics organized without overloading the console.
public enum Log {
    public static let app = Logger(subsystem: "com.waisay.kit", category: "App")
    public static let api = Logger(subsystem: "com.waisay.kit", category: "API")
    public static let audio = Logger(subsystem: "com.waisay.kit", category: "Audio")
    public static let dictation = Logger(subsystem: "com.waisay.kit", category: "Dictation")
    public static let recording = Logger(subsystem: "com.waisay.kit", category: "Recording")
    public static let ui = Logger(subsystem: "com.waisay.kit", category: "UI")
}
