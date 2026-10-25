"""Wohnungssuche Wien: scrapen, filtern, Karte bauen.

    python run.py scrape     neue Inserate holen (Suche + Detailseiten)
    python run.py build      bewerten, data/pending.json und docs/listings.json schreiben
    python run.py all        scrape + build
    python run.py pending    offene Prüfungen kompakt anzeigen
    python run.py review ID --heizung kein_gas --grund "..."      Prüfergebnis eintragen
    python run.py review ID --adresse "Karmeliterplatz 3" --sicherheit genau --grund "..."
    python run.py review-file datei.json                          viele Prüfergebnisse auf einmal
"""
import argparse
import datetime as dt
import hashlib
import shutil
import sys
import traceback

from wohnungen import geo, heizung, willhaben
from wohnungen.config import CONFIG, DATA, DOCS, ROOT, load_json, save_json
from wohnungen.geocode import geocode

LISTINGS = DATA / "listings.json"
REVIEWS = DATA / "reviews.json"
PENDING = DATA / "pending.json"
MAP_DATA = DOCS / "listings.json"
TODAY = dt.date.today().isoformat()
F = CONFIG["filter"]
ALLE_PLZ = CONFIG["bezirke"]["ganz"] + CONFIG["bezirke"]["mit_zonen"]


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- scrape

def filter_grund(r):
    """Harter Filter: Grund zum Ausschließen oder None."""
    if r.get("projekt") or "/neubauprojekt/" in r.get("url", ""):
        return "Neubauprojekt-Sammelinserat (Wohnungen sind einzeln gelistet)"
    if r.get("preis") and r["preis"] > F["preis_max"]:
        return f"Preis {r['preis']:,.0f} € über Limit".replace(",", ".")
    if r.get("flaeche") and r["flaeche"] < F["flaeche_min"]:
        return f"nur {r['flaeche']:g} m²"
    if r.get("zimmer") and r["zimmer"] < F["zimmer_min"]:
        return f"nur {r['zimmer']} Zimmer"
    return None


def lage_vorab_raus(r):
    if r.get("lat") and r.get("lage_genauigkeit") in ("adresse", "strasse"):
        drin, grund, _ = geo.pruefe(r["lat"], r["lon"])
        return None if drin else grund
    return None


def scrape():
    listings = load_json(LISTINGS, {})
    gesehen = set()
    fehler = []
    for plz in ALLE_PLZ:
        try:
            n = 0
            for s in willhaben.search(plz):
                n += 1
                gesehen.add(s["id"])
                r = listings.get(s["id"])
                if r is None:
                    r = listings[s["id"]] = {**s, "erstmals": TODAY}
                else:
                    if s.get("preis") and r.get("preis") and s["preis"] != r["preis"]:
                        r.setdefault("preis_historie", []).append([TODAY, r["preis"]])
                    for k, v in s.items():
                        if v is not None and k not in ("lat", "lon", "lage_genauigkeit", "adresse", "flaeche", "zimmer"):
                            r[k] = v
                r["zuletzt"] = TODAY
                r["aktiv"] = True
            log(f"willhaben {plz}: {n} Inserate")
        except Exception as e:  # eine kaputte Quelle soll den Rest nicht stoppen
            fehler.append(f"willhaben {plz}: {e}")
            traceback.print_exc()

    # Detailseiten nur für Kandidaten, die die Vorab-Filter bestehen
    todo = [r for r in listings.values()
            if r["id"] in gesehen and not r.get("detail_am")
            and not filter_grund(r) and not lage_vorab_raus(r)]
    log(f"Detailseiten zu laden: {len(todo)}")
    for i, r in enumerate(todo, 1):
        try:
            d = willhaben.detail(r["id"])
        except Exception as e:
            fehler.append(f"Detail {r['id']}: {e}")
            continue
        if d is None:
            r["aktiv"] = False
            continue
        for k, v in d.items():
            if v not in (None, "", []):
                r[k] = v
        if d.get("lat") and d.get("adresse"):
            r["lage_genauigkeit"] = r.get("lage_genauigkeit") if r.get("lage_genauigkeit") != "bezirk" else "strasse"
        r["detail_am"] = TODAY
        if i % 20 == 0:
            log(f"  {i}/{len(todo)}")
            save_json(LISTINGS, listings)

    # nicht mehr gesehene Inserate offline nehmen / alte löschen
    heute = dt.date.today()
    for k in list(listings):
        r = listings[k]
        alter = (heute - dt.date.fromisoformat(r.get("zuletzt", TODAY))).days
        if alter >= CONFIG["loeschen_nach_tagen"]:
            del listings[k]
        elif alter >= CONFIG["offline_nach_tagen"]:
            r["aktiv"] = False
    save_json(LISTINGS, listings)
    log(f"gespeichert: {len(listings)} Inserate, davon {len(gesehen)} heute gesehen")
    if fehler:
        log("FEHLER:\n  " + "\n  ".join(fehler[:30]))
    return fehler


# ---------------------------------------------------------------- bewerten

