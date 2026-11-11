"""Lädt die Umrisse der Wiener Gemeindebauten (data.wien.gv.at, GEMBAUTENFLOGD) und speichert die,
die höchstens 300 m von unseren Suchbezirken entfernt liegen, in geo/gemeindebauten.geojson.

Wunsch 2026-11-11: keine Wohnung direkt neben einem Gemeindebau (run.py, filter.gemeindebau_min_m).
Neu laden, wenn die Stadt neue Gemeindebauten einträgt (selten):

    python tools/fetch_gemeindebauten.py
"""
import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = ("https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0"
       "&typeName=ogdwien:GEMBAUTENFLOGD&srsName=EPSG:4326&outputFormat=json&bbox={},EPSG:4326")
RAND_M = 300
FELDER = ("HOFNAME", "ADRESSE", "WOHNUNGSANZAHL", "BAUJAHR", "BEZIRK")


def _ringe(geo):
    return [geo["coordinates"]] if geo["type"] == "Polygon" else geo["coordinates"]


def main():
    bez = json.loads((ROOT / "geo" / "bezirke.geojson").read_text(encoding="utf-8"))["features"]
    dx = RAND_M / (111320 * math.cos(math.radians(48.2)))
    dy = RAND_M / 110540
    boxen = []
    for f in bez:
        pts = [p for poly in _ringe(f["geometry"]) for p in poly[0]]
        boxen.append((min(x for x, _ in pts) - dx, min(y for _, y in pts) - dy,
                      max(x for x, _ in pts) + dx, max(y for _, y in pts) + dy))
    gesamt = (min(b[0] for b in boxen), min(b[1] for b in boxen), max(b[2] for b in boxen), max(b[3] for b in boxen))
    req = urllib.request.Request(URL.format(",".join(f"{v:.5f}" for v in gesamt)),
                                 headers={"User-Agent": "wohnungssuche"})
    daten = json.load(urllib.request.urlopen(req, timeout=180))
    out = []
    for f in daten["features"]:
        polys = _ringe(f["geometry"])
        pts = [p for poly in polys for ring in poly for p in ring]
        fb = (min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts), max(y for _, y in pts))
        if not any(fb[0] <= b[2] and fb[2] >= b[0] and fb[1] <= b[3] and fb[3] >= b[1] for b in boxen):
            continue
        geo = {"type": "MultiPolygon",
               "coordinates": [[[[round(x, 6), round(y, 6)] for x, y in ring] for ring in poly] for poly in polys]}
        out.append({"type": "Feature", "properties": {k: f["properties"].get(k) for k in FELDER}, "geometry": geo})
    pfad = ROOT / "geo" / "gemeindebauten.geojson"
    pfad.write_text(json.dumps({"type": "FeatureCollection", "features": out}, ensure_ascii=False,
                               separators=(",", ":")), encoding="utf-8")
    print(f"{len(out)} Gemeindebauten -> {pfad} ({pfad.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
