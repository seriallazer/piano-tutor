#!/usr/bin/env swift

import Foundation
import Vision

struct OCRLine: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct OCRPage: Codable {
    let path: String
    let lines: [OCRLine]
    let error: String?
}

func recognize(path: String) -> OCRPage {
    let url = URL(fileURLWithPath: path)
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true

    do {
        try VNImageRequestHandler(url: url, options: [:]).perform([request])
        let observations = request.results ?? []
        let lines = observations.compactMap { observation -> OCRLine? in
            guard let candidate = observation.topCandidates(1).first else { return nil }
            let box = observation.boundingBox
            return OCRLine(
                text: candidate.string,
                confidence: candidate.confidence,
                x: box.origin.x,
                y: box.origin.y,
                width: box.size.width,
                height: box.size.height
            )
        }.sorted {
            if abs($0.y - $1.y) > 0.01 { return $0.y > $1.y }
            return $0.x < $1.x
        }
        return OCRPage(path: path, lines: lines, error: nil)
    } catch {
        return OCRPage(path: path, lines: [], error: error.localizedDescription)
    }
}

let paths = Array(CommandLine.arguments.dropFirst())
guard !paths.isEmpty else {
    FileHandle.standardError.write(Data("Usage: apple_vision_ocr.swift IMAGE [IMAGE ...]\n".utf8))
    exit(2)
}

let pages = paths.map(recognize)
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
do {
    let data = try encoder.encode(pages)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    FileHandle.standardError.write(Data("Could not encode OCR output: \(error)\n".utf8))
    exit(1)
}