def _jitter(rid, lat, lon):
    """Ungefähre Lage (nur Bezirk bekannt): Punkt leicht streuen, damit sich Pins nicht stapeln."""
    h = hashlib.md5(rid.encode()).digest()
    return round(lat + (h[0] - 128) / 128 * 0.0035, 6), round(lon + (h[1] - 128) / 128 * 0.005, 6)


def bewerten(r, rev):
    """-> dict mit status (gruen/grau/raus), gruende, lage, heizung, fragen (offene Prüfungen)."""
    out = {"gruende": [], "fragen": [], "ungefaehr": False, "lat": r.get("lat"), "lon": r.get("lon")}
    eck = rev.get("eckdaten") or {}
    r = {**r, **{k: eck[k] for k in ("zimmer", "flaeche") if eck.get(k)}}
    grund = filter_grund(r)
    if grund:
        return {**out, "status": "raus", "art": "filter", "gruende": [grund]}
    grau = []
    if not r.get("zimmer"):
        grau.append("Zimmeranzahl nicht angegeben")
    if not r.get("flaeche"):
        grau.append("Wohnfläche nicht angegeben")
    if (not r.get("zimmer") or not r.get("flaeche")) and "eckdaten" not in rev:
        out["fragen"].append("eckdaten")

    # 1) Lage
    lrev = rev.get("lage")
    lage_txt = None
    if lrev and lrev.get("sicherheit") != "unklar":
        pos = (lrev.get("lat"), lrev.get("lon")) if lrev.get("lat") else (
            geocode(f"{lrev['adresse']}, {r['plz']} Wien") if lrev.get("adresse") else None)
        if pos and pos[0]:
            out["lat"], out["lon"] = pos
            drin, lage_txt, _ = geo.pruefe(*pos)
            lage_txt += f" (aus Beschreibung: {lrev.get('adresse') or 'Koordinaten'})"
            out["ungefaehr"] = lrev.get("sicherheit") != "genau"
            if not drin:
                return {**out, "status": "raus", "art": "lage", "gruende": [lage_txt], "lage": lage_txt}
        else:
            lrev = None
    if not lage_txt:
        if r.get("lat") and r.get("lage_genauigkeit") in ("adresse", "strasse"):
            drin, lage_txt, _ = geo.pruefe(r["lat"], r["lon"])
            if not drin:
                return {**out, "status": "raus", "art": "lage", "gruende": [lage_txt], "lage": lage_txt}
        elif r["plz"] in CONFIG["bezirke"]["ganz"]:
            lage_txt = f"{(r['plz'] - 1000) // 10}. Bezirk (genaue Adresse nicht angegeben)"
            out["ungefaehr"] = True
        else:
            lage_txt = f"Lage unklar, nur {(r['plz'] - 1000) // 10}. Bezirk bekannt"
            out["ungefaehr"] = True
            grau.append(lage_txt)
            if not (lrev or rev.get("lage")):
                out["fragen"].append("lage")
    out["lage"] = lage_txt
    if out["ungefaehr"] and out["lat"] and not (lrev and lrev.get("sicherheit") == "ungefaehr"):
        out["lat"], out["lon"] = _jitter(r["id"], out["lat"], out["lon"])

    # 2) Heizung
    hrev = rev.get("heizung")
    if hrev:
        h = {"ergebnis": hrev["ergebnis"], "text": hrev.get("begruendung", ""), "von": "Claude"}
    else:
        auto = heizung.einschaetzen(r.get("heizung_felder", []), r.get("text", "")) if r.get("detail_am") \
            else {"ergebnis": "unklar", "eindeutig": False, "belege": []}
        h = {"ergebnis": auto["ergebnis"], "von": "automatisch",
             "text": "; ".join(auto["belege"][:3]) or auto.get("hinweis") or "keine Angabe im Inserat"}
        if not auto["eindeutig"]:
            out["fragen"].append("heizung")
            h["text"] = "wird noch geprüft: " + h["text"]
        elif auto.get("hinweis"):
            h["text"] = auto["hinweis"]
    out["heizung"] = h
    if h["ergebnis"] == "gas":
        return {**out, "status": "raus", "art": "heizung", "gruende": ["Gasheizung: " + h["text"][:160]]}
    if h["ergebnis"] == "unklar":
        grau.append("Heizung unklar")
    out["gruende"] = grau
    out["status"] = "grau" if grau else "gruen"
    return out


