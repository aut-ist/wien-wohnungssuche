"""Öffi-Fahrzeit von jeder Haltestelle im 18./19. Bezirk bis zur U6 am Gürtel -> geo/guertel_zeiten.json

Grundlage: Fahrplan der Wiener Linien (GTFS, data.gv.at), ein normaler Werktagmorgen.
Rückwärts-Verbindungssuche (Connection Scan) für viele Ankunftszeiten; daraus die mittlere
Reisezeit bei Abfahrt zu einer zufälligen Minute zwischen 7 und 8 Uhr, also inklusive Wartezeit
und Umsteigen (2 min Umsteigezeit, Fußwege zwischen Haltestellen bis 300 m).

    python tools/oeffi_zeiten.py [JJJJMMTT]      (Standard: nächster Dienstag)

Dauert ein paar Minuten (lädt ~100 MB). Nur nötig, wenn sich Fahrpläne ändern.
"""
import csv
import datetime as dt
import io
import json
import math
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://www.wienerlinien.at/ogd_realtime/doku/ogd/gtfs/gtfs.zip"
BOX = (16.240, 48.192, 16.385, 48.285)  # 18./19. Bezirk plus Gürtel bis Westbahnhof
ZIELE = ["Westbahnhof", "Burggasse-Stadthalle", "Thaliastraße", "Josefstädter Straße", "Alser Straße",
         "Michelbeuern-AKH", "Währinger Straße-Volksoper", "Nußdorfer Straße", "Spittelau"]  # U6 am Gürtel
ZIEL_RADIUS_M = 150      # Straßenbahn-Haltestellen direkt an der U6-Station zählen als "am Gürtel"
FUSSWEG_M = 300          # Umsteigen zu Fuß zwischen Haltestellen
GEHEN_M_PRO_MIN = 80 / 1.25   # 80 m/min, Umwegfaktor 1,25 gegenüber Luftlinie
UMSTEIGEN_S = 120
START, ENDE = 7 * 3600, 8 * 3600   # Abfahrtsfenster
SCHRITT = 60


def m(a, b):
    return math.hypot((a[0] - b[0]) * 74200, (a[1] - b[1]) * 111320)


def sek(t):
    h, mi, s = t.split(":")
    return int(h) * 3600 + int(mi) * 60 + int(s)


def lesen(z, name):
    return csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"))


