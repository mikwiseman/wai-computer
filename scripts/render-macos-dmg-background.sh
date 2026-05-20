#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
OUTPUT_PATH=${1:?"usage: render-macos-dmg-background.sh <output-path> [icon-path] [base-background]"}
ICON_PATH=${2:-"$ROOT_DIR/assets/app-icon-1024.png"}
BASE_BACKGROUND_PATH=${3:-}

mkdir -p "$(dirname "$OUTPUT_PATH")"

swift - "$OUTPUT_PATH" "$ICON_PATH" "$BASE_BACKGROUND_PATH" <<'SWIFT'
import AppKit
import Foundation

let outputPath = CommandLine.arguments[1]
let iconPath = CommandLine.arguments[2]
let baseBackgroundPath = CommandLine.arguments.count > 3 ? CommandLine.arguments[3] : ""

guard FileManager.default.fileExists(atPath: iconPath) else {
    fputs("Icon file not found: \(iconPath)\n", stderr)
    exit(1)
}

let width: CGFloat = 960
let height: CGFloat = 620
let canvasRect = NSRect(x: 0, y: 0, width: width, height: height)
guard
    let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: Int(width),
        pixelsHigh: Int(height),
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ),
    let graphicsContext = NSGraphicsContext(bitmapImageRep: bitmap)
else {
    fputs("Failed to create DMG background bitmap context\n", stderr)
    exit(1)
}
bitmap.size = canvasRect.size

func drawCover(_ image: NSImage, in targetRect: NSRect, fraction: CGFloat) {
    let sourceSize = image.size
    guard sourceSize.width > 0, sourceSize.height > 0 else { return }

    let scale = max(targetRect.width / sourceSize.width, targetRect.height / sourceSize.height)
    let drawSize = NSSize(width: sourceSize.width * scale, height: sourceSize.height * scale)
    let drawRect = NSRect(
        x: targetRect.midX - drawSize.width / 2,
        y: targetRect.midY - drawSize.height / 2,
        width: drawSize.width,
        height: drawSize.height
    )

    NSGraphicsContext.current?.cgContext.saveGState()
    targetRect.clip()
    image.draw(in: drawRect, from: .zero, operation: .sourceOver, fraction: fraction)
    NSGraphicsContext.current?.cgContext.restoreGState()
}

func drawCurvedLine(from start: NSPoint, control1: NSPoint, control2: NSPoint, to end: NSPoint, alpha: CGFloat) {
    let path = NSBezierPath()
    path.move(to: start)
    path.curve(to: end, controlPoint1: control1, controlPoint2: control2)
    path.lineWidth = 2
    NSColor(calibratedWhite: 0.13, alpha: alpha).setStroke()
    path.stroke()
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = graphicsContext
graphicsContext.imageInterpolation = .high

if !baseBackgroundPath.isEmpty, let base = NSImage(contentsOfFile: baseBackgroundPath) {
    NSColor(red: 246 / 255, green: 244 / 255, blue: 238 / 255, alpha: 1).setFill()
    canvasRect.fill()
    drawCover(base, in: canvasRect, fraction: 0.16)
} else {
    let gradient = NSGradient(
        starting: NSColor(red: 248 / 255, green: 246 / 255, blue: 241 / 255, alpha: 1),
        ending: NSColor(red: 242 / 255, green: 240 / 255, blue: 235 / 255, alpha: 1)
    )
    gradient?.draw(in: canvasRect, angle: -90)

    drawCurvedLine(
        from: NSPoint(x: -62, y: 176),
        control1: NSPoint(x: 108, y: 44),
        control2: NSPoint(x: 282, y: 80),
        to: NSPoint(x: 392, y: 190),
        alpha: 0.07
    )
    drawCurvedLine(
        from: NSPoint(x: 598, y: 526),
        control1: NSPoint(x: 742, y: 666),
        control2: NSPoint(x: 984, y: 582),
        to: NSPoint(x: 1030, y: 340),
        alpha: 0.06
    )
}

let guidePath = NSBezierPath()
guidePath.move(to: NSPoint(x: 406, y: height - 352))
guidePath.line(to: NSPoint(x: 552, y: height - 352))
guidePath.lineWidth = 3
NSColor(calibratedWhite: 0.1, alpha: 0.63).setStroke()
guidePath.stroke()

let arrowPath = NSBezierPath()
arrowPath.move(to: NSPoint(x: 552, y: height - 352))
arrowPath.line(to: NSPoint(x: 536, y: height - 342))
arrowPath.line(to: NSPoint(x: 536, y: height - 362))
arrowPath.close()
NSColor(calibratedWhite: 0.1, alpha: 0.63).setFill()
arrowPath.fill()

let font = NSFont(name: "Avenir Next", size: 26) ?? NSFont.systemFont(ofSize: 26, weight: .medium)
let attributes: [NSAttributedString.Key: Any] = [
    .font: font,
    .foregroundColor: NSColor(calibratedWhite: 0.09, alpha: 0.77)
]
let title = NSString(string: "Drag to Applications")
let titleSize = title.size(withAttributes: attributes)
title.draw(
    at: NSPoint(x: (width - titleSize.width) / 2, y: height - 92 - titleSize.height),
    withAttributes: attributes
)

NSGraphicsContext.restoreGraphicsState()

guard
    let png = bitmap.representation(using: .png, properties: [:])
else {
    fputs("Failed to render DMG background PNG\n", stderr)
    exit(1)
}

try FileManager.default.createDirectory(
    at: URL(fileURLWithPath: outputPath).deletingLastPathComponent(),
    withIntermediateDirectories: true
)
try png.write(to: URL(fileURLWithPath: outputPath), options: .atomic)
SWIFT