def build():
    listings = load_json(LISTINGS, {})
    reviews = load_json(REVIEWS, {})
    heute = dt.date.today()
    karte, pending, details = [], [], {}
    erster_lauf = min((r["erstmals"] for r in listings.values()), default=TODAY)
    zaehler = {"gruen": 0, "grau": 0, "raus": 0}
    for r in listings.values():
        if not r.get("aktiv"):
            continue
        b = bewerten(r, reviews.get(r["id"], {}))
        eck = reviews.get(r["id"], {}).get("eckdaten") or {}
        zaehler[b["status"]] += 1
        if b["fragen"] and r.get("detail_am") and b["status"] != "raus":
            pending.append({
                "id": r["id"], "fragen": b["fragen"], "url": r["url"], "titel": r["titel"],
                "plz": r["plz"], "adresse_im_inserat": r.get("adresse"),
                "heizung_felder": r.get("heizung_felder", []),
                "heizung_vorab": b.get("heizung", {}).get("text"),
                "text": (r.get("text") or "")[:6000],
            })
        if b["status"] == "raus" and b.get("art") == "filter" or not b.get("lat"):
            continue
        # beim allerersten Lauf ist alles "neu" – das zählt nicht
        neu = r["erstmals"] > erster_lauf and (heute - dt.date.fromisoformat(r["erstmals"])).days < CONFIG["neu_tage"]
        karte.append({
            "id": r["id"], "quelle": r["quelle"], "url": r["url"], "titel": r["titel"],
            "status": b["status"], "gruende": b["gruende"], "lat": b["lat"], "lon": b["lon"],
            "ungefaehr": b["ungefaehr"], "preis": r.get("preis"), "flaeche": r.get("flaeche") or eck.get("flaeche"),
            "zimmer": r.get("zimmer") or eck.get("zimmer"), "plz": r["plz"], "adresse": r.get("adresse"),
            "lage": b.get("lage"), "heizung": b.get("heizung"), "bild": r.get("bild"),
            "erstmals": r["erstmals"], "neu": neu, "preis_historie": r.get("preis_historie"),
            "baujahr": r.get("baujahr"), "bauart": r.get("bauart"), "stockwerk": r.get("stockwerk"),
            "monatlich": r.get("monatlich"), "energie": r.get("energie"), "anbieter": r.get("anbieter"),
            "bilder": r.get("bilder") or ([r["bild"]] if r.get("bild") else []),
            "freiflaeche": r.get("freiflaeche") or [], "zustand": r.get("zustand"),
        })
        if r.get("text"):
            details[r["id"]] = {"text": r["text"], "heizung_felder": r.get("heizung_felder", [])}
    karte.sort(key=lambda x: (x["status"] != "gruen", x["erstmals"]), reverse=False)
    save_json(MAP_DATA, {"stand": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "anzahl": zaehler,
                         "wohnungen": karte}, indent=None)
    save_json(PENDING, pending)
    # Volltexte einzeln, damit die Karte schnell lädt und Details erst beim Öffnen holt
    ddir = DOCS / "d"
    ddir.mkdir(exist_ok=True)
    for p in ddir.glob("*.json"):
        if p.stem not in details:
            p.unlink()
    for rid, d in details.items():
        save_json(ddir / f"{rid}.json", d, indent=None)
    for name in ("bezirke.geojson", "zones.geojson", "oeffis.geojson"):
        (DOCS / "geo").mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "geo" / name, DOCS / "geo" / name)
    log(f"Karte: {zaehler['gruen']} passen, {zaehler['grau']} unklar, {zaehler['raus']} raus "
        f"| offene Prüfungen: {len(pending)}")


# ---------------------------------------------------------------- reviews

def add_review(rid, adresse=None, lat=None, lon=None, sicherheit=None, heiz=None, grund=""):
    reviews = load_json(REVIEWS, {})
    rv = reviews.setdefault(rid, {})
    if sicherheit or adresse or lat:
        rv["lage"] = {"adresse": adresse, "lat": lat, "lon": lon,
                      "sicherheit": sicherheit or "ungefaehr", "begruendung": grund}
    if heiz:
        rv["heizung"] = {"ergebnis": heiz, "begruendung": grund}
    rv["datum"] = TODAY
    save_json(REVIEWS, reviews)


def review_file(path):
    """JSON-Liste: [{"id":..., "lage": {"adresse":..., "sicherheit":..., "begruendung":...},
                      "heizung": {"ergebnis":..., "begruendung":...}}, ...]"""
    reviews = load_json(REVIEWS, {})
    items = load_json(__import__("pathlib").Path(path), [])
    for it in items:
        rv = reviews.setdefault(it["id"], {})
        for k in ("lage", "heizung", "eckdaten"):
            if k in it:
                rv[k] = it[k]
        rv["datum"] = TODAY
    save_json(REVIEWS, reviews)
    log(f"{len(items)} Prüfergebnisse übernommen")


def show_pending():
    for p in load_json(PENDING, []):
        print(f"\n=== {p['id']} | Fragen: {', '.join(p['fragen'])} | {p['plz']} | {p['titel']}\n{p['url']}")
        print("Heizungsfelder:", p["heizung_felder"], "| Vorab:", p["heizung_vorab"])
        print(p["text"][:1500])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scrape", "build", "all", "pending", "review", "review-file"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--adresse")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--sicherheit", choices=["genau", "ungefaehr", "unklar"])
    ap.add_argument("--heizung", choices=["gas", "kein_gas", "unklar"])
    ap.add_argument("--grund", default="")
    a = ap.parse_args()
    if a.cmd in ("scrape", "all"):
        scrape()
    if a.cmd in ("build", "all"):
        build()
    if a.cmd == "pending":
        show_pending()
    if a.cmd == "review":
        add_review(a.arg, a.adresse, a.lat, a.lon, a.sicherheit, a.heizung, a.grund)
    if a.cmd == "review-file":
        review_file(a.arg)


if __name__ == "__main__":
    main()
