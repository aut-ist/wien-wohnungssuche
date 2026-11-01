"""Fußweg-Gebiet für die Landstraße-Zone: alles, was zu Fuß höchstens MAX_M Meter von einer der U-Bahn-
Stationen entfernt ist (Saad 2026-11-01: im 3. nur max. 10 min zu Fuß zu U Landstraße oder U Rochusgasse;
Hundertwasserhaus -> Landstraße, ca. 13 min, war ihm zu weit). Gerechnet mit dem Fußweg-Routing von
OpenStreetMap (routing.openstreetmap.de, FOSSGIS) auf einem Gitter über die Zone; das Ergebnis ist ein
Polygon in geo/fussweg_landstrasse.geojson, das tools/build_zones.py mit der Zone schneidet.

700 m: das Routing gibt für Hundertwasserhaus -> Station Landstraße 788 m / 10,5 min an; Saads 13 min
enthalten den Weg hinunter zum Bahnsteig. 700 m bis zur Station sind ca. 9 min plus Abgang = 10 min.

    python tools/fussweg_zone.py      (braucht shapely, lokal laufen lassen, dauert ca. 1 Minute)
"""
import json
import time
import urllib.request
from pathlib import Path

from shapely.geometry import Point, Polygon, box, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
MAX_M = 700
STATIONEN = [(16.38567, 48.20576), (16.38485, 48.20692), (16.39226, 48.20209)]  # U3/U4 Landstraße, U3 Rochusgasse
SCHRITT_LON, SCHRITT_LAT = 0.0007, 0.00045  # ca. 50 m
URL = "https://routing.openstreetmap.de/routed-foot/table/v1/driving/"


def main():
    zonen = json.loads((ROOT / "geo" / "zones.geojson").read_text(encoding="utf-8"))["features"]
    zone = next(f for f in zonen if f["properties"]["id"] == "landstrasse")
    # die ungeschnittene Zone aus build_zones nehmen wäre schöner; der Rand reicht mit Puffer auch so
    gebiet = Polygon(zone["geometry"]["coordinates"][0]).buffer(0.002)
    minx, miny, maxx, maxy = gebiet.bounds
    pts = [(round(minx + i * SCHRITT_LON, 6), round(miny + j * SCHRITT_LAT, 6))
           for j in range(int((maxy - miny) / SCHRITT_LAT) + 1) for i in range(int((maxx - minx) / SCHRITT_LON) + 1)]
    pts = [p for p in pts if gebiet.contains(Point(p))]
    nah = []
    for k in range(0, len(pts), 80):
        teil = pts[k:k + 80]
        n = len(teil)
        url = (URL + ";".join(f"{a},{b}" for a, b in teil + STATIONEN)
               + f"?sources={';'.join(map(str, range(n)))}"
               + f"&destinations={';'.join(str(n + i) for i in range(len(STATIONEN)))}&annotations=distance")
        for versuch in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "wien-wohnungssuche (privat)"})
                d = json.load(urllib.request.urlopen(req, timeout=60))
                break
            except Exception as e:  # Dienst kurz überlastet
                if versuch == 2:
                    raise
                print("neuer Versuch:", e)
                time.sleep(5)
        nah += [p for p, dist in zip(teil, d["distances"]) if min(x for x in dist if x is not None) <= MAX_M]
        time.sleep(1.5)
    zellen = unary_union([box(a - SCHRITT_LON / 2, b - SCHRITT_LAT / 2, a + SCHRITT_LON / 2, b + SCHRITT_LAT / 2)
                          for a, b in nah])
    glatt = zellen.buffer(0.0002).buffer(-0.0002).simplify(0.00005)
    if glatt.geom_type != "Polygon":
        glatt = max(glatt.geoms, key=lambda g: g.area)
    out = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"max_m": MAX_M},
                                                       "geometry": mapping(Polygon(glatt.exterior))}]}
    (ROOT / "geo" / "fussweg_landstrasse.geojson").write_text(json.dumps(out), encoding="utf-8")
    print(f"{len(nah)} von {len(pts)} Gitterpunkten höchstens {MAX_M} m von einer Station")


if __name__ == "__main__":
    main()
