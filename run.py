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
import math
import re
import shutil
import sys
import threading
import time
import traceback

from wohnungen import geo, heizung, zustand
from wohnungen.quellen import QUELLEN
from wohnungen.config import CONFIG, DATA, DOCS, ROOT, load_json, save_json
from wohnungen.geocode import geocode

LISTINGS = DATA / "listings.json"
REVIEWS = DATA / "reviews.json"
PENDING = DATA / "pending.json"
# passende neue Wohnungen ohne genaue Adresse: die tägliche Routine recherchiert sie wie Nest-Wohnungen
RECHERCHE = DATA / "recherche.json"
GEPRUEFT = DATA / "nest_geprueft.json"
RECHERCHE_AB = "2026-10-28"
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


def _scrape_quelle(m, listings, gesehen, fehler, lock):
    """Ein Portal: Suche in allen Bezirken, dann Detailseiten der neuen Kandidaten."""
    name = m.QUELLE
    for plz in ALLE_PLZ:
        try:
            n = 0
            for s in m.search(plz):
                n += 1
                with lock:
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
            log(f"{name} {plz}: {n} Inserate")
        except Exception as e:  # eine kaputte Quelle soll den Rest nicht stoppen
            fehler.append(f"{name} {plz}: {e}")
            traceback.print_exc()
            # Ausfall heißt nicht "Inserate weg": bisherige Inserate dieses Portals im Bezirk behalten
            with lock:
                for r in listings.values():
                    if r["id"].startswith(m.PREFIX + "-") and r.get("plz") == plz and r.get("aktiv"):
                        r["zuletzt"] = TODAY

    # Detailseiten nur für Kandidaten, die die Vorab-Filter bestehen
    with lock:
        todo = [r for r in listings.values()
                if r["id"] in gesehen and m.PREFIX == r["id"].split("-")[0]
                # ältere willhaben-Detailseiten (vor 2026-10-27) einmal nachladen, um den Versatz zu kennen
                and (not r.get("detail_am") or (m.PREFIX == "wh" and "lage_radius" not in r))
                and not filter_grund(r) and not lage_vorab_raus(r)]
    log(f"{name}: {len(todo)} Detailseiten zu laden")
    for i, r in enumerate(todo, 1):
        try:
            d = m.detail(r["id"])
        except Exception as e:
            fehler.append(f"{name} Detail {r['id']}: {e}")
            continue
        with lock:
            if d is None:
                r["aktiv"] = False
                continue
            for k, v in d.items():
                if v not in (None, "", []):
                    r[k] = v
            if d.get("lat") and d.get("adresse") and r.get("lage_genauigkeit") in (None, "bezirk"):
                r["lage_genauigkeit"] = "strasse"
            r["detail_am"] = TODAY
            if i % 25 == 0:
                log(f"  {name}: {i}/{len(todo)}")
                save_json(LISTINGS, listings)


def scrape(nur=None):
    listings = load_json(LISTINGS, {})
    gesehen, fehler, lock = set(), [], threading.Lock()
    quellen = [m for p, m in QUELLEN.items() if not nur or p in nur]
    threads = [threading.Thread(target=_scrape_quelle, args=(m, listings, gesehen, fehler, lock))
               for m in quellen]
    log("Quellen: " + ", ".join(m.QUELLE for m in quellen))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if not gesehen:  # kein einziges Portal erreichbar (Netz/Proxy blockt): nichts verändern
        log("FEHLER: kein Portal erreichbar, nichts gespeichert:\n  " + "\n  ".join(fehler[:10]))
        sys.exit(2)

    # Portale, die in keinem Bezirk antworteten (kurzer Ausfall), nach einer Pause noch einmal
    ausfall = [m for m in quellen
               if all(any(f.startswith(f"{m.QUELLE} {plz}:") for f in fehler) for plz in ALLE_PLZ)]
    if ausfall:
        log("komplett ausgefallen, neuer Versuch in 3 Minuten: " + ", ".join(m.QUELLE for m in ausfall))
        time.sleep(180)
        for m in ausfall:
            neu = []
            _scrape_quelle(m, listings, gesehen, neu, lock)
            fehler[:] = [f for f in fehler if not f.startswith(m.QUELLE + " ")] + neu

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


