import Vision
import AppKit
for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    try? VNImageRequestHandler(cgImage: cg).perform([req])
    let obs = (req.results ?? []).sorted { $0.boundingBox.maxY > $1.boundingBox.maxY }
    print("== \(path)")
    for o in obs {
        if let t = o.topCandidates(1).first {
            let b = o.boundingBox
            print(String(format: "%.3f %.3f %.3f %.3f\t", b.minX, 1 - b.maxY, b.maxX, 1 - b.minY) + t.string)
        }
    }
}
