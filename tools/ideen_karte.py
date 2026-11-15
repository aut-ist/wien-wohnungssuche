"""Ideen-Grätzl für die Karte -> docs/geo/ideen.json und docs/geo/oeffis_ideen.geojson

Saad 2026-11-15: Gegenden außerhalb der Suchgebiete, die passen könnten (data/ideen.json, recherchiert
mit Fahrplan, Schulverzeichnis und Reddit), sollen auf der echten Karte zu sehen sein, mit Öffi-Netz.
Die Karte zeigt sie nur, wenn man den Knopf "Ideen" einschaltet.

- U-Bahn und Straßenbahn im ganzen Bereich um die Ideen (Linienweg mit den meisten Fahrten je Linie),
  Busse nur im Umkreis der Grätzl; aus dem GTFS-Fahrplan der Wiener Linien.
- U-Bahn-Stationen aus UBAHNHALTOGD (data.wien.gv.at).

Braucht shapely (nur lokal).    python tools/ideen_karte.py [gtfs.zip]
"""
import csv
import io
import json
import math
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from shapely.geometry import LineString, Point, box as rechteck
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
GTFS = "https://www.wienerlinien.at/ogd_realtime/doku/ogd/gtfs/gtfs.zip"
TYPEN = {"0": "tram", "1": "ubahn", "3": "bus"}
K_LON, K_LAT = 74200, 111320
BUS_RAND_M = 250   # Busse nur so weit über den Grätzl-Kreis hinaus
EINFACH = 0.00004  # Vereinfachung der Linien in Grad (ca. 3-4 m)


def kreis(lon, lat, r):
    p = Point(lon * K_LON, lat * K_LAT).buffer(r, quad_segs=16)
    return LineString([(x / K_LON, y / K_LAT) for x, y in p.exterior.coords]).convex_hull


def main():
    ideen = json.loads((ROOT / "data" / "ideen.json").read_text(encoding="utf-8"))
    alle = ideen["gebiete"] + ideen["zu_weit"]
    xs = [g["lon"] for g in alle]
    ys = [g["lat"] for g in alle]
    bereich = rechteck(min(xs) - .012, min(ys) - .008, max(xs) + .012, max(ys) + .008)
    bus_gebiet = unary_union([kreis(g["lon"], g["lat"], g["r"] + BUS_RAND_M) for g in ideen["gebiete"]])

    pfad = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "wl_gtfs.zip"
    if not pfad.exists():
        urllib.request.urlretrieve(GTFS, pfad)
    z = zipfile.ZipFile(pfad)
    lesen = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), "utf-8-sig"))  # noqa: E731
    routen = {r["route_id"]: (TYPEN[r["route_type"]], r["route_short_name"].strip(), "#" + r["route_color"])
              for r in lesen("routes.txt") if r["route_type"] in TYPEN and not r["route_short_name"].startswith("N")}
    zaehl = {}
    for t in lesen("trips.txt"):
        if t["route_id"] in routen:
            k = routen[t["route_id"]]
            zaehl.setdefault(k, {}).setdefault(t["shape_id"], 0)
            zaehl[k][t["shape_id"]] += 1
    # je Linie die zwei häufigsten Linienwege (beide Richtungen; bei Abzweigungen sonst Lücken)
    wahl = {s: k for k, v in zaehl.items() for s, _ in sorted(v.items(), key=lambda x: -x[1])[:2]}
    punkte = {}
    for p in lesen("shapes.txt"):
        if p["shape_id"] in wahl:
            punkte.setdefault(p["shape_id"], []).append(
                (int(p["shape_pt_sequence"]), float(p["shape_pt_lon"]), float(p["shape_pt_lat"])))

    feats, gesehen = [], {}
    for s, pts in punkte.items():
        typ, linie, farbe = wahl[s]
        linie_geo = LineString([(x, y) for _, x, y in sorted(pts)])
        teil = linie_geo.intersection(bus_gebiet if typ == "bus" else bereich)
        if teil.is_empty:
            continue
        stuecke = [teil] if teil.geom_type == "LineString" else [g for g in getattr(teil, "geoms", []) if g.geom_type == "LineString"]
        for st in stuecke:
            if st.length < 0.002:
                continue
            st = st.simplify(EINFACH)
            # Gegenrichtung desselben Weges nicht doppelt zeichnen
            schon = gesehen.setdefault((typ, linie), [])
            if any(st.hausdorff_distance(a) < 0.0006 for a in schon):
                continue
            schon.append(st)
            feats.append({"type": "Feature", "properties": {"typ": typ, "linien": linie, "farbe": farbe},
                          "geometry": {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y in st.coords]}})

    url = ("https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0"
           "&typeName=ogdwien:UBAHNHALTOGD&srsName=EPSG:4326&outputFormat=json")
    stationen = {}
    for f in json.load(urllib.request.urlopen(url, timeout=120))["features"]:
        lon, lat = f["geometry"]["coordinates"]
        if not bereich.contains(Point(lon, lat)):
            continue
        name = f["properties"]["HTXT"]
        s = stationen.setdefault(name, {"lon": lon, "lat": lat, "linien": set()})
        s["linien"].add(f"U{f['properties']['LINFO']}")
    for name, s in stationen.items():
        feats.append({"type": "Feature", "properties": {"typ": "station", "name": name, "linien": " ".join(sorted(s["linien"]))},
                      "geometry": {"type": "Point", "coordinates": [round(s["lon"], 5), round(s["lat"], 5)]}})
    reihe = {"tram": 0, "bus": 1, "ubahn": 2, "station": 3}
    feats.sort(key=lambda f: reihe[f["properties"]["typ"]])
    (ROOT / "docs" / "geo" / "oeffis_ideen.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (ROOT / "docs" / "geo" / "ideen.json").write_text(json.dumps(ideen, ensure_ascii=False), encoding="utf-8")
    zahl = {t: sum(1 for f in feats if f["properties"]["typ"] == t) for t in reihe}
    print("geschrieben:", zahl)


if __name__ == "__main__":
    main()
