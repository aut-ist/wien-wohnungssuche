"""Erzeugt das App-Symbol (Haus auf Grün) als PNG, nur mit der Standardbibliothek."""
import struct
import zlib
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"


def png(n):
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            u, v = x / n, y / n
            dach = v >= 0.22 and v <= 0.50 and abs(u - 0.5) <= (v - 0.22) / 0.28 * 0.30
            haus = 0.27 <= u <= 0.73 and 0.48 <= v <= 0.78
            tuer = 0.44 <= u <= 0.56 and 0.60 <= v <= 0.78
            weiss = (dach or haus) and not tuer
            row += bytes((255, 255, 255) if weiss else (31, 157, 97))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", raw) + chunk(b"IEND", b"")


for n in (180, 512):
    (DOCS / f"icon-{n}.png").write_bytes(png(n))
print("ok")
