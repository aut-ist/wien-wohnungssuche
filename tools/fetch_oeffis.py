"""Öffis fürs Suchgebiet -> geo/oeffis.geojson

Gebiet: 8., 9., 18., 19. Bezirk und der erlaubte Teil des 2. (blaue Zone Karmeliterviertel/Augarten);
der 8./9./2. seit 2026-10-29 (Wunsch), vorher nur 18./19.
- Straßenbahn, Bus und U-Bahn aus dem GTFS-Fahrplan der Wiener Linien (aktuelle Linienwege und
  offizielle Linienfarben). Bis 2026-10-29 kamen sie aus OEFFLINIENOGD (data.wien.gv.at), das ist
  veraltet: 13A endete dort an der Lerchenfelder Straße, die 2 fuhr noch durch die Josefstädter Straße.
- Nur Linien, die wirklich durchs Gebiet fahren, und nur das Stück im Gebiet (plus RAND_M, damit sie
  bis zu den Stationen am Rand reichen).
- S-Bahn-Strecken und U-/S-Stationen weiter von data.wien.gv.at (die S-Bahn fährt die ÖBB, nicht im GTFS).

Braucht shapely (nur lokal beim Erzeugen).

    python tools/fetch_oeffis.py [gtfs.zip]   (ohne ZIP wird es geladen, ~100 MB)
"""
import csv
import io
import json
import math
import re
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wohnungen import geo  # noqa: E402
from fetch_bezirke import simplify  # noqa: E402

WFS = ("https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0"
       "&typeName=ogdwien:{}&srsName=EPSG:4326&outputFormat=json")
GTFS = "https://www.wienerlinien.at/ogd_realtime/doku/ogd/gtfs/gtfs.zip"
GTFS_TYPEN = {"0": "tram", "1": "ubahn", "3": "bus"}
# Sonderfahrpläne (Baustelle, Marathon, Song Contest ...) nicht zeichnen, nur den normalen Linienweg
SONDER = re.compile(r"Baustelle|ESC|Fahrplan (am|vom)|Night-Run|Radrundfahrt|Festwochen|VCM", re.I)
NUR_SELTEN = 0.05     # Linienwege mit weniger als 5 % der Fahrten der häufigsten (Einschübe, Depotfahrten) weg
GLEICH_M = 20         # so nah an einem schon gezeichneten Stück derselben Linie: Gegenrichtung, nicht doppelt
# U-Bahn-Richtungen liegen in getrennten Tunnelröhren teils weiter auseinander (U2 Schottenring–Taborstraße
# war am 2026-11-01 doppelt zu sehen): dort erst ab 120 m Abstand als eigener Weg zeichnen
GLEICH_M_UBAHN = 120
GEBIETE = ([f for f in geo.BEZIRKE if f["properties"]["bezirk"] in (8, 9, 18, 19)]
           # alle blauen Zonen (seit 2026-11-16 auch Innere Stadt, Botschaftsviertel, Wieden/Margareten, Hernals)
           + [f for f in geo.ZONEN if not f["properties"]["id"].endswith("_rot")])
RAND_M = 120          # damit die Linien bis zu den Stationen am Rand (Gürtel) reichen
MIN_IM_GEBIET_M = 400  # so viel muss eine Linie im Gebiet fahren, um zu zählen
STATION_RAND_M = 250
# Zukünftige U5 (Stadt Wien, Stand 2026-10): übernimmt Karlsplatz–Rathaus von der U2, Betrieb bis
# Frankhplatz ab 2030; 2. Baustufe bis Hernals Baustart ab 2028, fertig Mitte der 2030er. Neue Strecke
# Station zu Station gerade gezeichnet (Tunnelverlauf nicht veröffentlicht), Koordinaten aus OSM/OGD.
# Wunsch (2026-10-29): so zeichnen, als gäbe es sie schon (durchgezogen, normale Station). Die Öffi-Zeiten
# zum Gürtel (tools/oeffi_zeiten.py) rechnen weiter ohne U5.
U5_FARBE = "#0097A0"  # Türkis
U5_STATIONEN = [  # Name, (lon, lat), andere U-/S-Linien dort (für Stationen außerhalb der OGD-Liste)
    ("Karlsplatz", (16.3689, 48.20088), ["U1", "U2", "U4"]), ("Museumsquartier", (16.36141, 48.20254), ["U2"]),
    ("Volkstheater", (16.35794, 48.20516), []), ("Rathaus", (16.35535, 48.21003), []),
    ("Frankhplatz", (16.35555, 48.21501), []), ("Arne-Karlsson-Park", (16.35374, 48.22128), []),
    ("Michelbeuern-AKH", (16.34425, 48.22124), []), ("Elterleinplatz", (16.3313, 48.21813), []),
    ("Hernals", (16.31485, 48.22328), ["S45"]),
]
REIHENFOLGE = {"ubahn": 0, "sbahn": 1, "tram": 2, "bus": 3}  # Bus zuletzt: gestrichelt über der Straßenbahn sichtbar