def rot_vielleicht_draussen(lat, lon, radius):
    """Bei unsicherer Lage gilt die rote Zone (Ausschluss) nur, wenn der ganze Umkreis darin liegt –
    im Zweifel bleibt die Wohnung (Wunsch). Die blauen Zonen gelten dagegen streng."""
    (_, txt, _), anteil = geo.pruefe_umkreis(lat, lon, radius)
    return txt.startswith("rote Zone") and anteil > 0


def bewerten(r, rev):
    """-> dict mit status (gruen/grau/raus), gruende, lage, heizung, fragen (offene Prüfungen)."""
    out = {"gruende": [], "fragen": [], "ungefaehr": False, "lat": r.get("lat"), "lon": r.get("lon")}
    eck = rev.get("eckdaten") or {}
    r = {**r, **{k: eck[k] for k in ("zimmer", "flaeche") if eck.get(k)}}
    # ohne Preis ("auf Anfrage") nicht zeigen; erst hier, nicht in filter_grund, weil manche
    # Portale den Preis erst auf der Detailseite nennen
    grund = filter_grund(r) or (None if r.get("preis") else "kein Preis angegeben")
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
            out["landmarke"] = out["ungefaehr"]  # Lage aus Hinweis wie "Nähe Kutschkermarkt"
            if not drin and out["ungefaehr"] and rot_vielleicht_draussen(*pos, 200):
                grau.append(f"Lage unklar: ungefähr {lage_txt}, kann auch knapp außerhalb liegen")
            elif not drin:
                return {**out, "status": "raus", "art": "lage", "gruende": [lage_txt], "lage": lage_txt}
        else:
            lrev = None
    if not lage_txt:
        if r.get("lat") and r.get("lage_genauigkeit") in ("adresse", "strasse") and (r.get("lage_radius") or 0) > 50:
            # Punkt absichtlich versetzt: der Punkt selbst muss passen (die Zonen gelten streng);
            # schneidet der Umkreis eine Grenze, bleibt die Lage offen
            radius = r["lage_radius"]
            (drin, lage_txt, _), anteil = geo.pruefe_umkreis(r["lat"], r["lon"], radius)
            if not drin and not rot_vielleicht_draussen(r["lat"], r["lon"], radius):
                return {**out, "status": "raus", "art": "lage", "gruende": [lage_txt], "lage": lage_txt}
            lage_txt += f" (Kartenpunkt bis zu {radius} m versetzt)"
            out["ungefaehr"] = out["versetzt"] = out["landmarke"] = True
            if anteil < 1:
                grau.append(f"Lage unklar: Kartenpunkt bis zu {radius} m versetzt, Zonengrenze in der Nähe")
                if not rev.get("lage"):
                    out["fragen"].append("lage")
        elif r.get("lat") and r.get("lage_genauigkeit") in ("adresse", "strasse"):
            drin, lage_txt, _ = geo.pruefe(r["lat"], r["lon"])
            if not drin and r["lage_genauigkeit"] == "strasse" and rot_vielleicht_draussen(r["lat"], r["lon"], 200):
                # nur die Straße bekannt, und die reicht aus der roten Zone hinaus
                out["ungefaehr"] = True
                grau.append(f"Lage unklar: {lage_txt}, nur die Straße ist bekannt")
                if not rev.get("lage"):
                    out["fragen"].append("lage")
            elif not drin:
                return {**out, "status": "raus", "art": "lage", "gruende": [lage_txt], "lage": lage_txt}
        elif r["plz"] in CONFIG["bezirke"]["ganz"]:
            lage_txt = f"{(r['plz'] - 1000) // 10}. Bezirk (genaue Adresse nicht angegeben)"
            out["ungefaehr"] = True
            # Lage passt sowieso, aber für die Öffi-Zeit zum Gürtel (18./19.) braucht es die Adresse
            if r["plz"] in (1180, 1190) and not (lrev or rev.get("lage")):
                out["fragen"].append("lage")
        else:
            lage_txt = f"Lage unklar, nur {(r['plz'] - 1000) // 10}. Bezirk bekannt"
            out["ungefaehr"] = True
            grau.append(lage_txt)
            if not (lrev or rev.get("lage")):
                out["fragen"].append("lage")
    out["lage"] = lage_txt
    if out["ungefaehr"] and out["lat"] and not out.get("versetzt") and not (lrev and lrev.get("sicherheit") == "ungefaehr"):
        out["lat"], out["lon"] = _jitter(r["id"], out["lat"], out["lon"])

    # 2) Zustand und Nutzung: unbefristet vermietet / sanierungsbedürftig -> raus
    zrev = rev.get("zustand")
    if zrev:
        if zrev.get("ergebnis") == "raus":
            return {**out, "status": "raus", "art": "zustand", "gruende": [zrev.get("begruendung") or "Zustand/Vermietung"]}
        if zrev.get("ergebnis") == "hinweis" and zrev.get("begruendung"):
            out["hinweis"] = zrev["begruendung"]
    elif r.get("detail_am"):
        z = zustand.einschaetzen(r)
        if z["raus"]:
            return {**out, "status": "raus", "art": "zustand", "gruende": [g[:200] for g in z["gruende"]]}
        if not z["eindeutig"]:
            out["fragen"].append("zustand")
            grau.append("Zustand/Vermietung wird noch geprüft")
        if z["hinweise"]:
            out["hinweis"] = ", ".join(z["hinweise"])

    # 3) Heizung
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
    out["gruende"] = grau + ([out["hinweis"]] if out.get("hinweis") else [])
    out["status"] = "grau" if grau else "gruen"
    return out


