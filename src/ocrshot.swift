import AppKit
import Vision
import Foundation
import CoreGraphics

// Usage: ocrshot <path-to-image>
// Prints recognized lines (one per line).

func recognizeText(from imageURL: URL) -> [String] {
    guard let nsImage = NSImage(contentsOf: imageURL) else { return [] }
    var rect = NSRect(x: 0, y: 0, width: nsImage.size.width, height: nsImage.size.height)
    guard let cgImage = nsImage.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { return [] }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.automaticallyDetectsLanguage = true

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
    } catch {
        return []
    }

    guard let observations = request.results as? [VNRecognizedTextObservation] else { return [] }
    var lines: [String] = []
    for obs in observations {
        if let cand = obs.topCandidates(1).first {
            lines.append(cand.string)
        }
    }
    return lines
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    exit(2)
}
let path = args[1]
let url = URL(fileURLWithPath: path)
let lines = recognizeText(from: url)

for l in lines {
    print(l)
}