def _laden(name):
    with urllib.request.urlopen(WFS.format(name), timeout=120) as r:
        return json.load(r)["features"]


def _abstand(lon, lat):
    return min(geo._abstand_m(lon, lat, f) for f in GEBIETE)


def _laenge_m(a, b):
    return math.hypot((a[0] - b[0]) * geo.K_LON, (a[1] - b[1]) * geo.K_LAT)


def _im_gebiet(line, box):
    """Stücke einer Linie (lon, lat) nahe am Gebiet und die Meter direkt im Gebiet."""
    stuecke, teil, drin_m = [], [], 0.0
    vorher = None
    for p in line + [None]:
        if p is not None and box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]:
            d = _abstand(*p)
            if vorher is not None and d == 0 and vorher[1] == 0:
                drin_m += _laenge_m(vorher[0], p)
            vorher = (p, d)
            if d <= RAND_M:
                teil.append(p)
                continue
        else:
            vorher = None
        if len(teil) >= 2:
            stuecke.append(teil)
        teil = []
    return stuecke, drin_m


def _gtfs_lesen(z):
    """Linienwege (Fahrten je Linienweg, Farben, Punkte) aus dem GTFS-ZIP."""
    lesen = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), "utf-8-sig"))  # noqa: E731

    routen = {}
    for r in lesen("routes.txt"):
        typ = GTFS_TYPEN.get(r["route_type"])
        if typ and not re.match(r"N\d", r["route_short_name"]):  # Nachtbusse nicht
            routen[r["route_id"]] = (typ, r["route_short_name"].strip(), "#" + r["route_color"],
                                     bool(SONDER.search(r["route_long_name"])))
    # Fahrten je Linienweg zählen, Sonderfahrpläne nur falls eine Linie gar nichts anderes hat
    fahrten, sonder = {}, {}
    for t in lesen("trips.txt"):
        ro = routen.get(t["route_id"])
        if not ro:
            continue
        ziel = sonder if ro[3] else fahrten
        k = (ro[0], ro[1])
        ziel.setdefault(k, {}).setdefault(t["shape_id"], 0)
        ziel[k][t["shape_id"]] += 1
    for k, v in sonder.items():
        fahrten.setdefault(k, v)
    farbe = {(ro[0], ro[1]): ro[2] for ro in routen.values()}
    shape_linie = {}
    for k, shapes in fahrten.items():
        top = max(shapes.values())
        for s, n in shapes.items():
            if n >= top * NUR_SELTEN:
                shape_linie[s] = k

    punkte = {}
    for p in lesen("shapes.txt"):
        if p["shape_id"] in shape_linie:
            punkte.setdefault(p["shape_id"], []).append(
                (int(p["shape_pt_sequence"]), float(p["shape_pt_lon"]), float(p["shape_pt_lat"])))
    return fahrten, shape_linie, farbe, punkte


