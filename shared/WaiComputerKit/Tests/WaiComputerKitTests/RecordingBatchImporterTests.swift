import XCTest

@testable import WaiComputerKit

@MainActor
final class RecordingBatchImporterTests: XCTestCase {
    func testImportSequentiallyContinuesAfterFailureAndPreservesOrder() async {
        let files = [
            URL(fileURLWithPath: "/tmp/one.wav"),
            URL(fileURLWithPath: "/tmp/two.wav"),
            URL(fileURLWithPath: "/tmp/three.wav"),
        ]
        var events: [String] = []
        var activeImports = 0
        var maximumActiveImports = 0

        let summary = await RecordingBatchImporter.importSequentially(
            files: files,
            onProgress: { index, total, file in
                events.append("progress:\(index)/\(total):\(file.lastPathComponent)")
            },
            importFile: { file in
                activeImports += 1
                maximumActiveImports = max(maximumActiveImports, activeImports)
                events.append("start:\(file.lastPathComponent)")
                await Task.yield()
                activeImports -= 1

                if file.lastPathComponent == "two.wav" {
                    return .failure(
                        RecordingImportFailure(
                            filename: file.lastPathComponent,
                            message: "Upload failed."
                        )
                    )
                }
                return .success(
                    Recording(
                        id: file.deletingPathExtension().lastPathComponent,
                        title: file.deletingPathExtension().lastPathComponent,
                        type: .note
                    )
                )
            }
        )

        XCTAssertEqual(maximumActiveImports, 1)
        XCTAssertEqual(summary.totalCount, 3)
        XCTAssertEqual(summary.importedCount, 2)
        XCTAssertEqual(summary.recordings.map(\.id), ["one", "three"])
        XCTAssertEqual(summary.failures.map(\.filename), ["two.wav"])
        XCTAssertNil(summary.singleRecording)
        XCTAssertEqual(
            events,
            [
                "progress:1/3:one.wav",
                "start:one.wav",
                "progress:2/3:two.wav",
                "start:two.wav",
                "progress:3/3:three.wav",
                "start:three.wav",
            ]
        )
    }

    func testSingleSuccessfulImportExposesRecordingForDetailNavigation() async {
        let file = URL(fileURLWithPath: "/tmp/meeting.m4a")

        let summary = await RecordingBatchImporter.importSequentially(
            files: [file],
            onProgress: { _, _, _ in },
            importFile: { _ in
                .success(Recording(id: "meeting", title: "meeting", type: .note))
            }
        )

        XCTAssertEqual(summary.singleRecording?.id, "meeting")
        XCTAssertNil(summary.failureMessage(language: .english))
    }

    func testFailureMessageSummarizesPartialBatchInBothLanguages() {
        let summary = RecordingImportSummary(
            totalCount: 3,
            recordings: [
                Recording(id: "one", title: "one", type: .note),
                Recording(id: "three", title: "three", type: .note),
            ],
            failures: [
                RecordingImportFailure(filename: "two.wav", message: "Upload failed."),
            ]
        )

        XCTAssertEqual(
            summary.failureMessage(language: .english),
            """
            Imported 2 of 3 files.

            Couldn’t import:
            • two.wav — Upload failed.
            """
        )
        XCTAssertEqual(
            summary.failureMessage(language: .russian),
            """
            Импортировано: 2 из 3.

            Не удалось импортировать:
            • two.wav — Upload failed.
            """
        )
    }
}