# ---------------------------------------------------------------- Öffis zum Gürtel

_GUERTEL = None
GEHEN_M_PRO_MIN = 80 / 1.25  # wie in tools/oeffi_zeiten.py


def guertel_zeit(lat, lon):
    """Geschätzte Öffi-Zeit (Minuten) bis zur U6 am Gürtel: Fußweg zur besten Haltestelle +
    mittlere Fahrzeit ab dort (aus geo/guertel_zeiten.json). -> dict oder None."""
    global _GUERTEL
    if _GUERTEL is None:
        p = ROOT / "geo" / "guertel_zeiten.json"
        _GUERTEL = load_json(p, {"haltestellen": {}, "ziele": {}})
    beste = None
    for s in _GUERTEL["haltestellen"].values():
        d = math.hypot((s["lon"] - lon) * 74200, (s["lat"] - lat) * 111320)
        if d > 1200:
            continue
        gehen = d / GEHEN_M_PRO_MIN
        t = gehen + s["min"]
        if beste is None or t < beste["min"]:  # Haltestelle direkt an der U6 = zu Fuß zur U6
            beste = {"min": t, "ab": s["name"] if s["min"] else None, "gehen": gehen, "ziel": s.get("ziel")}
    for name, z in _GUERTEL["ziele"].items():  # direkt zu Fuß zur U6
        t = math.hypot((z["lon"] - lon) * 74200, (z["lat"] - lat) * 111320) / GEHEN_M_PRO_MIN
        if beste is None or t <= beste["min"]:
            beste = {"min": t, "ab": None, "gehen": t, "ziel": name}
    if beste:
        beste = {k: (round(v) if isinstance(v, float) else v) for k, v in beste.items()}
    return beste


# ---------------------------------------------------------------- Duplikate

