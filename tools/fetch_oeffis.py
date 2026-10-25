"""Lädt Straßenbahn-, Bus-, U- und S-Bahn-Linien (data.wien.gv.at) und schneidet sie
auf den 18. und 19. Bezirk (plus Rand) zu -> geo/oeffis.geojson

    python tools/fetch_oeffis.py
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wohnungen import geo  # noqa: E402
from fetch_bezirke import simplify  # noqa: E402

URL = ("https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0"
       "&typeName=ogdwien:OEFFLINIENOGD&srsName=EPSG:4326&outputFormat=json")
TYPEN = {"1": "tram", "2": "bus", "4": "ubahn", "5": "sbahn"}
BEZIRKE = [f for f in geo.BEZIRKE if f["properties"]["bezirk"] in (18, 19)]
RAND_M = 250


def drin(lon, lat):
    return any(geo._abstand_m(lon, lat, f) <= RAND_M for f in BEZIRKE)


def main():
    with urllib.request.urlopen(URL, timeout=120) as r:
        src = json.load(r)
    xs = [x for f in BEZIRKE for x, _ in f["geometry"]["coordinates"][0]]
    ys = [y for f in BEZIRKE for _, y in f["geometry"]["coordinates"][0]]
    box = (min(xs) - .005, min(ys) - .004, max(xs) + .005, max(ys) + .004)
    feats = []
    for f in src["features"]:
        p = f["properties"]
        typ = TYPEN.get(p["LTYP"])
        if not typ or p.get("LTYPTXT") == "Zug":
            continue
        g = f["geometry"]
        lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        for line in lines:
            if not any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in line):
                continue
            stueck = []
            for pt in line + [None]:
                if pt is not None and drin(*pt[:2]):
                    stueck.append(pt[:2])
                    continue
                if len(stueck) >= 2:
                    feats.append({"type": "Feature", "properties": {"typ": typ, "linien": p["LBEZEICHNUNG"]},
                                  "geometry": {"type": "LineString", "coordinates":
                                               [[round(a, 5), round(b, 5)] for a, b in simplify(stueck, 6)]}})
                stueck = []
    path = ROOT / "geo" / "oeffis.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
                    encoding="utf-8")
    print("geschrieben:", path, len(feats), "Stücke,", path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