def main():
    if len(sys.argv) > 1:
        tag = dt.datetime.strptime(sys.argv[1], "%Y%m%d").date()
    else:
        heute = dt.date.today()
        tag = heute + dt.timedelta(days=(1 - heute.weekday()) % 7 or 7)
    wochentag = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][tag.weekday()]
    datum = tag.strftime("%Y%m%d")
    print("Fahrplantag:", tag)

    pfad = Path(tempfile.gettempdir()) / "wl_gtfs.zip"
    if not pfad.exists() or pfad.stat().st_size < 1e7:
        print("lade GTFS …")
        urllib.request.urlretrieve(URL, pfad)
    z = zipfile.ZipFile(pfad)

    dienste = {r["service_id"] for r in lesen(z, "calendar.txt")
               if r["start_date"] <= datum <= r["end_date"] and r[wochentag] == "1"}
    for r in lesen(z, "calendar_dates.txt"):
        if r["date"] == datum:
            (dienste.add if r["exception_type"] == "1" else dienste.discard)(r["service_id"])
    fahrten = {r["trip_id"] for r in lesen(z, "trips.txt") if r["service_id"] in dienste}

    stops = {}
    for r in lesen(z, "stops.txt"):
        lon, lat = float(r["stop_lon"]), float(r["stop_lat"])
        if BOX[0] <= lon <= BOX[2] and BOX[1] <= lat <= BOX[3]:
            stops[r["stop_id"]] = {"name": r["stop_name"], "lon": lon, "lat": lat}
    u6 = [s for s in stops.values() if s["name"] in ZIELE]
    ziele = {sid: next(z_["name"] for z_ in u6 if m((s["lon"], s["lat"]), (z_["lon"], z_["lat"])) <= ZIEL_RADIUS_M)
             for sid, s in stops.items()
             if any(m((s["lon"], s["lat"]), (z_["lon"], z_["lat"])) <= ZIEL_RADIUS_M for z_ in u6)}
    print(len(stops), "Haltestellen im Gebiet,", len(ziele), "davon am Gürtel")

    # Verbindungen (zwei aufeinanderfolgende Halte einer Fahrt) im Gebiet und Zeitfenster
    verb, vorher = [], None
    print("lese stop_times …")
    for r in lesen(z, "stop_times.txt"):
        t = r["trip_id"]
        if t not in fahrten or r["stop_id"] not in stops:
            vorher = None  # Fahrt verlässt das Gebiet: keine Verbindung über die Lücke hinweg
            continue
        akt = (t, r["stop_id"], sek(r["arrival_time"]), sek(r["departure_time"]))
        if vorher and vorher[0] == t and START - 600 <= vorher[3] <= ENDE + 3600:
            verb.append((vorher[3], akt[2], vorher[1], akt[1], t))
        vorher = akt
    verb.sort(key=lambda c: -c[0])
    print(len(verb), "Verbindungen")

    nachbarn = {s: [(o, m((a["lon"], a["lat"]), (b["lon"], b["lat"])) / GEHEN_M_PRO_MIN * 60)
                    for o, b in stops.items() if o != s and m((a["lon"], a["lat"]), (b["lon"], b["lat"])) <= FUSSWEG_M]
                for s, a in stops.items()}

    # Für jede Ankunftszeit T am Gürtel: späteste Abfahrt LD[s], um T noch zu schaffen
    deadlines = list(range(START + 120, ENDE + 3600, SCHRITT * 2))
    ld_alle = []
    for T in deadlines:
        ld = {s: T for s in ziele}
        for s in list(ziele):
            for o, w in nachbarn[s]:
                ld[o] = max(ld.get(o, -1), T - w)
        auf_fahrt = set()
        for dep, arr, u, v, trip in verb:
            if arr > T:
                continue
            frist = ld.get(v, -1) - (0 if v in ziele else UMSTEIGEN_S)
            if trip in auf_fahrt or arr <= frist:
                auf_fahrt.add(trip)
                if dep > ld.get(u, -1):
                    ld[u] = dep
                    for o, w in nachbarn[u]:
                        if dep - w > ld.get(o, -1):
                            ld[o] = dep - w
        ld_alle.append(ld)

    # mittlere Reisezeit bei Abfahrt zu jeder Minute zwischen START und ENDE
    out = {}
    for s, info in stops.items():
        if s in ziele:
            out[s] = {**info, "min": 0, "ziel": ziele[s]}
            continue
        zeiten = []
        for t in range(START, ENDE, SCHRITT):
            ankunft = next((T for T, ld in zip(deadlines, ld_alle) if ld.get(s, -1) >= t), None)
            if ankunft is None:
                break
            zeiten.append(ankunft - t)
        if len(zeiten) == (ENDE - START) // SCHRITT:
            out[s] = {**info, "min": round(sum(zeiten) / len(zeiten) / 60, 1)}
    ziel_out = {n: next({"lon": s["lon"], "lat": s["lat"]} for s in u6 if s["name"] == n) for n in ZIELE
                if any(s["name"] == n for s in u6)}
    path = ROOT / "geo" / "guertel_zeiten.json"
    path.write_text(json.dumps({"fahrplantag": str(tag), "ziele": ziel_out, "haltestellen": out},
                               ensure_ascii=False), encoding="utf-8")
    print("geschrieben:", path, len(out), "Haltestellen mit Zeit")


if __name__ == "__main__":
    main()
