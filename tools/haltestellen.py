"""Alle Öffi-Haltestellen Wiens mit ihren Linien -> geo/haltestellen.json (für "Öffis zu Fuß" in der Lage, Saad 2026-11-22).

Wiener Linien: GTFS (stops, trips, routes, stop_times), ein Eintrag je Steig mit allen Tageslinien (ohne Nachtbusse N…).
S-Bahn (ÖBB, nicht im GTFS der Wiener Linien): die S-Bahn-Stationen aus docs/geo/oeffis.geojson (tools/fetch_oeffis.py).
Format: [[Name, lat, lon, "U6 40 41"], ...]. Neu laufen lassen, wenn sich das Netz ändert (z. B. Fahrplanwechsel Dezember).
Aufruf: python tools/haltestellen.py
"""
import csv
import datetime as dt
import io
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://www.wienerlinien.at/ogd_realtime/doku/ogd/gtfs/gtfs.zip"
ZIEL = ROOT / "geo" / "haltestellen.json"


def lesen(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def sortkey(l):
    art = 0 if l.startswith("U") else 1 if l.startswith("S") else 3 if l[-1:].isalpha() and l[:-1].isdigit() else 2
    zahl = int("".join(c for c in l if c.isdigit()) or 0)
    return art, zahl, l


def main():
    pfad = Path(tempfile.gettempdir()) / "wl_gtfs.zip"
    if not pfad.exists() or pfad.stat().st_size < 1e7:
        print("lade GTFS …")
        urllib.request.urlretrieve(URL, pfad)
    z = zipfile.ZipFile(pfad)
    # ein normaler Werktag (nächster Dienstag): nur Fahrten, die an diesem Tag fahren. Über alle Kalender gezählt kamen
    # Umleitungen und Ein-/Ausrückfahrten dazu (37/38 in Gersthof, D und 1 in der Anastasius-Grün-Gasse)
    heute = dt.date.today()
    tag = heute + dt.timedelta(days=(1 - heute.weekday()) % 7 or 7)
    datum, wtag = tag.strftime("%Y%m%d"), ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][tag.weekday()]
    dienste = {r["service_id"] for r in lesen(z, "calendar.txt") if r["start_date"] <= datum <= r["end_date"] and r[wtag] == "1"}
    for r in lesen(z, "calendar_dates.txt"):
        if r["date"] == datum:
            (dienste.add if r["exception_type"] == "1" else dienste.discard)(r["service_id"])
    print("Werktag:", tag)
    linie = {r["route_id"]: r["route_short_name"].strip() for r in lesen(z, "routes.txt")}
    fahrt = {r["trip_id"]: linie.get(r["route_id"], "") for r in lesen(z, "trips.txt") if r["service_id"] in dienste}
    stops = {r["stop_id"]: (r["stop_name"].strip(), float(r["stop_lat"]), float(r["stop_lon"])) for r in lesen(z, "stops.txt")}
    an = {}
    print("lese stop_times …")
    for r in lesen(z, "stop_times.txt"):
        l = fahrt.get(r["trip_id"])
        if l and not l.startswith("N"):
            d = an.setdefault(r["stop_id"], {})
            d[l] = d.get(l, 0) + 1
    aus = []
    for sid, (name, lat, lon) in stops.items():
        if sid in an:
            # nur Linien mit regelmäßigem Halt (mind. 12 Fahrten an dem Tag), nicht einzelne Ein-/Ausrückfahrten
            ls = [l for l, n in an[sid].items() if n >= 12]
            if ls:
                aus.append([name.replace("Str.", "Straße"), round(lat, 6), round(lon, 6), " ".join(sorted(ls, key=sortkey))])
    # S-Bahn-Stationen (ÖBB): nur die S-Linien, die U-Linien kommen aus dem GTFS
    oeffis = json.loads((ROOT / "docs" / "geo" / "oeffis.geojson").read_text(encoding="utf-8"))
    for f in oeffis["features"]:
        p = f["properties"]
        if p.get("typ") == "station" and "S" in (p.get("linien") or ""):
            s = [x.strip() for x in p["linien"].split(",") if x.strip().startswith("S")]
            lon, lat = f["geometry"]["coordinates"][:2]
            aus.append([p["name"], round(lat, 6), round(lon, 6), " ".join(sorted(s, key=sortkey))])
    ZIEL.write_text(json.dumps(aus, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(len(aus), "Steige/Stationen ->", ZIEL)


if __name__ == "__main__":
    main()
