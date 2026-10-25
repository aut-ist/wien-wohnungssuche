"""Lädt die offiziellen Wiener Bezirksgrenzen (data.wien.gv.at) und speichert
die für uns relevanten Bezirke vereinfacht in geo/bezirke.geojson.

    python tools/fetch_bezirke.py
"""
import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = ("https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0"
       "&typeName=ogdwien:BEZIRKSGRENZEOGD&srsName=EPSG:4326&outputFormat=json")
BEZIRKE = {1, 2, 8, 9, 18, 19}
TOLERANZ_M = 4


def _dist_m(p, a, b):
    """Abstand Punkt p zur Strecke a-b in Metern (lokal flach gerechnet)."""
    k = math.cos(math.radians(48.2)) * 111320
    px, py = p[0] * k, p[1] * 110540
    ax, ay = a[0] * k, a[1] * 110540
    bx, by = b[0] * k, b[1] * 110540
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def simplify(pts, tol):
    """Douglas-Peucker, iterativ."""
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0, None
        for k in range(i + 1, j):
            d = _dist_m(pts[k], pts[i], pts[j])
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep) if k]


def main():
    with urllib.request.urlopen(URL, timeout=60) as r:
        src = json.load(r)
    feats = []
    for f in src["features"]:
        p = f["properties"]
        if p["BEZNR"] not in BEZIRKE:
            continue
        rings = [[[round(x, 6), round(y, 6)] for x, y in simplify(ring, TOLERANZ_M)]
                 for ring in f["geometry"]["coordinates"]]
        feats.append({"type": "Feature",
                      "properties": {"bezirk": p["BEZNR"], "name": p["NAMEK"], "plz": p["DISTRICT_CODE"]},
                      "geometry": {"type": "Polygon", "coordinates": rings}})
    feats.sort(key=lambda f: f["properties"]["bezirk"])
    path = ROOT / "geo" / "bezirke.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
                    encoding="utf-8")
    print("geschrieben:", path, path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
