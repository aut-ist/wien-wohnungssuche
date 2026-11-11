"""Schulweg-Gebiet für die Hernals-Zone (Wunsch 2026-11-11: Kinder sollen nicht im 17. Bezirk in die Schule müssen).

Regeln in Wien (Bildungsdirektion, Stand 2024/25 und 2025/26):
- Volksschule: keine Schulsprengel. Ist eine Schule überbucht, teilt die Bildungsdirektion nach Schulweg,
  Geschwistern und Platz zu (§ 46 Wiener Schulgesetz). Wer näher an einer anderen Schule wohnt, kommt eher dorthin.
- AHS (Gymnasium): Reihung nach Eignung, Geschwistern, dann Wohnortnähe/Schulweg. Die Nähe ist relativ (wer sonst
  angemeldet ist) und schließt ein, ob eine andere AHS leichter erreichbar ist. Eine feste Grenze (1 km, 10 min) gibt es nicht.

Deshalb: ein Punkt der Zone bleibt, wenn zu Fuß die nächste öffentliche Volksschule und die nächste öffentliche AHS
außerhalb des 17. höchstens TOLERANZ_M weiter weg sind als die nächste im 17. (Wunsch 2026-11-11: im Zweifelsfall mit
rein nehmen; Gleichstand ist Zweifelsfall).
Die Dependance des G 18 Klostergasse in der Wielemansgasse zählt als 18.
Schulen: data.wien.gv.at SCHULEOGD; Fußwege: OSM-Routing (routing.openstreetmap.de, FOSSGIS).
Ergebnis: geo/schulweg_hernals.geojson (ein Feature je Teilgebiet), tools/build_zones.py schneidet die Zone damit.

    python tools/schulweg_zone.py      (braucht shapely, lokal laufen lassen, dauert ca. 1 Minute)
"""
import json
import time
import urllib.request
from pathlib import Path

from shapely.geometry import Point, Polygon, box, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
TOLERANZ_M = 50  # im Zweifel drin: außen darf bis zu so viel weiter sein
SCHRITT_LON, SCHRITT_LAT = 0.0005, 0.0003  # ca. 37 x 33 m
SCHULEN_URL = ("https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0&typeName=ogdwien:SCHULEOGD"
               "&srsName=EPSG:4326&outputFormat=json&bbox=16.30,48.20,16.37,48.245,EPSG:4326")
ROUTING = "https://routing.openstreetmap.de/routed-foot/table/v1/driving/"


def _laden(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wien-wohnungssuche (privat)"})
    for versuch in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=120))
        except Exception as e:  # Dienst kurz überlastet
            if versuch == 2:
                raise
            print("neuer Versuch:", e)
            time.sleep(5)


def main():
    schulen = []
    for f in _laden(SCHULEN_URL)["features"]:
        p = f["properties"]
        art = p.get("ART_TXT") or ""
        if not art.startswith(("Volksschule (ö", "Allgemeinbildende höhere Schule (ö")):
            continue
        x, y = f["geometry"]["coordinates"]
        if not (16.315 < x < 16.36 and 48.21 < y < 48.235):
            continue
        bez = 18 if "Klostergasse" in p["NAME"] else int(p["ADRESSE"].split(".")[0])
        schulen.append(("VS" if art.startswith("Volks") else "AHS", bez, p["NAME"], x, y))
    # die ganze ursprüngliche Zone nehmen (GEO_ZONEN in build_zones), nicht die schon geschnittene
    from build_zones import GEO_ZONEN
    gebiet = Polygon([(lon, lat) for lat, lon in GEO_ZONEN["hernals"]]).buffer(0.0003)
    minx, miny, maxx, maxy = gebiet.bounds
    pts = [(round(minx + i * SCHRITT_LON, 6), round(miny + j * SCHRITT_LAT, 6))
           for j in range(int((maxy - miny) / SCHRITT_LAT) + 2) for i in range(int((maxx - minx) / SCHRITT_LON) + 2)]
    pts = [p for p in pts if gebiet.contains(Point(p))]
    ok = []
    for k in range(0, len(pts), 60):
        teil = pts[k:k + 60]
        n = len(teil)
        url = (ROUTING + ";".join(f"{a},{b}" for a, b in teil + [(s[3], s[4]) for s in schulen])
               + f"?sources={';'.join(map(str, range(n)))}"
               + f"&destinations={';'.join(str(n + i) for i in range(len(schulen)))}&annotations=distance")
        for p, zeile in zip(teil, _laden(url)["distances"]):
            def naechste(art, im_17):
                return min((d for d, s in zip(zeile, schulen) if d is not None and s[0] == art and (s[1] == 17) == im_17),
                           default=1e9)
            if (naechste("VS", False) <= naechste("VS", True) + TOLERANZ_M
                    and naechste("AHS", False) <= naechste("AHS", True) + TOLERANZ_M):
                ok.append(p)
        time.sleep(1.5)
    zellen = unary_union([box(a - SCHRITT_LON / 2, b - SCHRITT_LAT / 2, a + SCHRITT_LON / 2, b + SCHRITT_LAT / 2)
                          for a, b in ok])
    glatt = zellen.buffer(0.0002).buffer(-0.0002).simplify(0.00003)
    teile = [glatt] if glatt.geom_type == "Polygon" else list(glatt.geoms)
    out = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"toleranz_m": TOLERANZ_M}, "geometry": mapping(g)}  # mit Löchern
        for g in teile]}
    (ROOT / "geo" / "schulweg_hernals.geojson").write_text(json.dumps(out), encoding="utf-8")
    print(f"{len(ok)} von {len(pts)} Gitterpunkten näher an Schulen außerhalb des 17., {len(teile)} Teilgebiet(e)")


if __name__ == "__main__":
    main()