GENAU = {"adresse": 3, "strasse": 2, "bezirk": 0, None: 0}


def _abstand_m(a, b):
    return math.hypot((a["lat"] - b["lat"]) * 111320, (a["lon"] - b["lon"]) * 74200)


def _woerter(s):
    return {w for w in re.findall(r"[a-zäöüß]{4,}", (s or "").lower())}


def ist_duplikat(a, b):
    """Dieselbe Wohnung auf zwei Portalen (oder doppelt auf einem)?"""
    if a["plz"] != b["plz"] or not (a.get("flaeche") and b.get("flaeche") and a.get("preis") and b.get("preis")):
        return False
    if a.get("zimmer") and b.get("zimmer") and a["zimmer"] != b["zimmer"]:
        return False
    df = abs(a["flaeche"] - b["flaeche"])
    dp = abs(a["preis"] - b["preis"]) / max(a["preis"], b["preis"])
    gleiche_quelle = a["id"][:2] == b["id"][:2]
    if gleiche_quelle:  # auf demselben Portal nur echte Doppel-Inserate, keine Nachbar-Tops
        if df > 0.01 or dp > 0:
            return False
    elif df > max(1.0, a["flaeche"] * 0.015) or dp > 0.015:
        return False
    genau = GENAU[a.get("lage_genauigkeit")] >= 2 and GENAU[b.get("lage_genauigkeit")] >= 2 and a.get("lat") and b.get("lat")
    if genau:
        return _abstand_m(a, b) <= 350
    # ohne genaue Lage: zusätzlich ähnlicher Titel, gleicher Makler oder fast identische Eckdaten
    wa, wb = _woerter(a.get("titel")), _woerter(b.get("titel"))
    titel = len(wa & wb) / max(1, len(wa | wb)) >= 0.25
    makler = a.get("anbieter") and b.get("anbieter") and \
        _woerter(a["anbieter"]) & _woerter(b["anbieter"]) - {"immobilien", "gmbh", "real", "estate"}
    return titel or bool(makler) or (df <= 0.5 and dp <= 0.005)


def _vertraeglich(g):
    """Darf diese Menge eine Wohnung sein? Verhindert Ketten (A≈B≈C, aber A≠C) in Neubauprojekten."""
    preise = [r["preis"] for r in g]
    flaechen = [r["flaeche"] for r in g]
    if max(preise) / min(preise) - 1 > 0.015 or max(flaechen) - min(flaechen) > 1.5:
        return False
    pro_quelle = {}
    for r in g:  # pro Portal nur eine Wohnung (exakte Doppel-Inserate zählen als eine)
        pro_quelle.setdefault(r["id"][:2], set()).add((r["preis"], round(r["flaeche"], 1)))
    return all(len(v) == 1 for v in pro_quelle.values())


def gruppieren(rs):
    """Ähnlichste Paare zuerst zusammenführen, solange die Gruppe als eine Wohnung plausibel bleibt
    -> Liste von Gruppen (Listen von Inseraten)."""
    paare = []
    nach_plz = {}
    for r in rs:
        nach_plz.setdefault(r["plz"], []).append(r)
    for liste in nach_plz.values():
        liste.sort(key=lambda r: r.get("flaeche") or 0)
        for i, a in enumerate(liste):
            for b in liste[i + 1:]:
                if (b.get("flaeche") or 0) - (a.get("flaeche") or 0) > 3:
                    break
                if ist_duplikat(a, b):
                    dp = abs(a["preis"] - b["preis"]) / max(a["preis"], b["preis"])
                    paare.append((dp + abs(a["flaeche"] - b["flaeche"]) / 100, a["id"], b["id"]))
    paare.sort()
    gruppe_von = {r["id"]: [r] for r in rs}
    for _, a, b in paare:
        ga, gb = gruppe_von[a], gruppe_von[b]
        if ga is gb or not _vertraeglich(ga + gb):
            continue
        ga.extend(gb)
        for r in gb:
            gruppe_von[r["id"]] = ga
    return list({id(g): g for g in gruppe_von.values()}.values())


