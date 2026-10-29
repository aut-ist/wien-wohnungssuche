"""Öffis fürs Suchgebiet (data.wien.gv.at) -> geo/oeffis.geojson

Gebiet: 8., 9., 18., 19. Bezirk und der erlaubte Teil des 2. (blaue Zone Karmeliterviertel/Augarten);
der 8./9./2. seit 2026-10-29 (Wunsch), vorher nur 18./19.
- Straßenbahn- und Buslinien, die wirklich durchs Gebiet fahren, nur das Stück im Gebiet
  (plus RAND_M, damit sie bis zu den Stationen am Rand reichen).
- U- und S-Bahn-Strecken und -Stationen im selben Bereich (z. B. U6 am Gürtel).

    python tools/fetch_oeffis.py
"""
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wohnungen import geo  # noqa: E402
from fetch_bezirke import simplify  # noqa: E402

WFS = ("https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0"
       "&typeName=ogdwien:{}&srsName=EPSG:4326&outputFormat=json")
TYPEN = {"1": "tram", "2": "bus", "4": "ubahn", "5": "sbahn"}
GEBIETE = ([f for f in geo.BEZIRKE if f["properties"]["bezirk"] in (8, 9, 18, 19)]
           + [f for f in geo.ZONEN if f["properties"]["id"] == "leopoldstadt"])
RAND_M = 120          # damit die Linien bis zu den Stationen am Rand (Gürtel) reichen
MIN_IM_GEBIET_M = 400  # so viel muss eine Linie im Gebiet fahren, um zu zählen
STATION_RAND_M = 250


def _laden(name):
    with urllib.request.urlopen(WFS.format(name), timeout=120) as r:
        return json.load(r)["features"]


def _abstand(lon, lat):
    return min(geo._abstand_m(lon, lat, f) for f in GEBIETE)


def _laenge_m(a, b):
    return math.hypot((a[0] - b[0]) * geo.K_LON, (a[1] - b[1]) * geo.K_LAT)


def _linien(f):
    return [x.strip() for x in f["properties"]["LBEZEICHNUNG"].split(",") if x.strip()]


def main():
    xs = [x for f in GEBIETE for x, _ in f["geometry"]["coordinates"][0]]
    ys = [y for f in GEBIETE for _, y in f["geometry"]["coordinates"][0]]
    box = (min(xs) - .005, min(ys) - .004, max(xs) + .005, max(ys) + .004)
    in_box = lambda p: box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]  # noqa: E731

    # Linienstücke im Umkreis sammeln, Abstand zum Gebiet pro Punkt vorrechnen
    stuecke = []
    for f in _laden("OEFFLINIENOGD"):
        typ = TYPEN.get(f["properties"]["LTYP"])
        if not typ or f["properties"].get("LTYPTXT") == "Zug":
            continue
        g = f["geometry"]
        for line in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            line = [p[:2] for p in line]
            if any(in_box(p) for p in line):
                stuecke.append((typ, _linien(f), line, [_abstand(*p) for p in line]))

    # welche Linien fahren nennenswert durchs Gebiet?
    im_gebiet = {}
    for typ, linien, line, ab in stuecke:
        d = sum(_laenge_m(line[i], line[i + 1]) for i in range(len(line) - 1) if ab[i] == 0 and ab[i + 1] == 0)
        for l in linien:
            im_gebiet[l] = im_gebiet.get(l, 0) + d
    relevant = {l for l, d in im_gebiet.items() if d >= MIN_IM_GEBIET_M}

    feats = []
    for typ, linien, line, ab in stuecke:
        linien = [l for l in linien if l in relevant]
        if not linien:
            continue
        teil = []
        for p, d in zip(line + [None], ab + [None]):
            if p is not None and d <= RAND_M:
                teil.append(p)
                continue
            if len(teil) >= 2:
                feats.append({"type": "Feature", "properties": {"typ": typ, "linien": ", ".join(linien)},
                              "geometry": {"type": "LineString", "coordinates":
                                           [[round(a, 5), round(b, 5)] for a, b in simplify(teil, 6)]}})
            teil = []

    # U- und S-Bahn-Stationen (eine pro Name)
    stationen = {}
    for f in _laden("OEFFHALTESTOGD"):
        p = f["properties"]
        if str(p["LTYP"]) not in ("4", "5"):
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        if not in_box((lon, lat)) or _abstand(lon, lat) > STATION_RAND_M:
            continue
        name = p["HTXTK"].split(" (")[0]
        s = stationen.setdefault(name, {"lon": [], "lat": [], "linien": set()})
        s["lon"].append(lon); s["lat"].append(lat)
        s["linien"].update(x.strip() for x in str(p["HLINIEN"]).split(",") if x.strip())
    # nur echte U-/S-Bahn-Stationen (keine Ersatzverkehr-Haltestellen), Label nur mit U-/S-Linien
    tag = re.compile(r"^(U\d|S\d+)$")
    stationen = {n: s for n, s in stationen.items() if any(tag.match(l) for l in s["linien"])}
    for name, s in stationen.items():
        linien = sorted(l for l in s["linien"] if tag.match(l))
        feats.append({"type": "Feature",
                      "properties": {"typ": "station", "name": name, "linien": ", ".join(linien)},
                      "geometry": {"type": "Point", "coordinates": [round(sum(s["lon"]) / len(s["lon"]), 5),
                                                                    round(sum(s["lat"]) / len(s["lat"]), 5)]}})

    path = ROOT / "geo" / "oeffis.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
                    encoding="utf-8")
    print("Linien:", ", ".join(sorted(relevant, key=lambda x: (len(x), x))))
    print("Stationen:", ", ".join(sorted(stationen)))
    print("geschrieben:", path, path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
