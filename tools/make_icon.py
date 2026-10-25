"""Erzeugt das App-Symbol (Gigibird brütet auf dem Nest) als PNG, nur mit der Standardbibliothek."""
import struct
import zlib
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

GRUEN = (31, 157, 97)
GOLD, BAUCH, FLUEGEL = (246, 183, 60), (255, 226, 163), (224, 149, 42)
NEST, NEST_DUNKEL = (154, 107, 63), (110, 72, 38)
CREME, HELLBLAU = (255, 246, 230), (225, 241, 250)
SCHWARZ, WEISS, ORANGE = (29, 31, 35), (255, 255, 255), (240, 125, 46)


def ellipse(cx, cy, rx, ry):
    return lambda u, v: ((u - cx) / rx) ** 2 + ((v - cy) / ry) ** 2 <= 1


def dreieck(a, b, c):
    def drin(u, v):
        d1 = (u - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (v - b[1])
        d2 = (u - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (v - c[1])
        d3 = (u - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (v - a[1])
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))
    return drin


nest = ellipse(0.5, 0.64, 0.40, 0.21)
# Reihenfolge = Malreihenfolge (spätere Formen liegen oben)
FORMEN = [
    (ellipse(0.40, 0.47, 0.23, 0.20), GOLD),                        # Körper
    (ellipse(0.39, 0.265, 0.022, 0.055), FLUEGEL),                 # Federschopf
    (ellipse(0.435, 0.255, 0.024, 0.06), FLUEGEL),
    (ellipse(0.40, 0.47, 0.23, 0.20), GOLD),                        # Körper deckt den Schopf unten ab
    (ellipse(0.35, 0.53, 0.14, 0.11), BAUCH),                       # Bauch
    (ellipse(0.55, 0.50, 0.17, 0.08), FLUEGEL),                     # Flügel über den Eiern
    (ellipse(0.66, 0.58, 0.075, 0.095), CREME),                     # Eier
    (ellipse(0.79, 0.60, 0.065, 0.085), HELLBLAU),
    (lambda u, v: nest(u, v) and v >= 0.62, NEST),                  # Nest vorne
    (lambda u, v: nest(u, v) and v >= 0.62 and abs((v - 0.70) - 0.06 * (u - 0.5)) < 0.008, NEST_DUNKEL),
    (lambda u, v: nest(u, v) and v >= 0.62 and abs((v - 0.77) + 0.05 * (u - 0.5)) < 0.008, NEST_DUNKEL),
    (ellipse(0.31, 0.42, 0.032, 0.032), SCHWARZ),                   # Auge
    (ellipse(0.322, 0.408, 0.011, 0.011), WEISS),
    (dreieck((0.19, 0.45), (0.10, 0.49), (0.195, 0.52)), ORANGE),   # Schnabel
]


def png(n):
    rows = []
    for y in range(n):
        row = bytearray([0])
        v = (y + 0.5) / n
        for x in range(n):
            u = (x + 0.5) / n
            farbe = GRUEN
            for form, f in FORMEN:
                if form(u, v):
                    farbe = f
            row += bytes(farbe)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", raw) + chunk(b"IEND", b"")


for n in (180, 512):
    (DOCS / f"icon-{n}.png").write_bytes(png(n))
print("ok")
