"""Liegt ein Punkt in unserem Suchgebiet?

Regeln:
- 8., 18., 19. Bezirk: ganz erlaubt, im 19. außer rote Zone (Heiligenstadt / Karl-Marx-Hof bis Gürtel)
- 9. Bezirk: erlaubt, außer rote Zone (Lichtental-Nord / Friedensbrücke)
- 1. und 2. Bezirk: nur in den blauen Zonen (mit Toleranzrand)
- alles andere: raus
"""
import json
import math

from .config import ROOT

K_LON = math.cos(math.radians(48.2)) * 111320
K_LAT = 110540
BEZIRK_TOLERANZ_M = 40
GANZ_ERLAUBT = {8, 18, 19}


def _load(name):
    return json.loads((ROOT / "geo" / name).read_text(encoding="utf-8"))["features"]


BEZIRKE = _load("bezirke.geojson")
ZONEN = _load("zones.geojson")


def _in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polygon(lon, lat, coords):
    return _in_ring(lon, lat, coords[0]) and not any(_in_ring(lon, lat, h) for h in coords[1:])


def _dist_ring_m(lon, lat, ring):
    px, py = lon * K_LON, lat * K_LAT
    best = float("inf")
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        ax, ay, bx, by = ax * K_LON, ay * K_LAT, bx * K_LON, by * K_LAT
        dx, dy = bx - ax, by - ay
        t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
    return best


def _abstand_m(lon, lat, feature):
    """0 wenn drin, sonst Abstand zum Rand in Metern."""
    c = feature["geometry"]["coordinates"]
    return 0 if _in_polygon(lon, lat, c) else _dist_ring_m(lon, lat, c[0])


def bezirksmitte(nr):
    """Ungefährer Mittelpunkt eines Bezirks (Mittel der Randpunkte) -> (lat, lon)."""
    for f in BEZIRKE:
        if f["properties"]["bezirk"] == nr:
            ring = f["geometry"]["coordinates"][0]
            return round(sum(y for _, y in ring) / len(ring), 6), round(sum(x for x, _ in ring) / len(ring), 6)
    return None


def bezirk_von(lat, lon):
    best, nr = BEZIRK_TOLERANZ_M, None
    for f in BEZIRKE:
        d = _abstand_m(lon, lat, f)
        if d == 0:
            return f["properties"]["bezirk"]
        if d < best:
            best, nr = d, f["properties"]["bezirk"]
    return nr


def pruefe_umkreis(lat, lon, radius):
    """Für versetzte Punkte (echte Lage irgendwo im Umkreis): Mitte plus 16 Punkte auf zwei Ringen
    prüfen. -> (Ergebnis der Mitte wie pruefe(), Anteil der Prüfpunkte, die passen)"""
    punkte = [(lat, lon)]
    for f in (0.5, 1.0):
        for k in range(8):
            w = k * math.pi / 4
            punkte.append((lat + f * radius * math.sin(w) / K_LAT, lon + f * radius * math.cos(w) / K_LON))
    ergebnisse = [pruefe(*p) for p in punkte]
    return ergebnisse[0], sum(e[0] for e in ergebnisse) / len(ergebnisse)


def pruefe(lat, lon):
    """-> (drin: bool, begruendung: str, bezirk: int|None)"""
    bez = bezirk_von(lat, lon)
    for z in ZONEN:
        p = z["properties"]
        if p["rolle"] != "ausgeschlossen" or (p.get("nur_in_bezirk") and p["nur_in_bezirk"] != bez):
            continue
        if _abstand_m(lon, lat, z) <= p.get("puffer_m", 0):
            return False, f"rote Zone: {p['name']}", bez
    if bez in GANZ_ERLAUBT or bez == 9:
        return True, f"{bez}. Bezirk", bez
    for z in ZONEN:
        p = z["properties"]
        if p["rolle"] != "erlaubt":
            continue
        d = _abstand_m(lon, lat, z)
        if d == 0:
            return True, f"Zone {p['name']}", bez
        if d <= p.get("puffer_m", 0):
            return True, f"Randlage Zone {p['name']} ({round(d)} m außerhalb)", bez
    if bez in (1, 2):
        return False, f"{bez}. Bezirk außerhalb der blauen Zone", bez
    return False, f"{bez}. Bezirk" if bez else "außerhalb der Suchbezirke", bez
