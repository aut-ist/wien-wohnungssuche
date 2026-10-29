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
# Bahnstationen aus geo/oeffis.geojson
HEILIGENSTADT = (48.24908, 16.36571)
OBERDOEBLING = (48.24447, 16.34428)
KROTTENBACHSTRASSE = (48.24008, 16.34096)
SPITTELAU = (48.23562, 16.3582)
NUSSDORFER_STRASSE = (48.2315, 16.35287)

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
    # Handy-Screenshot 1080x2400 vom 2026-10-29, Karte um ca. 20° gedreht (daher "gedreht").
    # Linie = Rand der orangen Fläche, automatisch abgetastet und geglättet; Restfehler der
    # Referenzpunkte 10–20 m.
    "heiligenstadt_rot": {
        "gedreht": True,
        "refs": [((792, 740), HEILIGENSTADT), ((178, 1204), OBERDOEBLING), ((156, 1454), KROTTENBACHSTRASSE),
                 ((792, 1466), SPITTELAU), ((678, 1738), NUSSDORFER_STRASSE)],
        "line": [(730, 645), (721, 675), (719, 705), (719, 735), (736, 765), (736, 795), (736, 825),
                 (742, 855), (746, 885), (744, 915), (742, 945), (744, 975), (748, 1005), (748, 1035),
                 (743, 1065), (739, 1095), (734, 1125), (731, 1155), (727, 1185), (725, 1215), (724, 1245),
                 (726, 1275), (730, 1305), (742, 1335), (744, 1365), (747, 1395), (747, 1425), (753, 1455),
                 (753, 1485), (758, 1515), (758, 1545), (758, 1575), (756, 1605), (748, 1635), (675, 1635),
                 (672, 1605), (677, 1575), (672, 1545), (658, 1515), (653, 1485), (653, 1455), (649, 1425),
                 (616, 1395), (616, 1365), (618, 1335), (620, 1305), (624, 1275), (624, 1245), (619, 1215),
                 (612, 1185), (593, 1155), (589, 1125), (580, 1095), (570, 1065), (567, 1035), (561, 1005),
                 (555, 975), (545, 945), (534, 915), (501, 885), (489, 855), (463, 825), (457, 795),
                 (450, 765), (449, 735), (429, 705), (424, 675), (436, 645)],
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
}

ZONES = [
    {"id": "leopoldstadt", "rolle": "erlaubt", "name": "Karmeliterviertel / Augarten-Süd",
     "puffer_m": 50},
    {"id": "innere_stadt", "rolle": "erlaubt", "name": "Börse / Schottenviertel",
     "puffer_m": 50},
    {"id": "alsergrund_rot", "rolle": "ausgeschlossen", "name": "Lichtental-Nord / Friedensbrücke",
     "nur_in_bezirk": 9, "puffer_m": 0},
    # seit 2026-10-29: Streifen zwischen Hohe Warte/Döblinger Hauptstraße und Heiligenstädter Straße,
    # vom Karl-Marx-Hof bis kurz vor den Gürtel. Nicht zuschneiden: der Zuschnitt nimmt die konvexe
    # Hülle, die den schmalen Streifen um gut 20 % vergrößern würde; das Stück, das bei Spittelau in
    # den 9. ragt, liegt ohnehin in Lichtental-Nord und zählt dort nicht (nur_in_bezirk)
    {"id": "heiligenstadt_rot", "rolle": "ausgeschlossen", "name": "Heiligenstadt / Karl-Marx-Hof bis Gürtel",
     "nur_in_bezirk": 19, "puffer_m": 0, "zuschneiden": False},
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
        if z.get("nur_in_bezirk") and z.get("zuschneiden", True):
            # auf den Bezirk zuschneiden, damit die Karte nicht Nachbarbezirke rot färbt
            ring = auf_bezirk_zuschneiden(ring, z["nur_in_bezirk"])
        ring.append(ring[0])
        props = {k: v for k, v in z.items()}
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
    out = {"type": "FeatureCollection", "features": feats}
    path = ROOT / "geo" / "zones.geojson"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("geschrieben:", path)


if __name__ == "__main__":
    main()
