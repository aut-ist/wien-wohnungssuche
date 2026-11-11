"""Erzeugt geo/zones.geojson aus den eingezeichneten Screenshots.

Die Zonen wurden auf Google-Maps-Screenshots eingezeichnet. Pro Screenshot
gibt es Referenzpunkte (Pixel -> echte Koordinate, aus OpenStreetMap) und die
nachgezeichneten Pixel-Punkte der Linie. Daraus wird eine Transformation
gerechnet (Nord oben, Web-Mercator, Seitenverhältnis 1/cos(lat)).

Feinjustieren: Pixel-Punkte unten ändern und neu laufen lassen, oder die
fertige geo/zones.geojson direkt auf geojson.io bearbeiten.

    python tools/build_zones.py
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASPECT = 1 / math.cos(math.radians(48.22))

# Referenzpunkte: (pixel_x, pixel_y) -> (lat, lon)
FRIEDENSBRUECKE = (48.227837, 16.363975)
ROSSAUER_LAENDE = (48.222337, 16.367572)
SCHOTTENRING = (48.216560, 16.371945)
TABORSTRASSE = (48.219218, 16.381321)
VOTIVKIRCHE = (48.215414, 16.359140)
GAUSSPLATZ = (48.226238, 16.369830)
BURGTHEATER = (48.210337, 16.361477)
ANKERUHR = (48.210761, 16.373675)
MITTE_LANDSTRASSE = (48.20606, 16.38459)   # Station Wien Mitte-Landstraße (OGD)
HUNDERTWASSERHAUS = (48.20738, 16.39394)
RADETZKYPLATZ = (48.21086, 16.390449)
SCREENSHOTS = {
    "leopoldstadt": {
        "refs": [((423, 204), FRIEDENSBRUECKE), ((530, 521), ROSSAUER_LAENDE),
                 ((690, 859), SCHOTTENRING), ((1097, 738), TABORSTRASSE),
                 ((165, 935), VOTIVKIRCHE), ((635, 265), GAUSSPLATZ)],
        "line": [(805, 442), (845, 470), (870, 510), (900, 545), (935, 580), (960, 615),
                 (985, 650), (1010, 680), (1045, 712), (1095, 745), (1130, 775),
                 (1165, 808), (1200, 845), (1240, 875), (1270, 895), (1300, 925),
                 (1335, 960), (1360, 1000), (1380, 1045), (1365, 1070), (1335, 1090),
                 (1300, 1120), (1250, 1135), (1180, 1145), (1100, 1165), (1040, 1155),
                 (980, 1130), (950, 1100), (920, 1065), (885, 1030), (860, 1000),
                 (835, 960), (815, 920), (800, 880), (785, 840), (765, 800), (745, 775),
                 (720, 740), (700, 705), (670, 680), (655, 665), (660, 640), (645, 620),
                 (635, 595), (640, 565), (660, 535), (690, 510), (715, 480), (760, 460)],
    },
    # Saads Umriss vom 2026-11-01 abends auf der eigenen Karte (ersetzt die zwei groben Kritzeleien davor):
    # Weißgerberviertel vom Donaukanal bis Lorbeergasse, über Hetzgasse/Löwengasse bis unter das Hundertwasserhaus
    "weissgerber_rot": {
        "refs": [((178, 662), MITTE_LANDSTRASSE), ((722, 546), HUNDERTWASSERHAUS), ((530, 282), RADETZKYPLATZ),
                 ((422, 178), (48.211557, 16.38807)), ((372, 290), (48.210402, 16.387556))],  # Dißler-, Kolonitzgasse
        "line": [(230, 150), (270, 105), (330, 80), (420, 65), (500, 58), (560, 60), (600, 75), (660, 115), (720, 160),
                 (770, 210), (800, 260), (810, 320), (808, 380), (800, 430), (815, 470), (820, 500), (800, 520),
                 (760, 560), (720, 590), (690, 612), (675, 600), (690, 560), (700, 520), (680, 470), (650, 430),
                 (620, 400), (560, 385), (480, 380), (400, 375), (330, 355), (285, 320), (265, 270), (250, 210)],
    },
    "innere_stadt": {
        "refs": [((829, 182), SCHOTTENRING), ((152, 290), VOTIVKIRCHE),
                 ((283, 732), BURGTHEATER), ((965, 676), ANKERUHR)],
        "line": [(680, 78), (750, 85), (810, 120), (860, 160), (930, 220), (990, 280),
                 (1035, 350), (1060, 420), (1065, 470), (1050, 530), (1020, 580),
                 (980, 630), (940, 680), (900, 720), (850, 770), (800, 800), (750, 825),
                 (690, 835), (630, 830), (560, 805), (525, 770), (480, 750), (420, 725),
                 (360, 700), (320, 680), (300, 650), (285, 610), (285, 575), (300, 520),
                 (310, 470), (320, 430), (330, 390), (350, 360), (380, 330), (410, 300),
                 (440, 270), (480, 240), (530, 215), (575, 185), (620, 160), (660, 145),
                 (700, 125), (745, 100)],
    },
}

# Zonen, die entlang echter Straßen definiert sind (lat, lon) statt nachgezeichnet.
# Lichtental-Nord: Liechtensteinstraße (West, läuft fast genau nach Norden; bis 2026-10-27 war es die
# Nußdorfer Straße) – Gürtel/Spittelau (Nord) – Donaukanal/Friedensbrücke (Ost) – Alserbachstraße (Süd).
# Wird nur im 9. Bezirk angewendet, daher darf sie nach Norden/Osten überstehen.
GEO_ZONEN = {
    "alsergrund_rot": [(48.2254, 16.3571), (48.2264, 16.3567), (48.2281, 16.3561), (48.2300, 16.3561),
                       (48.2328, 16.3560), (48.2450, 16.3560), (48.2450, 16.3720), (48.2275, 16.3720),
                       (48.2272, 16.3650), (48.2262, 16.3600)],
    # Heiligenstadt: West = Straßenbahn 37 (Nußdorfer Straße, Döblinger Hauptstraße, Hohe Warte bis
    # zur Schleife, Punkte aus geo/oeffis.geojson), Nord = Kante von der Schleife zur Heiligenstädter
    # Straße beim Bahnhof (wie auf Saads Screenshot), dann gerade nach Osten; Ost/Süd = Bezirksgrenze
    # (Donaukanal, Gürtel) durch den Zuschnitt auf den 19.
    "heiligenstadt_rot": [(48.22963, 16.35015), (48.22978, 16.3503), (48.22989, 16.35073), (48.23038, 16.35088),
                          (48.23053, 16.35105), (48.23168, 16.35389), (48.2318, 16.35408), (48.23194, 16.35408),
                          (48.2323, 16.35384), (48.23329, 16.35323), (48.23384, 16.3529), (48.23436, 16.35279),
                          (48.23645, 16.3535), (48.2412, 16.35554), (48.24396, 16.35534), (48.24587, 16.35611),
                          (48.24687, 16.35583), (48.24745, 16.35547), (48.24821, 16.35518), (48.24904, 16.35506),
                          (48.25104, 16.35505), (48.25123, 16.35528), (48.2526, 16.35564), (48.25267, 16.3558),
                          (48.25274, 16.3572), (48.2512, 16.36483), (48.2512, 16.3900), (48.2250, 16.3900),
                          (48.2250, 16.35015)],
    # Landstraße (Saads Screenshot vom 2026-11-01): West = Wienfluss, Nord = Donaukanal (beides
    # Bezirksgrenze, daher hier großzügig nach außen und genau auf den 3. zugeschnitten), Süd = Rennweg
    # von St. Marx bis Schwarzenbergplatz (OSM), Ost = Saads Handlinie vom Donaukanal beim Kunst Haus
    # Wien über U3 Kardinal-Nagl-Platz zum Rennweg (Screenshot mit 9 Referenzpunkten entzerrt, ±60 m).
    "landstrasse": [(48.2160, 16.3940), (48.21097, 16.39418), (48.21016, 16.39479), (48.2088, 16.3952),
                    (48.20744, 16.39561), (48.20607, 16.39622), (48.20499, 16.39684), (48.2039, 16.39765),
                    (48.20281, 16.39868), (48.20226, 16.39929), (48.2009, 16.3997), (48.19927, 16.40031),
                    (48.19764, 16.40092), (48.19682, 16.40154), (48.19491, 16.40154), (48.19328, 16.40133),
                    (48.19219, 16.40092), (48.19138, 16.40031), (48.19056, 16.39929), (48.18947, 16.39888),
                    (48.19072, 16.39696), (48.19174, 16.39524), (48.19276, 16.39294), (48.19369, 16.39023),
                    (48.19442, 16.3866), (48.19493, 16.38526), (48.19573, 16.38326), (48.19698, 16.38041),
                    (48.19788, 16.37812), (48.2000, 16.3740), (48.2160, 16.3700)],
    # Hernals (Wunsch 2026-11-11): Dreieck zwischen Kalvarienberggasse (West, 20 m westlich der Straßenmitte, die
    # Westseite der Geschäftsstraße bleibt draußen), 18er-Grenze (Nord/Ost) und Jörgerstraße (Süd, 35 m nördlich
    # der Straßenmitte, die Jörgerstraße selbst bleibt draußen). Punkte aus OpenStreetMap; Nord/Ost großzügig,
    # wird genau auf den 17. zugeschnitten. Gebäudedaten der Stadt: fast nur Gründerzeit, kaum Gemeindebauten.
    "hernals": [(48.218647, 16.332256), (48.219047, 16.332387), (48.219115, 16.332409), (48.219179, 16.332431), (48.219747, 16.332631),
                (48.22039, 16.332856), (48.220891, 16.333331), (48.2217, 16.33411), (48.222441, 16.334831), (48.223259, 16.335604),
                (48.225, 16.335604), (48.225, 16.342), (48.217644, 16.342), (48.217644, 16.341662), (48.217652, 16.341545),
                (48.217804, 16.340423), (48.217887, 16.339866), (48.217942, 16.339545), (48.217971, 16.339321), (48.217972, 16.339219),
                (48.217992, 16.338831), (48.218017, 16.338533), (48.218048, 16.338202), (48.218061, 16.338019), (48.218062, 16.33798),
                (48.218057, 16.337931), (48.218, 16.33755), (48.217972, 16.33738), (48.217931, 16.337109), (48.21793, 16.337047),
                (48.21793, 16.337005), (48.217931, 16.336958), (48.217934, 16.336913), (48.217938, 16.336882), (48.217941, 16.336855),
                (48.218196, 16.335427), (48.218208, 16.335357), (48.218233, 16.335258), (48.218342, 16.334989), (48.218431, 16.334756),
                (48.21845, 16.33467), (48.218466, 16.334564), (48.218479, 16.334458), (48.218484, 16.334345), (48.218489, 16.334094),
                (48.218459, 16.332838), (48.218452, 16.332593), (48.218451, 16.332527), (48.218476, 16.332379)],
}

ZONES = [
    {"id": "leopoldstadt", "rolle": "erlaubt", "name": "Karmeliterviertel / Augarten-Süd",
     "puffer_m": 50},
    {"id": "innere_stadt", "rolle": "erlaubt", "name": "Börse / Schottenviertel",
     "puffer_m": 50},
    # seit 2026-11-01 abends zusätzlich nur, was zu Fuß höchstens 700 m von U Landstraße oder U Rochusgasse liegt
    # (Saad: max. 10 min zu Fuß; Polygon aus tools/fussweg_zone.py)
    {"id": "landstrasse", "rolle": "erlaubt", "name": "Landstraße: max. 10 min zu Fuß zu U Landstraße/Rochusgasse",
     "nur_in_bezirk": 3, "puffer_m": 50, "zuschneiden": "genau", "fussweg": "fussweg_landstrasse.geojson"},
    # streng: auch ungefähre Lagen darin sind raus (Saad 2026-11-01); wird wie die anderen roten Zonen gezeichnet
    {"id": "weissgerber_rot", "rolle": "ausgeschlossen", "name": "Weißgerberviertel / Hundertwasserhaus (zu weit zur U-Bahn)",
     "nur_in_bezirk": 3, "puffer_m": 0, "zuschneiden": "genau", "streng": True},
    {"id": "alsergrund_rot", "rolle": "ausgeschlossen", "name": "Lichtental-Nord / Friedensbrücke",
     "nur_in_bezirk": 9, "puffer_m": 0},
    # seit 2026-10-29: im 19. alles östlich der Straßenbahn 37 (Döblinger Hauptstraße/Hohe Warte) bis zum
    # Donaukanal, vom Gürtel bis Heiligenstadt. Genau zuschneiden (shapely): der alte Zuschnitt nimmt die
    # konvexe Hülle der Zone, die würde hier über die Straßenbahn nach Westen greifen.
    # seit 2026-11-11: ein Stück Hernals unter der 18er-Grenze, ohne Toleranzrand (sonst wären Jörgerstraße und
    # Westseite der Kalvarienberggasse wieder drin)
    # Seit dem Abend nur noch, wo die nächste öffentliche Volksschule und AHS zu Fuß nicht im 17. liegen
    # (Saad: Kinder sollen nicht im 17. in die Schule; tools/schulweg_zone.py). Ergibt mehrere Teilgebiete.
    {"id": "hernals", "rolle": "erlaubt", "name": "Hernals: Kalvarienberggasse bis 18er-Grenze, ohne Jörgerstraße",
     "nur_in_bezirk": 17, "puffer_m": 0, "zuschneiden": "genau", "fussweg": "schulweg_hernals.geojson"},
    {"id": "heiligenstadt_rot", "rolle": "ausgeschlossen", "name": "Heiligenstadt: Straßenbahn 37 bis Donaukanal",
     "nur_in_bezirk": 19, "puffer_m": 0, "zuschneiden": "genau"},
]


def fit(refs):
    """Least squares für x = ax + s*lon, y = ay - s*ASPECT*lat (3 Parameter)."""
    n = len(refs)
    # Normalgleichungen von Hand, damit kein numpy nötig ist
    sx = sum(p[0] for p, _ in refs); sy = sum(p[1] for p, _ in refs)
    slon = sum(g[1] for _, g in refs); slat = sum(g[0] for _, g in refs)
    # s minimiert sum((x - mx) - s(lon - mlon))^2 + ((y - my) + s*k(lat - mlat))^2
    mx, my, mlon, mlat = sx / n, sy / n, slon / n, slat / n
    num = sum((p[0] - mx) * (g[1] - mlon) - (p[1] - my) * ASPECT * (g[0] - mlat) for p, g in refs)
    den = sum((g[1] - mlon) ** 2 + (ASPECT * (g[0] - mlat)) ** 2 for _, g in refs)
    s = num / den
    return lambda x, y: (mlat - (y - my) / (s * ASPECT), mlon + (x - mx) / s)


def fit_gedreht(refs):
    """Wie fit(), aber mit Drehung (gedrehte Handykarte): Ähnlichkeitstransformation, komplex gerechnet."""
    k_lon = math.cos(math.radians(48.22)) * 111320
    k_lat = 110540
    lat0, lon0 = refs[0][1]
    w = [complex((g[1] - lon0) * k_lon, -(g[0] - lat0) * k_lat) for _, g in refs]  # Osten, Süden in m
    z = [complex(*p) for p, _ in refs]
    mz, mw = sum(z) / len(z), sum(w) / len(w)
    a = sum((zi - mz) * (wi - mw).conjugate() for zi, wi in zip(z, w)) / sum(abs(wi - mw) ** 2 for wi in w)

    def to_geo(x, y):
        m = (complex(x, y) - mz) / a + mw
        return lat0 - m.imag / k_lat, lon0 + m.real / k_lon
    return to_geo


def _huelle(pts):
    """Konvexe Hülle (Andrew), gegen den Uhrzeigersinn."""
    pts = sorted(set(map(tuple, pts)))

    def kreuz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    unten, oben = [], []
    for p in pts:
        while len(unten) >= 2 and kreuz(unten[-2], unten[-1], p) <= 0:
            unten.pop()
        unten.append(p)
    for p in reversed(pts):
        while len(oben) >= 2 and kreuz(oben[-2], oben[-1], p) <= 0:
            oben.pop()
        oben.append(p)
    return unten[:-1] + oben[:-1]


def auf_bezirk_zuschneiden(zone, bezirk):
    """Bezirksgrenze (Sutherland-Hodgman) an der konvexen Hülle der Zone abschneiden."""
    bez = json.loads((ROOT / "geo" / "bezirke.geojson").read_text(encoding="utf-8"))
    ring = next(f["geometry"]["coordinates"][0] for f in bez["features"] if f["properties"]["bezirk"] == bezirk)
    huelle = _huelle(zone)
    poly = [tuple(p) for p in ring[:-1]]
    for i in range(len(huelle)):
        a, b = huelle[i], huelle[(i + 1) % len(huelle)]
        innen = lambda p: (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0  # noqa: E731

        def schnitt(p, q):
            dx1, dy1, dx2, dy2 = q[0] - p[0], q[1] - p[1], b[0] - a[0], b[1] - a[1]
            t = ((a[0] - p[0]) * dy2 - (a[1] - p[1]) * dx2) / (dx1 * dy2 - dy1 * dx2)
            return (p[0] + t * dx1, p[1] + t * dy1)
        neu = []
        for j in range(len(poly)):
            p, q = poly[j - 1], poly[j]
            if innen(q):
                if not innen(p):
                    neu.append(schnitt(p, q))
                neu.append(q)
            elif innen(p):
                neu.append(schnitt(p, q))
        poly = neu
    return [[round(x, 6), round(y, 6)] for x, y in poly]


def genau_zuschneiden(zone, bezirk):
    """Zone exakt mit der Bezirksfläche schneiden (braucht shapely, nur lokal beim Zonenbauen)."""
    from shapely.geometry import Polygon
    bez = json.loads((ROOT / "geo" / "bezirke.geojson").read_text(encoding="utf-8"))
    ring = next(f["geometry"]["coordinates"][0] for f in bez["features"] if f["properties"]["bezirk"] == bezirk)
    teil = Polygon(zone).intersection(Polygon(ring))
    if teil.geom_type != "Polygon":  # Splitter an der Grenze: das größte Stück
        teil = max(teil.geoms, key=lambda g: g.area)
    return [[round(x, 6), round(y, 6)] for x, y in teil.exterior.coords[:-1]]


def main():
    feats = []
    for z in ZONES:
        if z["id"] in GEO_ZONEN:
            ring = GEO_ZONEN[z["id"]]
        else:
            shot = SCREENSHOTS[z["id"]]
            to_geo = (fit_gedreht if shot.get("gedreht") else fit)(shot["refs"])
            ring = [to_geo(x, y) for x, y in shot["line"]]
        ring = [[round(lon, 6), round(lat, 6)] for lat, lon in ring]
        ringe = [ring]
        if z.get("fussweg") and (ROOT / "geo" / z["fussweg"]).exists():
            # Fußweg-/Schulweg-Gebiet: kann aus mehreren Teilen bestehen, dann ein Zonen-Eintrag je Teil
            from shapely.geometry import Polygon, shape
            from shapely.ops import unary_union
            fw = json.loads((ROOT / "geo" / z["fussweg"]).read_text(encoding="utf-8"))["features"]
            teil = Polygon(ring).intersection(unary_union([shape(f["geometry"]) for f in fw]))
            if z.get("zuschneiden") == "genau":  # erst auf den Bezirk, dann teilen (sonst bliebe nur das größte Stück)
                bez = json.loads((ROOT / "geo" / "bezirke.geojson").read_text(encoding="utf-8"))["features"]
                teil = teil.intersection(Polygon(next(f["geometry"]["coordinates"][0] for f in bez
                                                      if f["properties"]["bezirk"] == z["nur_in_bezirk"])))
            teile = [teil] if teil.geom_type == "Polygon" else [g for g in teil.geoms if g.geom_type == "Polygon"]
            teile = [g for g in teile if g.area > 1e-8]  # Splitter unter ca. 70 m² weg
            ringe = [[[round(x, 6), round(y, 6)] for x, y in g.exterior.coords[:-1]] for g in teile]
        for i, ring in enumerate(ringe):
            if z.get("fussweg") and len(ringe) > 1:
                pass  # schon oben auf den Bezirk geschnitten
            elif z.get("zuschneiden") == "genau":
                ring = genau_zuschneiden(ring, z["nur_in_bezirk"])
            elif z.get("nur_in_bezirk") and z.get("zuschneiden", True):
                # auf den Bezirk zuschneiden, damit die Karte nicht Nachbarbezirke rot färbt
                ring = auf_bezirk_zuschneiden(ring, z["nur_in_bezirk"])
            ring.append(ring[0])
            props = {k: v for k, v in z.items()}
            if i:
                props["id"] = f"{z['id']}_{i + 1}"
            feats.append({"type": "Feature", "properties": props,
                          "geometry": {"type": "Polygon", "coordinates": [ring]}})
    out = {"type": "FeatureCollection", "features": feats}
    path = ROOT / "geo" / "zones.geojson"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("geschrieben:", path)


if __name__ == "__main__":
    main()