def _strassen_geocode(m):
    """Nur Straße bekannt (andere Portale geben oft keine Koordinaten) -> Koordinaten suchen,
    aber nur übernehmen, wenn das Ergebnis im angegebenen Bezirk liegt."""
    adr = m.get("adresse")
    if not adr or not re.search(r"[A-Za-zäöüß]{4}", adr) or re.search(r"(?i)bezirk|^wien", adr):
        return
    # Portale schreiben teils "Rudolfsplatz, Schwedenplatz, Donaukanal": erst alles, dann der erste Teil
    for versuch in dict.fromkeys([adr, re.split(r"[,/;]| - ", adr)[0].strip()]):
        if len(versuch) < 4:
            continue
        pos = geocode(f"{versuch}, {m['plz']} Wien")
        if pos and geo.bezirk_von(*pos) == (m["plz"] - 1000) // 10:
            m["lat"], m["lon"] = pos
            m["lage_genauigkeit"] = "adresse" if re.search(r"\d", versuch) else "strasse"
            return
    m["lat"] = m["lon"] = None
    m["lage_genauigkeit"] = "bezirk"


STRASSE_NR = re.compile(
    r"\b([A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)*(?:straße|strasse|gasse|platz|weg|allee|zeile|steig|kai|ring"
    r"|lände|promenade|markt|hof|berg|gürtel))\s+(\d{1,3}[a-zA-Z]?)\b")


def _adresse_aus_text(m):
    """Straße + Hausnummer aus Titel/Text (häufigste Nennung), nur wenn sie im richtigen Bezirk liegt."""
    text = f"{m.get('titel') or ''}\n{m.get('text') or ''}"
    treffer = {}
    for s, nr in STRASSE_NR.findall(text):
        k = f"{s.replace('strasse', 'straße')} {nr}"
        treffer[k] = treffer.get(k, 0) + 1
    for adr, _ in sorted(treffer.items(), key=lambda x: -x[1])[:3]:
        pos = geocode(f"{adr}, {m['plz']} Wien")
        if pos and geo.bezirk_von(*pos) == (m["plz"] - 1000) // 10:
            return adr, pos
    return None