def _gtfs_linien(box):
    """{(typ, linie): {"farbe", "stuecke": [[(lon, lat), ...]], "drin_m"}} aus dem Wiener-Linien-GTFS."""
    with tempfile.TemporaryDirectory() as tmp:
        pfad = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tmp) / "gtfs.zip"  # schon geladenes ZIP
        if not pfad.exists():
            with urllib.request.urlopen(GTFS, timeout=600) as r, open(pfad, "wb") as f:
                while block := r.read(1 << 20):
                    f.write(block)
        with zipfile.ZipFile(pfad) as z:
            fahrten, shape_linie, farbe, punkte = _gtfs_lesen(z)
    linien = {}
    # häufigster Linienweg zuerst, damit seltenere nur ihre Abweichungen beitragen
    for s in sorted(punkte, key=lambda s: -fahrten[shape_linie[s]][s]):
        line = [(x, y) for _, x, y in sorted(punkte[s])]
        stuecke, drin_m = _im_gebiet(line, box)
        if not stuecke:
            continue
        e = linien.setdefault(shape_linie[s], {"farbe": farbe[shape_linie[s]], "stuecke": [], "drin_m": 0.0,
                                               "roh": line})  # häufigster Weg ganz, für die U5
        e["stuecke"].append(stuecke)
        e["drin_m"] = max(e["drin_m"], drin_m)
    return linien


def _luecken_schliessen(teile, max_m):
    """Hängt ein Stück an das vorige, wenn es höchstens max_m nach dessen Ende beginnt (eine Richtung)."""
    out = []
    for t in teile:
        if out and _laenge_m(out[-1][-1], t[0]) <= max_m:
            out[-1] = list(out[-1]) + list(t)
        else:
            out.append(list(t))
    return out


def _ohne_doppelte(stuecke_je_weg, gleich_m=GLEICH_M):
    """Gegenrichtung und Varianten derselben Linie nur dort zeichnen, wo sie woanders fahren."""
    from shapely.geometry import LineString, MultiLineString, Point
    gezeichnet, raus = [], []
    for stuecke in stuecke_je_weg:
        schon = MultiLineString(gezeichnet) if gezeichnet else None
        for teil in stuecke:
            neu, lauf = [], []
            for i, p in enumerate(teil):
                weit = schon is None or schon.distance(Point(p)) * geo.K_LAT > gleich_m
                if weit:
                    if not lauf and i > 0:
                        lauf.append(teil[i - 1])  # an das schon gezeichnete Stück anschließen
                    lauf.append(p)
                elif lauf:
                    lauf.append(p)
                    neu.append(lauf)
                    lauf = []
            if lauf:
                neu.append(lauf)
            for n in neu:
                if len(n) >= 2 and sum(_laenge_m(n[i], n[i + 1]) for i in range(len(n) - 1)) > gleich_m:
                    raus.append(n)
        gezeichnet += [LineString(t) for t in stuecke]
    return raus


# S-Bahn-Abschnitte, die in OEFFLINIENOGD fehlen (Tunnel, Brücken), aus OpenStreetMap; Saad 2026-11-22
OSM_STRECKEN = [
    # Stammstrecke Matzleinsdorfer Platz - Quartier Belvedere - Rennweg - Wien Mitte - Praterstern (großteils Tunnel;
    # in OSM wegen der Sperre 9/2026-10/2027 als railway=construction, die Sperre zeigen wir nicht an)
    ("48.176,16.350,48.224,16.400", ["S1", "S2", "S3", "S4", "S7"], None,
     [(16.35882, 48.18045), (16.3808, 48.1877), (16.38628, 48.19479), (16.38459, 48.20606), (16.39215, 48.21894)]),
    # S40 Franz-Josefs-Bahnhof - Spittelau - Heiligenstadt - Nußdorf (Lücken bei Spittelau und vor Nußdorf)
    # (hier auch über Nebengleise suchen: die Streckengleise sind in OSM nur über Weichen verbunden)
    ("48.222,16.335,48.292,16.375", ["S40"], "*",
     [(16.35885, 48.23287), (16.3588, 48.2355), (16.36571, 48.24908), (16.36768, 48.26023), (16.36633, 48.26455)]),
]


def _stammstrecke_osm():
    return [x for bbox, namen, strecke, halte in OSM_STRECKEN for x in _osm_strecke(bbox, namen, halte, strecke)]


