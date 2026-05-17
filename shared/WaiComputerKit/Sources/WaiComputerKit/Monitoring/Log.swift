import Foundation
import os

/// Centralized logging namespace to keep diagnostics organized without overloading the console.
public enum Log {
    public static let app = Logger(subsystem: "is.waiwai.computer.kit", category: "App")
    public static let api = Logger(subsystem: "is.waiwai.computer.kit", category: "API")
    public static let audio = Logger(subsystem: "is.waiwai.computer.kit", category: "Audio")
    public static let dictation = Logger(subsystem: "is.waiwai.computer.kit", category: "Dictation")
    public static let recording = Logger(subsystem: "is.waiwai.computer.kit", category: "Recording")
    public static let ui = Logger(subsystem: "is.waiwai.computer.kit", category: "UI")
}