def zusammenfuehren(gruppe, reviews):
    """Eine Gruppe -> ein Datensatz mit der besten Info aller Portale + zusammengeführte Prüfungen."""
    def rang(r):
        return (GENAU[r.get("lage_genauigkeit")], bool(r.get("detail_am")), len(r.get("text") or ""))
    gruppe = sorted(gruppe, key=lambda r: (rang(r), r["id"] == min(x["id"] for x in gruppe)), reverse=True)
    kopf = gruppe[0]
    m = dict(kopf)
    for r in gruppe[1:]:
        for k, v in r.items():
            if m.get(k) in (None, "", [], {}) and v not in (None, "", [], {}):
                m[k] = v
    # Lage: genaueste Angabe mit Koordinaten; sonst eine Straßenangabe nachschlagen
    beste = max(gruppe, key=lambda r: (bool(r.get("lat")) and GENAU[r.get("lage_genauigkeit")], bool(r.get("lat"))))
    for k in ("lat", "lon", "lage_genauigkeit", "adresse"):
        m[k] = beste.get(k)
    # Versatz gilt auch, wenn ein anderes Portal denselben (vom Makler übernommenen) Punkt zeigt
    m["lage_radius"] = max([r.get("lage_radius") or 0 for r in gruppe if r.get("lat") and m.get("lat")
                            and _abstand_m(r, m) < 30] or [0])
    if not m.get("lat") or GENAU[m.get("lage_genauigkeit")] < 2:
        kandidat = max(gruppe, key=lambda r: GENAU[r.get("lage_genauigkeit")] if r.get("adresse") else -1)
        if kandidat.get("adresse") and GENAU[kandidat.get("lage_genauigkeit")] >= GENAU[m.get("lage_genauigkeit")]:
            alt = {k: m.get(k) for k in ("lat", "lon", "lage_genauigkeit", "adresse", "lage_radius")}
            m["adresse"], m["lage_radius"] = kandidat["adresse"], 0
            _strassen_geocode(m)
            if not m.get("lat"):  # nichts gefunden: ungefähre Lage von vorher behalten
                m.update({k: v for k, v in alt.items() if k != "adresse"})
        elif not m.get("adresse"):
            m["adresse"] = next((r["adresse"] for r in gruppe if r.get("adresse")), None)
    if m.get("punkt_verdaechtig") and (gefunden := _adresse_aus_text(m)) and \
            _abstand_m(m, {"lat": gefunden[1][0], "lon": gefunden[1][1]}) > 120:
        # geteilter Standardpunkt, aber der Text nennt eine andere Adresse (z. B. "Staudgasse 40")
        m["adresse"], (m["lat"], m["lon"]) = gefunden[0], gefunden[1]
        m["lage_genauigkeit"], m["lage_radius"] = "adresse", 0
    elif (GENAU[m.get("lage_genauigkeit")] < 3 or (m.get("lage_radius") or 0) > 50) \
            and (gefunden := _adresse_aus_text(m)) and not ((m.get("lage_radius") or 0) > 50 and _abstand_m(
                m, {"lat": gefunden[1][0], "lon": gefunden[1][1]}) > m["lage_radius"] + 150):
        # Adresse steht nur in der Beschreibung (z. B. "Projekt M86, Martinstraße 86"); bei versetztem
        # Punkt nur, wenn sie im Umkreis liegt (sonst ist es eher eine Ortsangabe wie eine Station)
        m["adresse"], (m["lat"], m["lon"]) = gefunden[0], gefunden[1]
        m["lage_genauigkeit"], m["lage_radius"] = "adresse", 0
    if not m.get("lat"):  # gar keine Koordinaten (z. B. derStandard ohne Straße): Bezirksmitte
        m["lat"], m["lon"] = geo.bezirksmitte((m["plz"] - 1000) // 10) or (None, None)
        m["lage_genauigkeit"] = "bezirk"
    if len(gruppe) > 1:
        m["heizung_felder"] = list(dict.fromkeys(
            f"{f} ({r['quelle']})" for r in gruppe for f in r.get("heizung_felder", [])))
        m["text"] = "\n\n".join(f"## ===== {r['quelle']} =====\n{r['text']}" for r in gruppe if r.get("text"))
        m["bilder"] = list(dict.fromkeys(b for r in gruppe for b in (r.get("bilder") or [])))[:40]
        m["freiflaeche"] = list(dict.fromkeys(f for r in gruppe for f in (r.get("freiflaeche") or [])))
        m["detail_am"] = next((r["detail_am"] for r in gruppe if r.get("detail_am")), None)
    m["erstmals"] = min(r["erstmals"] for r in gruppe)
    m["links"] = sorted(({"quelle": r["quelle"], "url": r["url"], "preis": r.get("preis"), "id": r["id"]}
                         for r in gruppe), key=lambda l: (l["quelle"] != "willhaben", l["quelle"]))
    m["ids"] = [r["id"] for r in gruppe]
    # Prüfungen: Kopf zuerst; Gas von irgendeinem Portal schlägt alles; genaue Lage vor ungefährer
    revs = [reviews[r["id"]] for r in gruppe if r["id"] in reviews]
    rev = {}
    if revs:
        h = [x["heizung"] for x in revs if x.get("heizung")]
        if h:
            rev["heizung"] = next((x for x in h if x["ergebnis"] == "gas"), None) or \
                next((x for x in h if x["ergebnis"] == "kein_gas"), h[0])
        lg = [x["lage"] for x in revs if x.get("lage")]
        if lg:
            rev["lage"] = next((x for x in lg if x.get("sicherheit") == "genau"), None) or \
                next((x for x in lg if x.get("sicherheit") == "ungefaehr"), lg[0])
        e = [x["eckdaten"] for x in revs if "eckdaten" in x]
        if e:
            rev["eckdaten"] = next((x for x in e if x), e[0])
        z = [x["zustand"] for x in revs if x.get("zustand")]
        if z:
            rev["zustand"] = next((x for x in z if x.get("ergebnis") == "raus"), z[0])
    return m, rev


def lage_genau(r, rev, b):
    """Adresse mit Hausnummer bekannt (geprüft oder aus dem Inserat, Punkt nicht versetzt)?"""
    if (rev.get("lage") or {}).get("sicherheit") == "genau":
        return True
    return (not b["ungefaehr"] and r.get("lage_genauigkeit") == "adresse"
            and bool(re.search(r"\d", r.get("adresse") or "")))


def build():
    listings = load_json(LISTINGS, {})
    reviews = load_json(REVIEWS, {})
    geprueft = load_json(GEPRUEFT, {})
    erledigt = {i for e in geprueft.values() for i in e.get("ids", [])} | set(geprueft)
    korb = set((load_json(DATA / "markierungen.json", {}).get("papierkorb") or {}))
    recherche = []
    heute = dt.date.today()
    karte, pending, details = [], [], {}
    erster_lauf = min((r["erstmals"] for r in listings.values()), default=TODAY)
    zaehler = {"gruen": 0, "grau": 0, "raus": 0}
    aktiv = [r for r in listings.values() if r.get("aktiv")]
    # Makler setzen manchmal denselben Standardpunkt für viele Inserate. Teilen sich 3+ verschiedene
    # Inserate exakt dieselben Koordinaten, ist der Punkt verdächtig (zusammenfuehren prüft dann den Text)
    titel_pro_punkt = {}
    for r in aktiv:
        if r.get("lat") and GENAU[r.get("lage_genauigkeit")] >= 2:
            titel_pro_punkt.setdefault((r["lat"], r["lon"]), set()).add((r.get("titel") or "")[:25].lower())
    verdaechtig = {p for p, t in titel_pro_punkt.items() if len(t) >= 3}
    aktiv = [{**r, "punkt_verdaechtig": True} if (r.get("lat"), r.get("lon")) in verdaechtig else r for r in aktiv]
    gruppen = gruppieren([r for r in aktiv if not (r.get("projekt") or "/neubauprojekt/" in r.get("url", ""))])
    # von Hand erkannte Doppelte (z. B. gleicher Grundriss, verschiedene Makler): reviews "gleich_wie"
    for a, rv in reviews.items():
        b = rv.get("gleich_wie")
        ga = next((g for g in gruppen if any(r["id"] == a for r in g)), None)
        gb = next((g for g in gruppen if any(r["id"] == b for r in g)), None)
        if ga is not None and gb is not None and ga is not gb:
            ga.extend(gb)
            gruppen.remove(gb)
    gruppen += [[r] for r in aktiv if r.get("projekt") or "/neubauprojekt/" in r.get("url", "")]
    doppelt = sum(len(g) - 1 for g in gruppen)
    for gruppe in gruppen:
        r, rev = zusammenfuehren(gruppe, reviews)
        b = bewerten(r, rev)
        eck = rev.get("eckdaten") or {}
        zaehler[b["status"]] += 1
        if (b["status"] == "gruen" and r["erstmals"] >= RECHERCHE_AB and not lage_genau(r, rev, b)
                and not set(r["ids"]) & (erledigt | korb)):
            recherche.append({
                "id": r["id"], "ids": r["ids"], "titel": r["titel"], "plz": r["plz"],
                "links": [l["url"] for l in r["links"]], "anbieter": r.get("anbieter"),
                "adresse_im_inserat": r.get("adresse"), "lage": b.get("lage"),
                "punkt": [b["lat"], b["lon"]], "versatz_m": r.get("lage_radius") or 0,
                "preis": r.get("preis"), "flaeche": r.get("flaeche"), "zimmer": r.get("zimmer"),
                "stockwerk": r.get("stockwerk"), "energie": r.get("energie"),
                "grundrisse": f"data/grundrisse/{r['id']}/",
            })
        if b["fragen"] and r.get("detail_am") and b["status"] != "raus":
            pending.append({
                "id": r["id"], "fragen": b["fragen"], "url": r["url"], "titel": r["titel"],
                "plz": r["plz"], "adresse_im_inserat": r.get("adresse"),
                "heizung_felder": r.get("heizung_felder", []),
                "heizung_vorab": b.get("heizung", {}).get("text"),
                "text": (r.get("text") or "")[:9000],
            })
        if b["status"] == "raus" and b.get("art") == "filter" or not b.get("lat"):
            continue
        # beim allerersten Lauf ist alles "neu" – das zählt nicht
        neu = r["erstmals"] > erster_lauf and (heute - dt.date.fromisoformat(r["erstmals"])).days < CONFIG["neu_tage"]
        karte.append({
            "id": r["id"], "ids": r["ids"], "links": r["links"], "quelle": r["quelle"], "url": r["url"],
            "titel": r["titel"], "status": b["status"], "gruende": b["gruende"], "lat": b["lat"], "lon": b["lon"],
            "ungefaehr": b["ungefaehr"], "preis": r.get("preis"), "flaeche": r.get("flaeche") or eck.get("flaeche"),
            "zimmer": r.get("zimmer") or eck.get("zimmer"), "plz": r["plz"], "adresse": r.get("adresse"),
            "lage": b.get("lage"), "heizung": b.get("heizung"), "bild": r.get("bild"),
            "erstmals": r["erstmals"], "neu": neu, "preis_historie": r.get("preis_historie"),
            "baujahr": r.get("baujahr"), "bauart": r.get("bauart"), "stockwerk": r.get("stockwerk"),
            "monatlich": r.get("monatlich"), "energie": r.get("energie"), "anbieter": r.get("anbieter"),
            "bilder": r.get("bilder") or ([r["bild"]] if r.get("bild") else []),
            "freiflaeche": r.get("freiflaeche") or [], "zustand": r.get("zustand"),
            # nur 18./19. Bezirk und nur bei bekannter Lage (bei ungefährer Lage wäre die Zeit geraten)
            "guertel": ({**g, "ungefaehr": bool(b.get("landmarke"))}
                        if r["plz"] in (1180, 1190) and (not b["ungefaehr"] or b.get("landmarke"))
                        and (g := guertel_zeit(b["lat"], b["lon"])) else None),
        })
        if r.get("text"):
            details[r["id"]] = {"text": r["text"], "heizung_felder": r.get("heizung_felder", [])}
    karte.sort(key=lambda x: (x["status"] != "gruen", x["erstmals"]), reverse=False)
    quellen = sorted({l["quelle"] for w in karte for l in w["links"]}, key=lambda q: (q != "willhaben", q))
    save_json(MAP_DATA, {"stand": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "anzahl": zaehler,
                         "quellen": quellen, "wohnungen": karte}, indent=None)
    save_json(PENDING, pending)
    save_json(RECHERCHE, recherche)
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
        f"| {doppelt} Duplikate zusammengeführt | offene Prüfungen: {len(pending)} | Adress-Recherchen: {len(recherche)}")


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
        for k in ("lage", "heizung", "eckdaten", "zustand", "gleich_wie"):
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
    ap.add_argument("--quellen", help="nur diese Portale, z. B. wh,ds,is")
    a = ap.parse_args()
    if a.cmd in ("scrape", "all"):
        scrape(a.quellen.split(",") if a.quellen else None)
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