def _osm_strecke(bbox, namen, halte, strecke=None):
    """Kürzester Weg über die Gleise (OSM railway=rail/construction, ohne Nebengleise) von Station zu Station.
    Liefert [(namen, koordinaten)] je Abschnitt; Umwege über andere Strecken werden verworfen."""
    import heapq
    import json as _j
    import urllib.parse
    nur = "" if strecke == "*" else f'[!"service"]["name"="{strecke}"]' if strecke else '[!"service"]'
    q = ('[out:json][timeout:90];way["railway"~"^(rail|construction)$"]' + nur +
         f'({bbox});out geom;')
    d = None
    for url in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                "https://overpass-api.de/api/interpreter"):
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers={"User-Agent": "wohnungssuche-karte/1.0"})
            d = _j.loads(urllib.request.urlopen(req, timeout=150).read())
            break
        except Exception as e:  # Overpass ist oft kurz überlastet (502/504)
            print("Overpass:", url, e)
    if not d:
        return []
    nb = {}
    for e in d["elements"]:
        pts = [(round(p["lon"], 7), round(p["lat"], 7)) for p in e.get("geometry", [])]
        for a_, b_ in zip(pts, pts[1:]):
            w = _laenge_m(a_, b_)
            nb.setdefault(a_, []).append((b_, w))
            nb.setdefault(b_, []).append((a_, w))
    if not nb:
        return []
    naechst = lambda p: min(nb, key=lambda k: _laenge_m(k, p))
    weg = []
    for von, bis in zip(halte, halte[1:]):
        s0, z = naechst(von), naechst(bis)
        dist, vor, todo = {s0: 0}, {}, [(0, s0)]
        while todo:
            dd, k = heapq.heappop(todo)
            if k == z:
                break
            if dd > dist.get(k, 1e18):
                continue
            for n, w in nb[k]:
                if dd + w < dist.get(n, 1e18):
                    dist[n], vor[n] = dd + w, k
                    heapq.heappush(todo, (dd + w, n))
        if z not in vor and z != s0:
            continue
        teil, k = [z], z
        while k != s0:
            k = vor[k]
            teil.append(k)
        teil = teil[::-1]
        # Umwege über andere Gleise verwerfen (Matzleinsdorf - Quartier Belvedere fand nur einen 8-km-Umweg)
        if sum(_laenge_m(x, y) for x, y in zip(teil, teil[1:])) <= 2.5 * _laenge_m(von, bis):
            weg.append(teil)
    return [(namen, t) for t in weg]


def _u5(u2):
    """U5: Karlsplatz–Rathaus im U2-Tunnel, dann gerade von Station zu Station."""
    def naechster(p):
        return min(range(len(u2)), key=lambda i: _laenge_m(u2[i], p))
    a, b = naechster(U5_STATIONEN[0][1]), naechster(U5_STATIONEN[3][1])
    alt = u2[min(a, b):max(a, b) + 1]
    if a > b:
        alt = alt[::-1]
    stufe1 = alt + [U5_STATIONEN[4][1]]
    stufe2 = [p for _, p, _ in U5_STATIONEN[4:]]
    return [{"type": "Feature", "properties": {"typ": "ubahn", "linien": "U5", "farbe": U5_FARBE},
             "geometry": {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y in simplify(line, 6)]}}
            for line in (stufe1, stufe2)]


