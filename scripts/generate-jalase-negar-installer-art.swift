// Draws the branded artwork for the macOS DMG window and the Windows installer wizard.
// Run from the repository root:  swift scripts/generate-jalase-negar-installer-art.swift
// Writes jalase-negar/macos/dmg/background.png (+@2x) and jalase-negar/windows/installer/*.bmp.
import AppKit

let root = "jalase-negar"
let bg = NSColor(srgbRed: 75/255, green: 110/255, blue: 72/255, alpha: 1)
let bgDeep = NSColor(srgbRed: 46/255, green: 72/255, blue: 46/255, alpha: 1)
let beige = NSColor(srgbRed: 178/255, green: 172/255, blue: 136/255, alpha: 1)
let paper = NSColor(srgbRed: 242/255, green: 240/255, blue: 239/255, alpha: 1)

func font(_ file: String, _ size: CGFloat) -> NSFont {
    let url = URL(fileURLWithPath: "\(root)/assets/fonts/\(file)")
    CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
    if let provider = CGDataProvider(url: url as CFURL), let cg = CGFont(provider),
       let ps = cg.postScriptName as String?, let f = NSFont(name: ps, size: size) { return f }
    return NSFont.systemFont(ofSize: size, weight: .semibold)
}

func render(_ w: Int, _ h: Int, _ draw: (CGFloat, CGFloat) -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = ctx
    ctx.cgContext.interpolationQuality = .high
    draw(CGFloat(w), CGFloat(h))
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

// Standard bottom-up 24-bit BMP (BITMAPINFOHEADER). Inno Setup shows top-down / 32-bit BMPs flipped.
func saveBMP(_ rep: NSBitmapImageRep, _ path: String) {
    let w = rep.pixelsWide, h = rep.pixelsHigh
    let rowBytes = (w * 3 + 3) & ~3
    var data = Data()
    func le32(_ v: Int) { var x = UInt32(truncatingIfNeeded: v).littleEndian; data.append(Data(bytes: &x, count: 4)) }
    func le16(_ v: Int) { var x = UInt16(v).littleEndian; data.append(Data(bytes: &x, count: 2)) }
    data.append(contentsOf: [0x42, 0x4D]); le32(54 + rowBytes * h); le32(0); le32(54)
    le32(40); le32(w); le32(h); le16(1); le16(24); le32(0); le32(rowBytes * h); le32(2835); le32(2835); le32(0); le32(0)
    for y in stride(from: h - 1, through: 0, by: -1) {   // bottom row first
        var row = [UInt8](repeating: 0, count: rowBytes)
        for x in 0..<w {
            let c = rep.colorAt(x: x, y: y)!.usingColorSpace(.sRGB)!
            row[x * 3] = UInt8((c.blueComponent * 255).rounded())
            row[x * 3 + 1] = UInt8((c.greenComponent * 255).rounded())
            row[x * 3 + 2] = UInt8((c.redComponent * 255).rounded())
        }
        data.append(contentsOf: row)
    }
    let full = "\(root)/\(path)"
    try! data.write(to: URL(fileURLWithPath: full))
}

func save(_ rep: NSBitmapImageRep, _ path: String, _ type: NSBitmapImageRep.FileType) {
    let full = "\(root)/\(path)"
    try? FileManager.default.createDirectory(atPath: (full as NSString).deletingLastPathComponent,
                                             withIntermediateDirectories: true)
    try! rep.representation(using: type, properties: [:])!.write(to: URL(fileURLWithPath: full))
}

// The five-bar waveform mark, centred in `rect`.
func waveform(in rect: NSRect, alpha: CGFloat = 1) {
    let bars: [(CGFloat, CGFloat, CGFloat, CGFloat, NSColor)] = [
        (144, 416, 240, 608, beige), (304, 288, 400, 736, beige), (464, 128, 560, 896, paper),
        (624, 288, 720, 736, beige), (784, 416, 880, 608, beige)]
    let s = rect.width / 736   // artwork spans x 144...880
    for (x0, y0, x1, y1, c) in bars {
        c.withAlphaComponent(alpha).setFill()
        NSRect(x: rect.minX + (x0 - 144) * s, y: rect.minY + (1024 - y1 - 128) * s,
               width: (x1 - x0) * s, height: (y1 - y0) * s).fill()
    }
}


// SedaSanj wordmark (same vector data as lib/app/widgets/brand_logo.dart, viewBox 520x189, y down).
let wordmarkPaths = [
    "M 305.667 92.500 C 307.457 93.524 309.771 93.000 311.833 93.000 C 316.112 93.000 320.452 92.442 324.667 93.178 C 326.504 93.654 328.292 94.714 329.511 96.168 C 330.616 97.901 331.107 100.119 330.933 102.167 C 330.323 105.087 327.418 107.768 324.500 108.388 C 318.764 109.114 312.667 107.260 307.167 109.042 C 303.468 110.858 301.661 115.746 301.137 119.833 C 300.910 121.680 300.475 123.657 301.083 125.415 C 302.425 126.548 304.586 126.034 306.333 125.860 C 308.665 125.777 311.000 125.833 313.333 125.833 C 319.842 125.833 326.535 126.487 332.833 124.847 C 334.880 124.211 336.842 123.265 338.667 122.141 C 339.911 121.319 341.050 120.184 342.500 119.833 C 345.023 121.839 347.810 123.621 350.833 124.736 C 356.222 126.326 362.123 126.490 367.667 125.579 C 371.768 124.624 375.646 122.545 379.000 120.000 C 380.668 120.812 381.926 122.293 383.500 123.275 C 385.402 124.359 387.546 124.990 389.667 125.530 C 394.041 126.325 398.554 125.833 403.000 125.833 C 410.667 125.833 418.333 125.833 426.000 125.833 C 432.167 125.833 438.333 125.833 444.500 125.833 C 451.141 125.833 458.201 125.572 464.167 122.655 C 469.841 119.423 474.428 113.665 476.582 107.500 C 478.269 101.076 477.353 93.737 474.656 87.667 C 471.902 82.366 467.092 77.820 461.667 75.322 C 455.989 73.096 449.598 73.167 443.500 73.167 C 436.369 73.167 428.906 73.500 422.333 76.266 C 414.429 80.151 407.599 86.584 402.598 93.833 C 400.862 96.399 399.300 99.087 397.865 101.833 C 396.962 103.498 396.437 105.638 394.827 106.635 C 392.928 106.738 391.196 104.741 390.430 103.000 C 389.591 100.059 390.000 96.892 390.000 93.833 C 390.000 91.594 390.952 87.923 388.826 87.218 C 382.735 87.143 375.564 88.820 371.664 93.501 C 369.923 96.037 370.547 99.567 369.619 102.500 C 368.564 105.090 366.037 107.342 363.333 108.056 C 359.400 108.778 354.423 106.725 352.303 103.333 C 350.408 99.690 350.728 95.256 349.514 91.333 C 347.611 86.206 344.049 81.237 339.333 78.467 C 333.195 75.288 325.746 75.333 318.833 75.333 C 316.222 75.333 313.611 75.333 311.000 75.333 C 309.406 75.334 307.713 75.079 306.229 75.660 C 304.969 77.298 305.667 79.767 305.667 81.833 C 305.667 85.389 305.667 88.944 305.667 92.500 Z M 418.167 106.333 C 419.516 101.227 423.690 96.504 428.500 94.322 C 433.604 92.377 439.371 93.000 444.833 93.000 C 448.008 93.000 451.369 92.521 454.333 93.657 C 456.475 94.703 458.163 97.007 458.681 99.333 C 458.890 102.012 456.926 105.069 454.500 106.225 C 450.299 107.852 445.505 106.833 441.000 106.833 C 436.167 106.833 431.333 106.833 426.500 106.833 C 423.717 106.833 420.616 107.654 418.167 106.333 Z M 47.667 88.000 C 51.426 88.751 55.333 88.167 59.167 88.167 C 66.278 88.167 73.389 88.167 80.500 88.167 C 83.611 88.167 86.722 88.167 89.833 88.167 C 92.408 88.167 95.813 88.989 96.877 91.333 C 97.157 92.410 97.100 93.633 96.686 94.666 C 95.888 95.869 94.572 96.858 93.167 97.189 C 87.481 97.834 81.722 97.167 76.000 97.167 C 70.233 97.167 64.225 97.274 58.833 99.321 C 52.523 102.086 46.694 107.345 43.953 113.667 C 41.831 119.165 41.545 125.700 43.274 131.333 C 45.364 136.416 49.282 141.191 54.167 143.710 C 57.997 145.362 62.328 145.831 66.500 145.834 C 68.523 145.861 70.705 146.434 72.565 145.639 C 73.575 144.114 73.000 141.997 73.000 140.167 C 73.000 136.944 73.000 133.722 73.000 130.500 C 71.786 129.604 70.009 130.006 68.500 129.995 C 66.982 129.914 65.431 129.418 64.168 128.572 C 62.848 127.377 61.890 125.604 61.699 123.833 C 61.729 122.286 62.403 120.710 63.371 119.503 C 66.890 115.961 73.174 117.167 78.167 117.167 C 84.279 117.167 90.438 117.544 96.500 116.756 C 98.382 116.436 100.143 115.603 101.999 115.157 C 104.276 115.786 105.366 118.478 107.167 120.008 C 110.360 122.529 114.117 124.416 118.000 125.630 C 124.343 127.092 131.329 126.649 137.500 124.576 C 140.849 123.162 143.852 120.967 146.667 118.667 C 148.697 119.120 150.098 121.021 151.833 122.169 C 154.695 123.872 157.890 125.136 161.167 125.731 C 166.302 126.439 171.756 126.117 176.667 124.455 C 180.128 123.125 183.099 120.751 186.167 118.667 C 188.088 119.599 189.573 121.246 191.333 122.455 C 193.930 124.029 196.841 125.216 199.833 125.732 C 204.581 126.382 209.596 126.076 214.167 124.638 C 217.300 123.350 220.002 121.193 222.833 119.333 C 224.481 120.171 225.788 121.560 227.333 122.575 C 229.921 124.033 232.745 125.194 235.667 125.731 C 244.090 126.894 253.747 124.202 260.166 118.626 C 263.727 115.209 266.289 110.586 267.618 105.833 C 268.761 100.391 268.333 94.727 268.333 89.167 C 268.333 85.722 268.333 82.278 268.333 78.833 C 268.333 76.812 268.912 74.524 267.882 72.785 C 265.899 71.628 263.262 72.682 261.000 73.074 C 256.268 74.011 250.686 76.400 248.785 80.833 C 246.378 87.235 248.708 94.541 247.903 101.333 C 247.182 103.999 244.386 106.308 241.667 106.788 C 238.290 106.989 233.988 104.461 233.216 101.167 C 232.682 96.083 233.000 90.945 233.000 85.833 C 233.000 84.278 233.000 82.722 233.000 81.167 C 233.000 80.113 233.132 78.716 232.288 78.086 C 225.714 77.120 217.322 80.375 214.068 86.167 C 211.936 90.840 213.883 96.541 212.548 101.500 C 211.496 104.472 207.977 106.733 204.833 106.974 C 201.542 106.816 197.801 104.050 197.087 100.833 C 196.579 95.971 197.000 91.056 197.000 86.167 C 197.000 83.772 197.771 81.029 196.500 79.000 C 189.956 79.000 181.945 80.906 178.290 86.333 C 175.946 90.752 177.661 96.440 176.026 101.167 C 174.506 104.488 170.472 106.814 166.833 107.131 C 162.760 106.991 158.296 103.705 157.023 99.833 C 156.146 95.249 156.833 90.500 156.833 85.833 C 156.833 83.941 157.058 81.975 156.500 80.167 C 152.604 79.551 148.612 80.000 144.667 80.000 C 142.132 80.000 139.001 78.917 137.083 80.575 C 136.517 82.236 136.833 84.079 136.833 85.833 C 136.833 90.278 137.519 94.811 136.631 99.167 C 135.336 103.543 130.395 107.735 125.833 107.586 C 121.980 107.136 117.850 104.641 116.124 101.167 C 114.429 96.664 115.646 91.489 114.435 86.833 C 112.652 81.236 108.740 75.843 103.667 72.882 C 98.075 69.870 91.184 70.000 84.833 70.000 C 78.766 70.000 72.484 69.413 66.667 71.138 C 62.303 72.831 58.706 76.224 55.454 79.590 C 53.741 81.312 52.003 83.010 50.320 84.762 C 49.360 85.775 48.144 86.689 47.667 88.000 Z M 275.833 125.833 L 295.167 125.333 L 294.667 42.167 C 290.828 42.167 286.831 43.077 283.500 44.986 C 280.449 46.947 277.833 49.868 276.325 53.167 C 274.771 57.462 275.333 62.266 275.333 66.833 C 275.333 73.667 275.333 80.500 275.333 87.333 C 275.333 95.667 275.333 104.000 275.333 112.333 C 275.333 115.111 275.333 117.889 275.333 120.667 C 275.333 122.397 275.012 124.310 275.833 125.833 Z",
    "M 147.333 54.000 C 145.144 54.441 142.845 54.927 141.000 56.186 C 139.025 57.765 137.455 60.170 137.059 62.667 C 136.860 65.371 137.664 68.303 139.254 70.499 C 140.928 72.328 143.372 73.665 145.833 73.972 C 148.113 74.058 150.533 73.578 152.500 72.421 C 154.872 70.611 156.667 67.635 156.973 64.667 C 157.029 62.137 156.086 59.446 154.468 57.501 C 152.611 55.612 149.936 54.493 147.333 54.000 Z",
    "M 88.833 125.833 C 86.381 126.359 83.858 127.312 82.012 129.011 C 80.330 130.880 79.220 133.486 79.171 136.000 C 79.346 140.586 84.417 145.392 89.000 145.640 C 91.637 145.429 94.351 144.279 96.272 142.460 C 97.983 140.510 99.021 137.761 98.990 135.167 C 98.793 132.603 97.396 130.022 95.495 128.292 C 93.601 126.872 91.162 126.257 88.833 125.833 Z",
]
func wordmark(width: CGFloat, centerX: CGFloat, y: CGFloat, color: NSColor) {
    let s = width / 520
    let path = NSBezierPath()
    for data in wordmarkPaths {
        let t = data.split(whereSeparator: { $0 == " " }).map(String.init)
        var i = 0; var cmd = ""
        func pt() -> NSPoint { let x = CGFloat(Double(t[i])!), yy = CGFloat(Double(t[i + 1])!); i += 2
            return NSPoint(x: centerX - width / 2 + x * s, y: y + (189 - yy) * s) }
        while i < t.count {
            if ["M", "L", "C", "Z"].contains(t[i]) { cmd = t[i]; i += 1; if cmd == "Z" { path.close(); continue } }
            switch cmd {
            case "M": path.move(to: pt()); cmd = "L"
            case "L": path.line(to: pt())
            default: let a = pt(), b = pt(), c = pt(); path.curve(to: c, controlPoint1: a, controlPoint2: b)
            }
        }
    }
    path.windingRule = .nonZero
    color.setFill(); path.fill()
}

func gradient(_ w: CGFloat, _ h: CGFloat) {
    NSGradient(starting: bg, ending: bgDeep)!.draw(in: NSRect(x: 0, y: 0, width: w, height: h), angle: -90)
}

func text(_ s: String, _ f: NSFont, _ c: NSColor, centerX: CGFloat, y: CGFloat, kern: CGFloat = 0) {
    let style = NSMutableParagraphStyle(); style.alignment = .center
    style.baseWritingDirection = .rightToLeft
    let a = NSAttributedString(string: s, attributes: [.font: f, .foregroundColor: c, .paragraphStyle: style, .kern: kern])
    let size = a.size()
    a.draw(in: NSRect(x: centerX - size.width / 2 - 4, y: y, width: size.width + 8, height: size.height + 4))
}

// ---- DMG background: 660x440 points, drawn at 1x and 2x ----
// Logo + name on top, install guide in the middle, SedaSanj wordmark + address at the bottom.
for scale in [1, 2] {
    let k = CGFloat(scale)
    let rep = render(660 * scale, 440 * scale) { w, h in
        gradient(w, h)
        waveform(in: NSRect(x: (w - 60 * k) / 2, y: h - 80 * k, width: 60 * k, height: 60 * k))
        text("جلسه‌نگار", font("Vazirmatn-SSStrong.ttf", 28 * k), paper, centerX: w / 2, y: h - 126 * k)
        // arrow between the app icon (x=180) and Applications (x=480)
        paper.withAlphaComponent(0.85).setStroke()
        let arrow = NSBezierPath(); arrow.lineWidth = 4 * k; arrow.lineCapStyle = .round; arrow.lineJoinStyle = .round
        let ay = h - 215 * k
        arrow.move(to: NSPoint(x: 270 * k, y: ay)); arrow.line(to: NSPoint(x: 390 * k, y: ay))
        arrow.move(to: NSPoint(x: 372 * k, y: ay + 16 * k)); arrow.line(to: NSPoint(x: 390 * k, y: ay))
        arrow.line(to: NSPoint(x: 372 * k, y: ay - 16 * k))
        arrow.stroke()
        text("برای نصب، آیکن جلسه‌نگار را روی پوشهٔ Applications بکشید", font("Vazirmatn-SSStrong.ttf", 15 * k), paper,
             centerX: w / 2, y: 104 * k)
        text("اگر مک هنگام اولین اجرا هشدار داد: روی برنامه راست‌کلیک کنید و Open را بزنید", font("Vazirmatn-SSMedium.ttf", 12 * k), beige,
             centerX: w / 2, y: 78 * k)
        wordmark(width: 82 * k, centerX: w / 2, y: 38 * k, color: paper.withAlphaComponent(0.9))
        text("sedasanj.ir", font("Vazirmatn-SSText.ttf", 12 * k), beige, centerX: w / 2, y: 20 * k, kern: 1.6 * k)
    }
    save(rep, "macos/dmg/background\(scale == 2 ? "@2x" : "").png", .png)
}

// ---- Windows installer wizard images (BMP; Inno Setup scales between the listed sizes) ----
for scale in [1, 2] {
    let k = CGFloat(scale)
    let big = render(164 * scale, 314 * scale) { w, h in
        gradient(w, h)
        waveform(in: NSRect(x: 32 * k, y: h - 140 * k, width: 100 * k, height: 100 * k))
        text("جلسه‌نگار", font("Vazirmatn-SSStrong.ttf", 26 * k), paper, centerX: w / 2, y: h - 205 * k)
        wordmark(width: 92 * k, centerX: w / 2, y: 44 * k, color: paper.withAlphaComponent(0.9))
        text("sedasanj.ir", font("Vazirmatn-SSText.ttf", 12 * k), beige, centerX: w / 2, y: 28 * k, kern: 1.6 * k)
    }
    saveBMP(big, "windows/installer/wizard\(scale == 2 ? "@2x" : "").bmp")
    let small = render(55 * scale, 55 * scale) { w, h in
        bg.setFill(); NSRect(x: 0, y: 0, width: w, height: h).fill()
        waveform(in: NSRect(x: 7 * k, y: 7 * k, width: 41 * k, height: 41 * k))
    }
    saveBMP(small, "windows/installer/wizard-small\(scale == 2 ? "@2x" : "").bmp")
}
print("installer art written")
