import AVFoundation
import Foundation
import os

/// Single source of truth for which media files the apps can import as
/// recordings, mirroring the backend's `app/core/media_audio.py` tables: any
/// container ffmpeg can demux is importable — provider-ready audio uploads
/// as-is, video is reduced to its audio track (locally when AVFoundation can
/// export it, otherwise by the server's ffmpeg pipeline).
public enum MediaImportSupport {

    public static let audioExtensions: [String] = [
        "mp3", "wav", "m4a", "aac", "ogg", "oga", "opus", "webm", "flac",
        "aiff", "aif", "wma", "amr", "mka", "caf",
    ]

    public static let videoExtensions: [String] = [
        "mp4", "mov", "m4v", "mkv", "avi", "mpg", "mpeg", "wmv", "flv",
        "3gp", "3g2", "ts", "mts",
    ]

    /// Every extension the import pickers offer. `webm` lives in both worlds;
    /// the server resolves it by content.
    public static let importableExtensions: [String] = audioExtensions + videoExtensions

    public static func isVideoExtension(_ ext: String) -> Bool {
        videoExtensions.contains(ext.lowercased())
    }

    /// MIME type for the multipart upload, matching the backend's
    /// EXTENSION_TO_CONTENT_TYPE so `resolve_import_extension` round-trips.
    public static func mimeType(forExtension ext: String) -> String {
        switch ext.lowercased() {
        case "mp3": return "audio/mpeg"
        case "wav": return "audio/wav"
        case "m4a": return "audio/mp4"
        case "aac": return "audio/aac"
        case "ogg", "oga": return "audio/ogg"
        case "opus": return "audio/opus"
        case "webm": return "audio/webm"
        case "flac": return "audio/flac"
        case "aiff", "aif": return "audio/aiff"
        case "wma": return "audio/x-ms-wma"
        case "amr": return "audio/amr"
        case "mka": return "audio/x-matroska"
        case "caf": return "audio/x-caf"
        case "mp4": return "video/mp4"
        case "mov": return "video/quicktime"
        case "m4v": return "video/x-m4v"
        case "mkv": return "video/x-matroska"
        case "avi": return "video/x-msvideo"
        case "mpg", "mpeg": return "video/mpeg"
        case "wmv": return "video/x-ms-wmv"
        case "flv": return "video/x-flv"
        case "3gp": return "video/3gpp"
        case "3g2": return "video/3gpp2"
        case "ts", "mts": return "video/mp2t"
        default: return "application/octet-stream"
        }
    }
}

/// Extracts the audio track from a video before upload, so a 200 MB screen
/// recording uploads as a ~20 MB `.m4a` instead of the full container.
public enum MediaAudioExtractor {

    private static let log = Logger(subsystem: "is.waiwai.computer", category: "media-import")

    /// Extracts the first audio track of an AVFoundation-readable video into a
    /// temporary `.m4a`. Returns nil when this container/codec can't be
    /// exported locally (e.g. mkv/avi) — the caller then uploads the original
    /// video and the server's ffmpeg pipeline extracts the audio instead.
    /// The caller owns deleting the returned temp file.
    public static func extractAudioForUpload(source: URL) async -> URL? {
        let asset = AVURLAsset(url: source)
        guard
            let audioTracks = try? await asset.loadTracks(withMediaType: .audio),
            !audioTracks.isEmpty
        else {
            log.info("local audio extraction skipped: no readable audio track")
            return nil
        }
        guard
            let session = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetAppleM4A)
        else {
            log.info("local audio extraction skipped: no m4a export session for container")
            return nil
        }
        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent("import-audio-\(UUID().uuidString).m4a")
        session.outputURL = destination
        session.outputFileType = .m4a

        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            session.exportAsynchronously {
                continuation.resume()
            }
        }

        guard session.status == .completed else {
            let reason = session.error.map(String.init(describing:)) ?? "status \(session.status.rawValue)"
            log.warning("local audio extraction failed, uploading original: \(reason, privacy: .public)")
            try? FileManager.default.removeItem(at: destination)
            return nil
        }
        let size = (try? destination.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        guard size > 0 else {
            try? FileManager.default.removeItem(at: destination)
            return nil
        }
        log.info("extracted audio track for upload bytes=\(size, privacy: .public)")
        return destination
    }
}