def main():
    xs = [x for f in GEBIETE for x, _ in f["geometry"]["coordinates"][0]]
    ys = [y for f in GEBIETE for _, y in f["geometry"]["coordinates"][0]]
    box = (min(xs) - .005, min(ys) - .004, max(xs) + .005, max(ys) + .004)
    in_box = lambda p: box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]  # noqa: E731

    feats = []
    gtfs = _gtfs_linien(box)
    relevant = sorted((k for k, e in gtfs.items() if e["drin_m"] >= MIN_IM_GEBIET_M),
                      key=lambda k: (REIHENFOLGE[k[0]], len(k[1]), k[1]))
    for typ, linie in relevant:
        e = gtfs[(typ, linie)]
        teile = _ohne_doppelte(e["stuecke"], GLEICH_M_UBAHN if typ == "ubahn" else GLEICH_M)
        if typ == "ubahn":  # Stücke, die nur am Gebietsrand kurz unterbrochen sind, wieder verbinden
            teile = _luecken_schliessen(teile, 250)
        for teil in teile:
            props = {"typ": typ, "linien": linie}
            if typ == "ubahn":
                props["farbe"] = e["farbe"]
            feats.append({"type": "Feature", "properties": props,
                          "geometry": {"type": "LineString", "coordinates":
                                       [[round(a, 5), round(b, 5)] for a, b in simplify(teil, 6)]}})

    feats += _u5(gtfs[("ubahn", "U2")]["roh"])

    # S-Bahn-Strecken von data.wien.gv.at
    from shapely.geometry import LineString, Point, shape
    from shapely.ops import unary_union
    wien = unary_union([shape(f["geometry"]) for f in _laden("BEZIRKSGRENZEOGD")]).buffer(0.0003)
    sbahn = []
    for f in _laden("OEFFLINIENOGD"):
        if f["properties"]["LTYP"] != "5" or f["properties"].get("LTYPTXT") == "Zug":
            continue
        g = f["geometry"]
        for line in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            line = [tuple(p[:2]) for p in line]
            # ganz Wien, nicht nur ums Suchgebiet (Saad 2026-11-16: vom Hauptbahnhof ist man mit der S-Bahn
            # schnell in Wien Mitte usw., das soll man sehen)
            namen = [x.strip() for x in f["properties"]["LBEZEICHNUNG"].split(",") if x.strip()]
            schnitt = LineString(line).intersection(wien)  # nur innerhalb der Stadtgrenze
            for t in getattr(schnitt, "geoms", [schnitt]):
                if t.geom_type == "LineString" and t.length > 0:
                    sbahn.append((namen, list(t.coords)))
    # Stammstrecke im Tunnel (Quartier Belvedere - Rennweg - Wien Mitte - Praterstern) fehlt in OEFFLINIENOGD
    # (Saad 2026-11-22: "die Stadtlinien vom Hauptbahnhof über Wien Mitte nach Handelskai"): Gleis aus OpenStreetMap
    sbahn += _stammstrecke_osm()
    for namen, teil in sbahn:
        feats.insert(0, {"type": "Feature", "properties": {"typ": "sbahn", "linien": ", ".join(namen)},
                         "geometry": {"type": "LineString", "coordinates":
                                      [[round(a, 5), round(b, 5)] for a, b in simplify(teil, 6)]}})

    # U- und S-Bahn-Stationen (eine pro Name)
    s_netz = [(namen, teil, LineString(teil)) for namen, teil in sbahn]
    stationen = {}
    for f in _laden("OEFFHALTESTOGD"):
        p = f["properties"]
        if str(p["LTYP"]) not in ("4", "5"):
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        # S-Bahn-Halte in ganz Wien: LTYP 5 (Bahnhof) bis ca. 100 m neben einer S-Bahn-Strecke, mit Bahnlinien in
        # HLINIEN (oder abgeschnittener Liste wie am Hauptbahnhof, oder Rennweg, das dort nur Ersatzverkehr nennt).
        # Die S-Linien kommen von den Strecken daneben, weil HLINIEN abgeschnitten ist. Ohne die Bahn-Bedingung
        # kamen Bus-/Badner-Bahn-Halte wie Czartoryskigasse oder Gutheil-Schoder-Gasse dazu.
        s_linien = set()
        hl = str(p["HLINIEN"])
        bahn = re.search(r"(^|,)\s*(S\d+|R\d*|REX ?\d*|CJX\d*)\s*(,|$)", hl) or len(hl) > 200 or p["HTXTK"] == "Rennweg"
        if (str(p["LTYP"]) == "5" and bahn and "," not in p["HTXTK"] and "Autoreisezug" not in p["HTXTK"]
                and wien.contains(Point(lon, lat))):
            for namen, teil, linie in s_netz:
                if linie.distance(Point(lon, lat)) < 0.0012:
                    s_linien.update(namen)
        if not s_linien and (not in_box((lon, lat)) or _abstand(lon, lat) > STATION_RAND_M):
            continue
        name = p["HTXTK"].split(" (")[0]
        s = stationen.setdefault(name, {"lon": [], "lat": [], "linien": set()})
        s["lon"].append(lon); s["lat"].append(lat)
        s["linien"].update(x.strip() for x in str(p["HLINIEN"]).split(",") if x.strip())
        s["linien"].update(s_linien)
    # nur echte U-/S-Bahn-Stationen (keine Ersatzverkehr-Haltestellen), Label nur mit U-/S-Linien
    tag = re.compile(r"^(U\d|S\d+)$")
    stationen = {n: s for n, s in stationen.items() if any(tag.match(l) for l in s["linien"])}
    # Rennweg und Wien Mitte nennen in HLINIEN keine S-Linie (abgeschnitten bzw. nur Ersatzverkehr): S-Linien von Hand
    for name, linien in (("Rennweg", ["S1", "S2", "S3", "S4"]), ("Mitte-Landstraße", ["S1", "S2", "S3", "S4", "S7"])):
        if name in stationen:
            stationen[name]["linien"].update(linien)
        elif name == "Rennweg":
            stationen[name] = {"lon": [16.38628], "lat": [48.19479], "linien": set(linien)}
    # Quartier Belvedere (S-Bahn-Station seit 2012) hat in OEFFHALTESTOGD nur Straßenbahn-Halte: Punkt aus deren Mitte
    if "Quartier Belvedere" not in stationen:
        qb = [l.distance(Point(16.3808, 48.1877)) < 0.0012 and set(n) for n, _, l in s_netz]
        stationen["Quartier Belvedere"] = {"lon": [16.3808], "lat": [48.1877],
                                          "linien": set().union(*[x for x in qb if x]) or {"S1", "S2", "S3", "S4"}}
    for name, s in stationen.items():
        linien = sorted(l for l in s["linien"] if tag.match(l))
        feats.append({"type": "Feature",
                      "properties": {"typ": "station", "name": name, "linien": ", ".join(linien)},
                      "geometry": {"type": "Point", "coordinates": [round(sum(s["lon"]) / len(s["lon"]), 5),
                                                                    round(sum(s["lat"]) / len(s["lat"]), 5)]}})

    # U5-Stationen: bestehende Station bekommt die U5 dazu, sonst eigene Station
    vorhanden = {f["properties"]["name"]: f for f in feats if f["properties"]["typ"] == "station"}
    sortiert = lambda ls: ", ".join(sorted(set(ls), key=lambda l: (l[0] != "U", l)))  # noqa: E731
    for name, (x, y), andere in U5_STATIONEN:
        if name in vorhanden:
            p = vorhanden[name]["properties"]
            p["linien"] = sortiert(p["linien"].split(", ") + ["U5"])
        else:
            feats.append({"type": "Feature", "properties": {"typ": "station", "name": name,
                                                            "linien": sortiert(andere + ["U5"])},
                          "geometry": {"type": "Point", "coordinates": [x, y]}})

    path = ROOT / "geo" / "oeffis.geojson"
    # S-Bahn nie verlieren (2026-11-22: OEFFLINIENOGD/OEFFHALTESTOGD lieferten plötzlich weniger, u. a. ohne Station
    # Meidling, vermutlich wegen der Stammstrecken-Sperre): S-Strecken und Stationen der bisherigen Datei bleiben
    if path.exists():
        alt = json.loads(path.read_text(encoding="utf-8"))["features"]
        da = {json.dumps(f["geometry"]["coordinates"]) for f in feats if f["properties"]["typ"] == "sbahn"}
        st = {f["properties"]["name"]: f for f in feats if f["properties"]["typ"] == "station"}
        for f in alt:
            p = f["properties"]
            if p["typ"] == "sbahn" and json.dumps(f["geometry"]["coordinates"]) not in da:
                feats.insert(0, f)
            elif p["typ"] == "station":
                if p["name"] in st:
                    q = st[p["name"]]["properties"]
                    q["linien"] = sortiert(q["linien"].split(", ") + p["linien"].split(", "))
                else:
                    feats.append(f)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
                    encoding="utf-8")
    print("Linien:", ", ".join(l for _, l in relevant))
    print("Stationen:", ", ".join(sorted(stationen)))
    print("geschrieben:", path, path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
