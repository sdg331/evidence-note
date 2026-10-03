// Extract Korean/English text from one rendered PDF page on macOS.
// Usage: swift scripts/ocr_page.swift /path/to/page.png

import Foundation
import Vision

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: swift ocr_page.swift /path/to/page.png\n", stderr)
    exit(2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ko-KR", "en-US"]
request.usesLanguageCorrection = true

do {
    try VNImageRequestHandler(url: imageURL, options: [:]).perform([request])
    let observations = (request.results ?? []).sorted { first, second in
        if abs(first.boundingBox.midY - second.boundingBox.midY) > 0.018 {
            return first.boundingBox.midY > second.boundingBox.midY
        }
        return first.boundingBox.minX < second.boundingBox.minX
    }
    let lines = observations.compactMap { $0.topCandidates(1).first?.string }
    print(lines.joined(separator: "\n"))
} catch {
    fputs("OCR failed: \(error)\n", stderr)
    exit(1)
}
