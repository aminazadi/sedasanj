#!/usr/bin/env python3
"""Redraws the Jalase-Negar launcher icon (the SedaSanj waveform) crisply at every size.

The 64px favicon was upscaled before and looked blurry; the artwork is five rectangles, so it is
rendered here from geometry (pure standard library, anti-aliased by supersampling) for iOS, Android,
macOS, Windows and web. Run from the repository root: python3 scripts/generate-jalase-negar-icons.py
"""
import json
import os
import struct
import zlib

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jalase-negar")
BG = (75, 110, 72)
BEIGE = (178, 172, 136)
WHITE = (242, 240, 239)
# (x0, y0, x1, y1, colour) on a 1024 grid
BARS = [
    (144, 416, 240, 608, BEIGE),
    (304, 288, 400, 736, BEIGE),
    (464, 128, 560, 896, WHITE),
    (624, 288, 720, 736, BEIGE),
    (784, 416, 880, 608, BEIGE),
]


def _in_round_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x >= x1 or y < y0 or y >= y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size, shape="square"):
    """RGBA bytes. shape: square (full bleed) or mac (824/1024 rounded square, transparent margin)."""
    ss = 4 if size <= 256 else 2
    s = size * ss
    k = 1024 / s
    out = bytearray()
    for py in range(size):
        row = []
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    x = (px * ss + sx + 0.5) * k
                    y = (py * ss + sy + 0.5) * k
                    if shape == "mac":
                        inside = _in_round_rect(x, y, 100, 100, 924, 924, 185)
                    else:
                        inside = True
                    if not inside:
                        continue
                    if shape == "mac":
                        # scale artwork into the 824 square
                        ax = (x - 100) * 1024 / 824
                        ay = (y - 100) * 1024 / 824
                    else:
                        ax, ay = x, y
                    c = BG
                    for x0, y0, x1, y1, col in BARS:
                        if x0 <= ax < x1 and y0 <= ay < y1:
                            c = col
                    acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]; acc[3] += 1
            n = ss * ss
            if acc[3] == 0:
                row.append((0, 0, 0, 0))
            else:
                row.append((acc[0] // acc[3], acc[1] // acc[3], acc[2] // acc[3], acc[3] * 255 // n))
        for p in row:
            out += bytes(p)
    return bytes(out)


def png(size, rgba, opaque=False):
    if opaque:  # iOS App Store icons must not have an alpha channel
        raw = b"".join(b"\x00" + bytes(c for i in range(size) for c in rgba[(y * size + i) * 4:(y * size + i) * 4 + 3]) for y in range(size))
        ct = 2
    else:
        raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
        ct = 6

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, ct, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def write(path, data):
    path = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)  # atomic


cache = {}


def sq(size, opaque=False):
    key = (size, opaque)
    if key not in cache:
        cache[key] = png(size, render(size), opaque)
    return cache[key]


def main():
    # iOS: sizes come from the asset catalog itself
    d = "ios/Runner/Assets.xcassets/AppIcon.appiconset"
    with open(os.path.join(ROOT, d, "Contents.json")) as f:
        for im in json.load(f)["images"]:
            base = float(im["size"].split("x")[0])
            scale = int(im["scale"].rstrip("x"))
            write(f"{d}/{im['filename']}", sq(round(base * scale), opaque=True))
    # Android launcher densities
    for dens, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        write(f"android/app/src/main/res/mipmap-{dens}/ic_launcher.png", sq(px))
    # macOS
    for px in (16, 32, 64, 128, 256, 512, 1024):
        write(f"macos/Runner/Assets.xcassets/AppIcon.appiconset/app_icon_{px}.png", png(px, render(px, "mac")))
    # Windows .ico (PNG-compressed entries)
    sizes = (16, 24, 32, 48, 64, 128, 256)
    blobs = [png(s, render(s, "mac")) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(sizes))
    off = 6 + 16 * len(sizes)
    entries = b""
    for s, b in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), off)
        off += len(b)
    write("windows/runner/resources/app_icon.ico", head + entries + b"".join(blobs))
    # Web
    write("web/favicon.png", sq(32))
    write("web/icons/Icon-192.png", sq(192))
    write("web/icons/Icon-512.png", sq(512))
    write("web/icons/Icon-maskable-192.png", sq(192))
    write("web/icons/Icon-maskable-512.png", sq(512))
    print("icons written")


main()
