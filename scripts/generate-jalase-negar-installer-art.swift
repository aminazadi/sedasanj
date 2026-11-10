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

func gradient(_ w: CGFloat, _ h: CGFloat) {
    NSGradient(starting: bg, ending: bgDeep)!.draw(in: NSRect(x: 0, y: 0, width: w, height: h), angle: -90)
}

func text(_ s: String, _ f: NSFont, _ c: NSColor, centerX: CGFloat, y: CGFloat) {
    let style = NSMutableParagraphStyle(); style.alignment = .center
    style.baseWritingDirection = .rightToLeft
    let a = NSAttributedString(string: s, attributes: [.font: f, .foregroundColor: c, .paragraphStyle: style])
    let size = a.size()
    a.draw(in: NSRect(x: centerX - size.width / 2 - 4, y: y, width: size.width + 8, height: size.height + 4))
}

// ---- DMG background: 660x400 points, drawn at 1x and 2x ----
for scale in [1, 2] {
    let k = CGFloat(scale)
    let rep = render(660 * scale, 400 * scale) { w, h in
        gradient(w, h)
        waveform(in: NSRect(x: 40 * k, y: 40 * k, width: 580 * k, height: 320 * k), alpha: 0.05)
        text("جلسه‌نگار", font("Vazirmatn-SSStrong.ttf", 40 * k), paper, centerX: w / 2, y: h - 92 * k)
        text("ضبط جلسه و رونویسی فارسی · همراه صداسنج", font("Vazirmatn-SSMedium.ttf", 15 * k), beige,
             centerX: w / 2, y: h - 124 * k)
        // arrow between the app icon (x=180) and Applications (x=480)
        paper.withAlphaComponent(0.85).setStroke()
        let arrow = NSBezierPath(); arrow.lineWidth = 4 * k; arrow.lineCapStyle = .round; arrow.lineJoinStyle = .round
        let ay = h - 215 * k
        arrow.move(to: NSPoint(x: 270 * k, y: ay)); arrow.line(to: NSPoint(x: 390 * k, y: ay))
        arrow.move(to: NSPoint(x: 372 * k, y: ay + 16 * k)); arrow.line(to: NSPoint(x: 390 * k, y: ay))
        arrow.line(to: NSPoint(x: 372 * k, y: ay - 16 * k))
        arrow.stroke()
        text("برای نصب، جلسه‌نگار را روی پوشهٔ Applications بکشید", font("Vazirmatn-SSMedium.ttf", 14 * k), paper,
             centerX: w / 2, y: 36 * k)
    }
    save(rep, "macos/dmg/background\(scale == 2 ? "@2x" : "").png", .png)
}

// ---- Windows installer wizard images (BMP; Inno Setup scales between the listed sizes) ----
for scale in [1, 2] {
    let k = CGFloat(scale)
    let big = render(164 * scale, 314 * scale) { w, h in
        gradient(w, h)
        waveform(in: NSRect(x: 32 * k, y: h - 150 * k, width: 100 * k, height: 100 * k))
        text("جلسه‌نگار", font("Vazirmatn-SSStrong.ttf", 26 * k), paper, centerX: w / 2, y: h - 205 * k)
        text("همراه صداسنج", font("Vazirmatn-SSMedium.ttf", 13 * k), beige, centerX: w / 2, y: h - 232 * k)
        beige.withAlphaComponent(0.5).setFill()
        NSRect(x: 52 * k, y: h - 245 * k, width: 60 * k, height: 2 * k).fill()
    }
    save(big, "windows/installer/wizard\(scale == 2 ? "@2x" : "").bmp", .bmp)
    let small = render(55 * scale, 55 * scale) { w, h in
        bg.setFill(); NSRect(x: 0, y: 0, width: w, height: h).fill()
        waveform(in: NSRect(x: 7 * k, y: 7 * k, width: 41 * k, height: 41 * k))
    }
    save(small, "windows/installer/wizard-small\(scale == 2 ? "@2x" : "").bmp", .bmp)
}
print("installer art written")
