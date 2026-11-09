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
from wohnungen.geocode import geocode, strassenblick
from wohnungen.http import get

LISTINGS = DATA / "listings.json"
REVIEWS = DATA / "reviews.json"
PENDING = DATA / "pending.json"
# Wohnungen auf der Karte (grün oder grau, nicht im Papierkorb) ohne genaue Adresse – auch ältere,
# die z. B. nach einer Regeländerung wieder auftauchen: die Routine recherchiert sie wie Nest-Wohnungen
RECHERCHE = DATA / "recherche.json"
GEPRUEFT = DATA / "nest_geprueft.json"
RECHERCHE_PRO_TAG = 25  # mehr schafft die Morgen-Routine nicht sinnvoll; Grundrisse nur für diese
# Preisverlauf der Nest-Wohnungen, bleibt auch, wenn das Inserat verschwindet (Verhandlungsspielraum)
PREISARCHIV = DATA / "preisverlauf.json"
SICHTBAR = DATA / "sichtbar_seit.json"
# Papierkorb-Eintrag -> {"zeit": Zeitstempel, "offline": war die Wohnung beim Rauswerfen ausgegraut,
# "wieder_da": erster Tag wieder online}. Ausgegraut Rausgeworfenes kommt beim Neu-Inserieren als neu
# zurück, online Rausgeworfenes bleibt weg (Wunsch 2026-10-30).
KORB_STATUS = DATA / "papierkorb_status.json"
MAP_DATA = DOCS / "listings.json"
TODAY = dt.date.today().isoformat()
F = CONFIG["filter"]
ALLE_PLZ = CONFIG["bezirke"]["ganz"] + CONFIG["bezirke"]["mit_zonen"]


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- scrape

def flaeche_min(r, bestand=False):
    """Seit 2026-10-30 ab 75 m²; Wohnungen, die vorher schon gefunden wurden, bleiben ab 70 m² (Wunsch).
    Die Gruppe trägt das früheste "erstmals" aller Portale, ein Neu-Inserat das der alten Nummer."""
    if bestand or (r.get("erstmals") or TODAY) < F["flaeche_min_ab"]:
        return F["flaeche_min_bestand"]
    return F["flaeche_min"]


def _sammelinserat(r):
    """Projekt-Sammelinserat eines Portals; Bauträger-Einheiten (bt-) sind immer einzelne Wohnungen."""
    return r.get("projekt") or (not r["id"].startswith("bt-") and "/neubauprojekt/" in r.get("url", ""))


def filter_grund(r, bestand=False):
    """Harter Filter: Grund zum Ausschließen oder None. bestand=True: alte Flächengrenze, für den
    Scrape, der noch nicht weiß, ob ein neues Inserat zu einer bekannten Wohnung gehört."""
    if _sammelinserat(r):
        return "Neubauprojekt-Sammelinserat (Wohnungen sind einzeln gelistet)"
    if r.get("plz") and r["plz"] not in ALLE_PLZ:  # z. B. Klosterneuburg (3400) in der derStandard-Suche 1190
        return f"PLZ {r['plz']} außerhalb des Suchgebiets"
    if r.get("preis") and r["preis"] > F["preis_max"]:
        return f"Preis {r['preis']:,.0f} € über Limit".replace(",", ".")
    if r.get("flaeche") and r["flaeche"] < flaeche_min(r, bestand):
        return f"nur {r['flaeche']:g} m²"
    if r.get("zimmer") and r["zimmer"] < F["zimmer_min"]:
        return f"nur {r['zimmer']} Zimmer"
    if r.get("zimmer") == 3 and r.get("preis") and r["preis"] > F["preis_max_3_zimmer"]:  # nur genau 3 Zimmer
        return f"3 Zimmer über {F['preis_max_3_zimmer']:,.0f} €".replace(",", ".")
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
                                # die Suche liefert oft nur 1-4 Vorschaubilder; die Fotos der Detailseite nicht
                                # damit überschreiben (bis 2026-11-06 hatten ImmoScout24, FindMyHome, s REAL und
                                # Raiffeisen deshalb fast nur ein Bild)
                                if k == "bilder" and len(r.get("bilder") or []) > len(v or []):
                                    continue
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
                and not filter_grund(r, bestand=True) and not lage_vorab_raus(r)]
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


def neu_inseriert(listings, gesehen):
    """Makler stellen Wohnungen gern mit neuer Nummer neu ein, oft billiger. Ist heute ein Inserat
    verschwunden und ein neues desselben Maklers auf demselben Portal da (gleiche Fläche, Zimmer,
    Stock, Energieausweis), ist es dieselbe Wohnung: Verlauf übernehmen, Preisänderung merken.
    Auch wenn das alte Inserat schon länger weg ist (bis es gelöscht wird, im Papierkorb ein Jahr)."""
    # alle verschwundenen Inserate, nicht nur die der letzten Tage (auch Wochen später neu inseriert ist
    # dieselbe Wohnung: online Rausgeworfenes soll dann weg bleiben); das zuletzt gesehene zuerst
    weg = sorted((r for r in listings.values() if r["id"] not in gesehen and not r.get("nachfolger")
                  and r.get("zuletzt") != TODAY), key=lambda r: r.get("zuletzt") or "", reverse=True)
    for n in [r for r in listings.values() if r["id"] in gesehen and r.get("erstmals") == TODAY]:
        hwb = (n.get("energie") or {}).get("hwb")
        for a in weg:
            if (a["id"][:2] == n["id"][:2] and a.get("plz") == n.get("plz") and a.get("anbieter")
                    and a.get("anbieter") == n.get("anbieter") and hwb and (a.get("energie") or {}).get("hwb") == hwb
                    and a.get("flaeche") and n.get("flaeche") and abs(a["flaeche"] - n["flaeche"]) <= 0.5
                    and a.get("zimmer") == n.get("zimmer") and str(a.get("stockwerk")) == str(n.get("stockwerk"))):
                n["erstmals"] = min(a["erstmals"], n["erstmals"])
                n["preis_historie"] = (a.get("preis_historie") or []) + (
                    [[TODAY, a["preis"]]] if a.get("preis") and a["preis"] != n.get("preis") else []) + (n.get("preis_historie") or [])
                n["vorgaenger"] = (a.get("vorgaenger") or []) + [a["id"]]
                a["aktiv"], a["nachfolger"] = False, n["id"]
                weg.remove(a)
                log(f"neu inseriert: {a['id']} -> {n['id']} ({a.get('preis')} -> {n.get('preis')})")
                break


def online_pruefen(listings, gesehen):
    """Nest-Wohnungen jeden Tag einzeln aufrufen: zeigt die Suche sie nicht mehr (z. B. Preis über
    dem Filter), zählt nur, ob das Inserat selbst noch da ist. Weg -> aktiv False, weg_am."""
    nest = set(load_json(DATA / "markierungen.json", {}).get("gemerkt") or {})
    nest |= {i for e in load_json(PREISARCHIV, {}).values() if set(e["ids"]) & nest for i in e["ids"]}
    module = {m.PREFIX: m for m in QUELLEN.values()}
    for i in sorted(nest - gesehen):
        r = listings.get(i)
        if not r or r.get("nachfolger") or r.get("weg_am"):
            continue
        try:
            if i.startswith("is-"):  # die Detailsuche kennt ImmoScout-Nummern nur nach search()
                seite = get(r["url"])
                da = bool(seite) and "Immobilie nicht gefunden" not in seite
            else:
                da = module[i.split("-")[0]].detail(i) is not None
        except Exception as e:  # gesperrt o. Ä.: heute nichts entscheiden
            log(f"Nest-Prüfung {i}: {e}")
            continue
        if da:
            r["zuletzt"], r["aktiv"] = TODAY, True
        else:
            r["aktiv"], r["weg_am"] = False, TODAY
            log(f"Nest-Wohnung nicht mehr online: {i}")


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
    # (nicht, wenn der Host für heute gesperrt ist: derStandard blockt GitHub, die Pause bringt nichts)
    ausfall = [m for m in quellen
               if all(any(f.startswith(f"{m.QUELLE} {plz}:") for f in fehler) for plz in ALLE_PLZ)
               and not any("heute gesperrt" in f for f in fehler if f.startswith(f"{m.QUELLE} "))]
    if ausfall:
        log("komplett ausgefallen, neuer Versuch in 3 Minuten: " + ", ".join(m.QUELLE for m in ausfall))
        time.sleep(180)
        for m in ausfall:
            neu = []
            _scrape_quelle(m, listings, gesehen, neu, lock)
            fehler[:] = [f for f in fehler if not f.startswith(m.QUELLE + " ")] + neu

    neu_inseriert(listings, gesehen)
    online_pruefen(listings, gesehen)
    # nicht mehr gesehene Inserate offline nehmen / alte löschen; Rausgeworfenes ein Jahr behalten, damit
    # neu_inseriert es wiedererkennt
    heute = dt.date.today()
    korb = set(load_json(DATA / "markierungen.json", {}).get("papierkorb") or {})
    for k in list(listings):
        r = listings[k]
        alter = (heute - dt.date.fromisoformat(r.get("zuletzt", TODAY))).days
        if alter >= (365 if k in korb else CONFIG["loeschen_nach_tagen"]):
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


# Anleger- vs. Eigennutzerpreis: manche Inserate zeigen den Nettopreis für Anleger (ohne 20 % USt);
# das Paar zieht selbst ein, also zählt der Preis für Eigennutzer
_BETRAG = r"(?:€|EUR)\s*(\d{1,3}(?:[.\u202f\u00a0 ]\d{3})+)(?:,[\d-]+)?"
# "Der Eigennutzerpreis beläuft sich auf EUR 1.090.770" stand bis 2026-11-07 nicht drin (Gartenwohnung Kuchelau)
_EIGEN = [re.compile(r"(?i)(?:eigennutzer|endnutzer|selbstnutzer)\w*\s*[:=]?\s*(?:beträgt\s*|beläuft\s+sich\s+auf\s*|liegt\s+bei\s*)?" + _BETRAG),
          re.compile(r"(?i)" + _BETRAG + r"[^.\n€]{0,25}?für\s+(?:eigennutzer|endnutzer|selbstnutzer)")]
_ANLEGER = [re.compile(r"(?i)anleger\w*[^.\n€]{0,60}?" + _BETRAG),
            re.compile(r"(?i)" + _BETRAG + r"[^.\n€]{0,40}?für\s+anleger")]
_NETTO = re.compile(r"(?i)(?:angegebene\s+kaufpreis|kaufpreis\s+versteht\s+sich)[^.\n]{0,30}?"
                    r"(?:zzgl|zuzüglich|exkl|plus)\.?\s*(?:der\s*)?(?:20\s*%\s*)?(?:ust|mwst|umsatzsteuer)")


def _betrag(s):
    return float(re.sub(r"\D", "", s))


def eigennutzer_preis(r):
    """-> {"preis", "text", "geschaetzt"} wenn der gezeigte Preis nicht der für Eigennutzer ist, sonst None."""
    p = r.get("preis")
    if not p:
        return None
    text = f"{r.get('titel') or ''}\n{r.get('text') or ''}"
    for rx in _EIGEN:
        for m in rx.finditer(text):
            e = _betrag(m.group(1))
            if e == p:
                return None
            if 1 < e / p < 1.3:
                return {"preis": e, "text": "Eigennutzerpreis steht so im Inserat"}
    anleger = {_betrag(m.group(1)) for rx in _ANLEGER for m in rx.finditer(text)}
    if p in anleger or _NETTO.search(text):
        return {"preis": round(p * 1.2), "geschaetzt": True,
                "text": "geschätzt: Anlegerpreis + 20 % USt"}
    return None


def rot_vielleicht_draussen(lat, lon, radius):
    """Bei unsicherer Lage gilt die rote Zone (Ausschluss) nur, wenn der ganze Umkreis darin liegt –
    im Zweifel bleibt die Wohnung (Wunsch). Die blauen Zonen gelten dagegen streng."""
    (_, txt, _), anteil = geo.pruefe_umkreis(lat, lon, radius)
    # die roten Zonen im 3. gelten streng wie die blauen (Saad 2026-11-01: dort war noch eine ungefähre drin)
    streng = {f"rote Zone: {z['properties']['name']}" for z in geo.ZONEN if z["properties"].get("streng")}
    return txt.startswith("rote Zone") and txt not in streng and anteil > 0


# ---------------------------------------------------------------- laufende Kosten, Versteigerung

_EUR = r"(?:€|EURO|EUR|Euro)\s*([\d.]+(?:,\d{1,2})?)(?:\s*,-+)?"
_KOSTEN_GESAMT = re.compile(r"(?i)(?:gesamt(?:belastung|kosten)?|insgesamt|summe|gesamte?\s+monatliche\s+kosten|bk-gesamtbelastung)"
                            r"[^\n€]{0,40}?" + _EUR)
_BK = re.compile(r"(?i)(?:betriebskosten|\bbk\b)(?:[- ]akonto)?[^\n€\d]{0,25}?" + _EUR + r"([^\n]{0,25})")
_RUECKLAGE = re.compile(r"(?i)(?:reparaturr(?:ü|ue)cklage|r(?:ü|ue)cklage|reparaturfonds|erhaltungsbeitrag)(?!\s*per)"
                        r"[^\n€\d]{0,25}?" + _EUR)
_LIFT = re.compile(r"(?i)\blift(?:kosten|betriebskosten)?[^\n€\d]{0,10}?" + _EUR)
_HEIZKOSTEN = re.compile(r"(?i)heizkosten \(exkl\. mwst\):\s*([\d.,]+)")


def _eur(s):
    s = s.strip().rstrip(".,-")
    s = s.replace(".", "").replace(",", ".") if "," in s else (s.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", s) else s)
    try:
        return float(s)
    except ValueError:
        return None


def laufende_kosten(gruppe):
    """Laufende Monatskosten brutto (Betriebskosten + Rücklage + Lift, Heizkosten wenn ausgewiesen) einer Wohnung,
    geschätzt aus allen Portalen: Portalfeld, im Text genannte Gesamtsumme oder Betriebskosten + Rücklage aus dem
    Text; der höchste plausible Wert zählt (Portale lassen die Rücklage oft weg). -> {"betrag", "von"} oder None.
    Wunsch 2026-11-04: über 700 € im Monat raus."""
    kand = []
    for r in gruppe:
        text = f"{r.get('text') or ''}"
        alt_is = r["id"].startswith("is-") and not r.get("monatlich_neu")  # alte, aufaddierte ImmoScout-Werte
        if r.get("monatlich") and 30 < r["monatlich"] < 5000 and not alt_is:
            heiz = [_eur(m.group(1)) for f in r.get("heizung_felder") or [] for m in [_HEIZKOSTEN.search(f)] if m]
            extra = sum(h for h in heiz if h and h < 1000) * 1.2
            kand.append((r["monatlich"] + extra, f"{r['quelle']}: monatliche Kosten" + (" + Heizkosten" if extra else "")))
        for zeile in text.split("\n"):
            if re.search(r"(?i)kaufpreis|provision|grunderwerb|grundbuch|vertragserricht|stand der|jährlich|pro jahr|p\.\s?a\.", zeile):
                continue
            for m in _KOSTEN_GESAMT.finditer(zeile):
                v = _eur(m.group(1))
                if v and 80 < v < 5000 and re.search(r"(?i)monat|mtl|vorschreibung|bk|betriebskost|rücklage|belastung", zeile + text[:0]):
                    kand.append((v, f"{r['quelle']}: Text \"{zeile.strip()[:80]}\""))
        bk = next(((_eur(m.group(1)), m.group(2)) for m in _BK.finditer(text) if _eur(m.group(1)) and 30 < _eur(m.group(1)) < 3000), None)
        rl = next((_eur(m.group(1)) for m in _RUECKLAGE.finditer(text) if _eur(m.group(1)) and 5 < _eur(m.group(1)) < 1500), None)
        if bk and rl:
            netto = re.search(r"(?i)netto|zzgl|exkl|excl|plus", bk[1] or "")
            lift = next((_eur(m.group(1)) for m in _LIFT.finditer(text) if _eur(m.group(1)) and _eur(m.group(1)) < 300), 0)
            summe = (bk[0] + (lift or 0)) * (1.1 if netto else 1) + rl
            kand.append((round(summe, 2), f"{r['quelle']}: Betriebskosten + Rücklage laut Text"))
    if not kand:
        return None
    betrag, von = max(kand)
    return {"betrag": round(betrag, 2), "von": von}


VERSTEIGERUNG = re.compile(r"(?i)versteiger|zwangsversteiger|exekution|insolvenz|konkurs|masseverwalter|sanierungsverwalter|"
                           r"\bauktion|bieterverfahren|bestbieter|mindestgebot|schätzgutachten|edikt")


def versteigerung(r):
    """Versteigerung, Insolvenzmasse, Bieterverfahren (Wunsch 2026-11-04: keine solchen Wohnungen) -> Fundstelle oder None."""
    for teil in (r.get("titel") or "", r.get("text") or ""):
        m = VERSTEIGERUNG.search(teil)
        if m:
            return teil[max(0, m.start() - 40):m.end() + 40].replace("\n", " ").strip()
    return None


def bewerten(r, rev):
    """-> dict mit status (gruen/grau/raus), gruende, lage, heizung, fragen (offene Prüfungen)."""
    out = {"gruende": [], "fragen": [], "ungefaehr": False, "lat": r.get("lat"), "lon": r.get("lon")}
    eck = rev.get("eckdaten") or {}
    r = {**r, **{k: eck[k] for k in ("zimmer", "flaeche") if eck.get(k)}}
    # ohne Preis ("auf Anfrage") nicht zeigen; erst hier, nicht in filter_grund, weil manche
    # Portale den Preis erst auf der Detailseite nennen
    prev = rev.get("preis") or {}
    ep = ({"preis": prev["eigennutzer"], "text": prev.get("begruendung") or "Preis für Eigennutzer (geprüft)"}
          if prev.get("eigennutzer") else eigennutzer_preis(r))
    if ep and ep["preis"] != r.get("preis"):
        out["preis"], out["preis_hinweis"] = ep["preis"], ep["text"]
        r = {**r, "preis": ep["preis"]}
    grund = filter_grund(r) or (None if r.get("preis") else "kein Preis angegeben")
    if grund:
        return {**out, "status": "raus", "art": "filter", "gruende": [grund]}
    if (fund := versteigerung(r)) and not (rev.get("versteigerung") or {}).get("ok"):
        return {**out, "status": "raus", "art": "filter", "gruende": [f"Versteigerung/Insolvenz: …{fund}…"]}
    kosten = (rev.get("kosten") or {}).get("betrag") or (r.get("laufende_kosten") or {}).get("betrag")
    if kosten and kosten > F["laufende_kosten_max"]:
        return {**out, "status": "raus", "art": "filter",
                "gruende": [f"laufende Kosten ca. {kosten:,.0f} € brutto im Monat (über {F['laufende_kosten_max']} €)".replace(",", ".")]}
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
            if lrev.get("adresse"):  # geprüfte Adresse (Recherche) statt der aus dem Inserat zeigen/verlinken
                out["adresse"] = lrev["adresse"]
            drin, lage_txt, _ = geo.pruefe(*pos)
            lage_txt += (f" (gleiches Haus wie ein anderes Inserat: {lrev['adresse']})" if lrev.get("quelle") == "gleiches Haus"
                         else f" (aus Beschreibung: {lrev.get('adresse') or 'Koordinaten'})")
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
    # genau 3 Zimmer im 18./19. nur bis 10 Minuten Öffis zum Gürtel (Wunsch); bei ungefährer Lage nur raus,
    # wenn es auch vom günstigsten Punkt im Umkreis zu weit wäre, sonst grau
    if r.get("zimmer") == 3 and r["plz"] in (1180, 1190):
        grenze = F["guertel_max_min_3_zimmer"]
        g = guertel_zeit(out["lat"], out["lon"]) if out["lat"] else None
        if not g:
            if out["lat"]:  # keine Haltestelle im Umkreis von 1,2 km
                return {**out, "status": "raus", "art": "guertel", "gruende": [f"3 Zimmer, mehr als {grenze} min zum Gürtel"]}
            grau.append(f"3 Zimmer: Öffi-Zeit zum Gürtel unbekannt (max. {grenze} min), Lage fehlt")
        elif g["min"] > grenze:
            spiel = ((r.get("lage_radius") or 250) / GEHEN_M_PRO_MIN) if out["ungefaehr"] else 0
            if g["min"] - spiel > grenze:
                return {**out, "status": "raus", "art": "guertel",
                        "gruende": [f"3 Zimmer, {g['min']} min zum Gürtel (max. {grenze})"]}
            grau.append(f"3 Zimmer: etwa {g['min']} min zum Gürtel, Lage ungefähr (max. {grenze} min)")
    if out["ungefaehr"] and out["lat"] and not out.get("versetzt") and not (lrev and lrev.get("sicherheit") == "ungefaehr"):
        out["lat"], out["lon"] = _jitter(r["id"], out["lat"], out["lon"])

    # 2) Zustand und Nutzung: unbefristet vermietet / sanierungsbedürftig -> raus
    zrev = rev.get("zustand")
    if zrev:
        if zrev.get("ergebnis") == "raus":
            return {**out, "status": "raus", "art": "zustand", "gruende": [zrev.get("begruendung") or "Zustand/Vermietung"]}
        if zrev.get("ergebnis") == "hinweis" and zrev.get("begruendung"):
            out["hinweis"] = zrev["begruendung"]
    # Einzug bis Q3 2027 (seit 2026-10-28, auch für schon geprüfte Wohnungen): alle Inserate der Gruppe
    # lesen, der Termin steht oft nur bei einem Makler
    if not (zrev or {}).get("bezug_ok"):
        for titel, text, baujahr in r.get("_alle") or [(r.get("titel"), r.get("text"), r.get("baujahr"))]:
            b = zustand.bezug_einschaetzen(f"{titel or ''}\n{text or ''}", baujahr) if text else None
            if b and b[0] == "raus":
                return {**out, "status": "raus", "art": "zustand", "gruende": [b[1][:200]]}
    if not zrev and r.get("detail_am"):
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
    # Heizung schließt seit 2026-10-28 nichts mehr aus: Gas, kein Gas oder unklar ist ein Filter auf
    # der Karte (Wunsch des Paares); die Prüfung läuft weiter, damit der Filter stimmt
    out["heizung"] = h
    if ep and ep.get("geschaetzt") and not prev:
        out["fragen"].append("preis")
        grau.append("Preis für Eigennutzer geschätzt (Inserat zeigt den Anlegerpreis)")
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


def _zahl(v):
    """"147,9", 147.9 oder "1886" -> Zahl, sonst None."""
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def ist_duplikat(a, b):
    """Dieselbe Wohnung auf zwei Portalen (oder doppelt auf einem)?"""
    if a["plz"] != b["plz"] or not (a.get("flaeche") and b.get("flaeche") and a.get("preis") and b.get("preis")):
        return False
    if a.get("zimmer") and b.get("zimmer") and a["zimmer"] != b["zimmer"]:
        return False
    # anderer Energieausweis oder anderes Baujahr = anderes Haus (z. B. Makler mit zwei Wohnungen zu
    # gleichem Preis und gleicher Fläche: Rembrandtstraße 1886 und Rotensterngasse 1960)
    ha, hb = _zahl((a.get("energie") or {}).get("hwb")), _zahl((b.get("energie") or {}).get("hwb"))
    if ha and hb and abs(ha - hb) > max(2, 0.05 * max(ha, hb)):
        return False
    ja, jb = _zahl(a.get("baujahr")), _zahl(b.get("baujahr"))
    if ja and jb and int(ja) != int(jb):
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


def _bt_treffer(bt, gruppe):
    """Passt eine Bauträger-Einheit zu dieser Gruppe? -> Rangzahl (kleiner = besser) oder None.
    Portale runden die Fläche und zeigen teils andere Preise; Saad: "matchen meistens über Quadratmeter oder Preis"."""
    if any(x.get("bt_projekt") == bt.get("bt_projekt") for x in gruppe if x.get("bt_projekt")):
        return None  # zwei Einheiten eines Projekts sind nie dieselbe Wohnung
    df = min((abs(x["flaeche"] - bt["flaeche"]) for x in gruppe if x.get("flaeche")), default=99)
    werte = [p for p in (bt.get("preis"), bt.get("bt_anleger")) if p]
    dp = min((abs(x["preis"] - p) / max(x["preis"], p) for x in gruppe if x.get("preis") for p in werte), default=9)
    if df > 1.5 or any(x.get("zimmer") and bt.get("zimmer") and abs(x["zimmer"] - bt["zimmer"]) > 1 for x in gruppe):
        return None
    strasse = re.sub(r"(?i)strasse", "straße", re.match(r"[^\d,]*", bt.get("adresse") or "").group(0).strip()).lower()
    worte = [w for w in (strasse, (bt.get("bt_name") or "").lower()) if len(w) >= 6]
    im_text = any(w in " ".join(str(x.get(k) or "") for k in ("titel", "adresse", "text")).lower().replace("strasse", "straße")
                  for x in gruppe for w in worte)
    nah = bool(bt.get("lat")) and any(x.get("lat") and GENAU[x.get("lage_genauigkeit")] >= 2 and not x.get("bt_projekt")
                                      and _abstand_m(x, bt) <= max(350, (x.get("lage_radius") or 0) + 100) for x in gruppe)
    if (dp <= 0.015 and (im_text or nah)) or (df <= 0.6 and dp <= 0.005) or (df <= 0.6 and dp <= 0.08 and im_text):
        return dp + df / 100 - (0.02 if im_text else 0)
    return None


def _bautraeger_einsortieren(gruppen, bts, listings, marken):
    """Bauträger-Einheiten sind keine eigene Liste: jede wird der Wohnung zugeordnet, die schon von einem Portal
    bekannt ist (Wunsch 2026-11-09), nur was nirgends inseriert ist, wird ein neuer Eintrag. Passt sie zu einer alten,
    rausgeworfenen oder gemerkten Inseratsnummer, zählt diese als frühere Nummer: Papierkorb und Nest gelten weiter."""
    paare = []
    for bt in bts:
        for g in gruppen:
            if g and g[0].get("plz") == bt.get("plz") and bt.get("preis") and bt.get("flaeche"):
                if (rang := _bt_treffer(bt, g)) is not None:
                    paare.append((rang, bt["id"], id(g), bt, g))
    paare.sort(key=lambda p: p[0])
    vergeben, voll = set(), set()
    for _, bid, gid, bt, g in paare:  # pro Wohnung eine Einheit je Projekt; dasselbe Projekt bei 3SI und EHL darf beide anhängen
        if bid not in vergeben and (gid, bt["bt_projekt"]) not in voll:
            g.append(bt)
            vergeben.add(bid)
            voll.add((gid, bt["bt_projekt"]))
    einzeln = []
    for bt in bts:
        if bt["id"] in vergeben:
            continue
        # dasselbe Projekt bei zwei Vermarktern (3SI und Winegg)
        g = next((g for g in einzeln if g[0].get("preis") and _bt_treffer(bt, g) is not None), None)
        if g:
            g.append(bt)
        else:
            einzeln.append([bt])
    gruppen.extend(einzeln)
    aktiv_ids = {r["id"] for g in gruppen for r in g}
    alte = [r for i, r in listings.items() if i in marken and i not in aktiv_ids and not r.get("bt_projekt")
            and r.get("preis") and r.get("flaeche")]
    for g in gruppen:
        for i, r in enumerate(g):
            if r.get("bt_projekt"):
                frueher = [a["id"] for a in alte if a.get("plz") == r.get("plz") and _bt_treffer(r, [a]) is not None]
                if frueher:
                    g[i] = {**r, "vorgaenger": list(r.get("vorgaenger") or []) + frueher}
    return len(vergeben)


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


def _preisverlauf(gruppe):
    """Je Portal der erste bekannte Preis und jede Änderung -> [[ab Datum, Preis, Portal], ...]."""
    punkte = []
    for r in gruppe:
        if not r.get("preis"):
            continue
        alt = r.get("preis_historie") or []  # [Änderungsdatum, Preis davor]
        preise = [p for _, p in alt] + [r["preis"]]
        daten = [r["erstmals"]] + [d for d, _ in alt]
        punkte += [[d, p, r["quelle"]] for d, p in zip(daten, preise)]
    return sorted(punkte)


_BILD_HASHES = None


def _bild_hashes():
    """Fingerabdrücke aus tools/bild_hashes.py (URL -> dHash), einmal geladen."""
    global _BILD_HASHES
    if _BILD_HASHES is None:
        _BILD_HASHES = load_json(DATA / "bild_hashes.json", {})
    return _BILD_HASHES


def _bilder_der_gruppe(gruppe):
    """Alle Fotos aller Portale, jedes nur einmal (Wunsch 2026-11-06: alle Fotos, auch den Grundriss).
    Dasselbe Foto hat auf jedem Portal eine andere Adresse: mit Fingerabdruck (tools/bild_hashes.py) gilt ein
    Foto als doppelt, wenn es sich in höchstens 6 von 64 Bits von einem schon gezeigten unterscheidet. Ohne
    Fingerabdrücke je Makler nur das Inserat mit den meisten Fotos (derselbe Makler stellt überall dieselben
    Fotos ein), Fotos anderer Makler kommen dazu."""
    sortiert = sorted(gruppe, key=lambda r: -len(r.get("bilder") or []))
    hashes = _bild_hashes()
    alle = [u for r in sortiert for u in (r.get("bilder") or [])]
    if alle and sum(u in hashes for u in alle) >= 0.8 * len(alle):
        gezeigt, fps = [], []
        for u in dict.fromkeys(alle):
            h = (hashes.get(u) or {}).get("h")
            if h is not None:
                x = int(h, 16)
                if any(bin(x ^ y).count("1") <= 6 for y in fps):
                    continue
                fps.append(x)
            gezeigt.append(u)
    else:
        je_makler = {}
        for r in sortiert:
            makler = re.sub(r"[^a-z0-9]", "", ((r.get("anbieter") or "").split() or [""])[0].lower()) or r["id"]
            je_makler.setdefault(makler, r.get("bilder") or [])
        gezeigt = list(dict.fromkeys(b for bilder in je_makler.values() for b in bilder))
    return _grundriss_nach_vorne(gezeigt)[:60]


def _grundriss_nach_vorne(bilder):
    """Den Grundriss als zweites Foto (Wunsch 2026-11-06), damit man ihn gleich sieht: das Foto mit dem
    höchsten Grundriss-Wert aus tools/bild_hashes.py (ab 0,6, wie tools/grundrisse.py) oder "grundriss" im Namen."""
    hashes = _bild_hashes()
    wert = {u: (hashes.get(u) or {}).get("g") or (1.0 if "grundriss" in u.lower() else 0) for u in bilder}
    bester = max(bilder[1:], key=lambda u: wert[u], default=None)
    if len(bilder) < 3 or bester is None or wert[bester] < 0.6 or wert[bilder[0]] >= wert[bester]:
        return bilder
    rest = [u for u in bilder[1:] if u != bester]
    return [bilder[0], bester] + rest


GR_PLAENE = DATA / "grundriss_plaene"
GR_GEPRUEFT = DATA / "grundriss_geprueft.json"
GR_OFFEN = DATA / "grundriss_offen.json"
GR_BILDER = DATA / "grundriss_bilder.json"


def _neue_grundrisse():
    """Neu gezeichnete Grundrisse (Wunsch 2026-11-06): data/grundriss_plaene/ID.json -> docs/grundrisse/ID.svg.
    Die Pläne schreibt die Routine bzw. Claude aus abfotografierten, technischen oder bekritzelten Originalen."""
    from wohnungen.grundriss_svg import zeichnen
    ziel = DOCS / "grundrisse"
    plaene = []
    for p in sorted(GR_PLAENE.glob("*.json")) if GR_PLAENE.exists() else []:
        plan = load_json(p, {})
        try:
            svg = zeichnen(plan)
        except Exception as e:
            log(f"Grundriss {p.name} nicht zeichenbar: {e}")
            continue
        ziel.mkdir(exist_ok=True)
        z = ziel / f"{p.stem}.svg"
        if not z.exists() or z.read_text(encoding="utf-8") != svg:
            z.write_text(svg, encoding="utf-8")
        plaene.append({"ids": set(plan.get("ids") or []), "ersetzt": plan.get("ersetzt") or [],
                       "url": f"grundrisse/{p.stem}.svg?v={hashlib.md5(svg.encode()).hexdigest()[:8]}"})
    for z in ziel.glob("*.svg") if ziel.exists() else []:
        if not (GR_PLAENE / f"{z.stem}.json").exists():
            z.unlink()
    # Fertige Pläne von außerhalb der Inserate, z. B. aus einem angehängten PDF (Wunsch 2026-11-08, Gentzgasse 83):
    # {"ID": {"ids": [...], "bild": "ID.jpg"}} in data/grundriss_bilder.json, Bild in docs/grundrisse/
    for eintrag in load_json(GR_BILDER, {}).values():
        z = ziel / eintrag["bild"]
        if z.exists():
            plaene.append({"ids": set(eintrag["ids"]), "ersetzt": eintrag.get("ersetzt") or [],
                           "url": f"grundrisse/{z.name}?v={hashlib.md5(z.read_bytes()).hexdigest()[:8]}"})
    return plaene


def _mit_neuem_grundriss(ids, bilder, plaene):
    """Neu gezeichneter Grundriss als zweites Foto, die hässlichen Originale (auch dasselbe Bild von anderen
    Portalen, per Fingerabdruck) ganz ans Ende (Wunsch 2026-11-06)."""
    plan = next((p for p in plaene if p["ids"] & set(ids)), None)
    if not plan:
        return bilder
    hashes = _bild_hashes()
    fps = [int(h["h"], 16) for u in plan["ersetzt"] if (h := hashes.get(u))]

    def alt(u):
        h = (hashes.get(u) or {}).get("h")
        return u in plan["ersetzt"] or (h is not None and any(bin(int(h, 16) ^ y).count("1") <= 6 for y in fps))
    alte, rest = [u for u in bilder if alt(u)], [u for u in bilder if not alt(u)]
    return rest[:1] + [plan["url"]] + rest[1:] + alte


def _grundriss_offen(karte, nest, korb, plaene):
    """Nest- und neue Wohnungen mit Grundriss-Kandidaten, die noch niemand angesehen hat (data/grundriss_offen.json).
    Die Routine entscheidet: schön lassen oder neu zeichnen (REVIEW.md). Kommt später ein neuer Plan dazu
    (anderer Fingerabdruck), wird die Wohnung wieder vorgelegt."""
    hashes = _bild_hashes()
    geprueft = load_json(GR_GEPRUEFT, {})
    offen = []
    for w in karte:
        if w["status"] == "raus" or w.get("offline") or not (set(w["ids"]) & nest or w.get("neu")):
            continue
        if set(w["ids"]) & korb and not w.get("korb_frei") and not set(w["ids"]) & nest:  # Papierkorb: nicht ansehen
            continue
        kand = [u for u in w["bilder"] if u.startswith("http") and ((hashes.get(u) or {}).get("g") or 0) >= 0.6]
        if not kand:
            continue
        gesehen = [int(h, 16) for e in geprueft.values() if set(e.get("ids") or []) & set(w["ids"])
                   for h in e.get("plaene") or []]
        neu = [u for u in kand if not any(bin(int(hashes[u]["h"], 16) ^ y).count("1") <= 6 for y in gesehen)]
        if gesehen and not neu:
            continue
        offen.append({"id": w["id"], "ids": w["ids"], "titel": w["titel"], "adresse": w.get("adresse"),
                      "flaeche": w.get("flaeche"), "zimmer": w.get("zimmer"), "im_nest": bool(set(w["ids"]) & nest),
                      "neu_gezeichnet": any(p["ids"] & set(w["ids"]) for p in plaene),
                      "plaene": kand, "ordner": f"data/grundrisse_zeichnen/{w['id']}/"})
    offen.sort(key=lambda e: not e["im_nest"])
    save_json(GR_OFFEN, offen)
    return offen


def zusammenfuehren(gruppe, reviews):
    """Eine Gruppe -> ein Datensatz mit der besten Info aller Portale + zusammengeführte Prüfungen."""
    def rang(r):
        # Portal-Inserate bleiben der Kopf des Eintrags (Titel, Nummer), die Bauträger-Einheit ergänzt nur
        return (not r.get("bt_projekt"), GENAU[r.get("lage_genauigkeit")], bool(r.get("detail_am")), len(r.get("text") or ""))
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
        m["bilder"] = _bilder_der_gruppe(gruppe)
        m["freiflaeche"] = list(dict.fromkeys(f for r in gruppe for f in (r.get("freiflaeche") or [])))
        m["detail_am"] = next((r["detail_am"] for r in gruppe if r.get("detail_am")), None)
    m["laufende_kosten"] = laufende_kosten(gruppe)
    m["erstmals"] = min(r["erstmals"] for r in gruppe)
    m["zuletzt"] = max(r.get("zuletzt") or r["erstmals"] for r in gruppe)
    m["preisverlauf"] = _preisverlauf(gruppe)
    # frühestes Inseratsdatum auf irgendeinem Portal (Dauer am Markt = Verhandlungsargument)
    datum = [str(r["veroeffentlicht"])[:10] for r in gruppe
             if re.match(r"\d{4}-\d\d-\d\d", str(r.get("veroeffentlicht") or ""))]
    m["online_seit"] = min(datum + [m["erstmals"]])
    m["links"] = sorted(({"quelle": r["quelle"], "url": r["url"], "preis": r.get("preis"), "id": r["id"],
                          "zuletzt": r.get("zuletzt")}
                         for r in gruppe), key=lambda l: (l["quelle"] != "willhaben", l["quelle"]))
    # frühere Nummern derselben Wohnung (neu inseriert): Nest, Papierkorb und Prüfungen gelten weiter
    m["ids"] = [r["id"] for r in gruppe] + [v for r in gruppe for v in r.get("vorgaenger") or []]
    # Prüfungen: Kopf zuerst; Gas von irgendeinem Portal schlägt alles; genaue Lage vor ungefährer
    revs = [reviews[i] for i in m["ids"] if i in reviews]
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
        p = [x["preis"] for x in revs if x.get("preis")]
        if p:
            rev["preis"] = p[0]
        for k in ("kosten", "versteigerung"):  # von Hand geprüft (2026-11-04)
            v = [x[k] for x in revs if x.get(k)]
            if v:
                rev[k] = v[0]
    return m, rev


def _zahl(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _haus_schluessel(r):
    """Makler + Energieausweis (HWB und fGEE): gilt fürs ganze Haus, nicht für die Wohnung."""
    e = r.get("energie") or {}
    hwb, fgee = _zahl(e.get("hwb")), _zahl(e.get("fgee"))
    makler = re.findall(r"[a-zäöü0-9]+", (r.get("anbieter") or "").lower())
    if hwb is None or fgee is None or not makler:
        return None
    return makler[0], round(hwb, 1), round(fgee, 2)


def _foto_schluessel(r):
    """willhaben speichert gleiche Fotos unter demselben Namen (…/NNNN_-614684930.jpg), auch in
    verschiedenen Inseraten: Fotos teilen = dieselbe Wohnung oder dasselbe Haus."""
    return {m for b in r.get("bilder") or [] for m in re.findall(r"cache\.willhaben\.at/mmo/.+_(-?\d{6,})\.jpg", b)}


def haus_index(listings, reviews):
    """Inserate mit Hausnummer (aus dem Inserat oder geprüft) nach Haus- und Foto-Schlüssel."""
    energie, fotos = {}, {}
    for r in listings.values():
        lrev = (reviews.get(r["id"]) or {}).get("lage") or {}
        if lrev.get("sicherheit") == "genau" and re.search(r"\d", lrev.get("adresse") or "") and lrev.get("lat"):
            adr = (lrev["adresse"], lrev["lat"], lrev["lon"])
        elif (r.get("lage_genauigkeit") == "adresse" and re.search(r"\d", r.get("adresse") or "") and r.get("lat")
              and (r.get("lage_radius") or 0) <= 50):
            adr = (r["adresse"], r["lat"], r["lon"])
        else:
            continue
        eintrag = (r["id"], r.get("plz"), *adr)
        if (k := _haus_schluessel(r)):
            energie.setdefault(k, []).append(eintrag)
        for f in _foto_schluessel(r):
            fotos.setdefault(f, []).append(eintrag)
    return energie, fotos


def gleiches_haus(r, gruppe, index):
    """Adresse eines anderen Inserats desselben Hauses (gleicher Makler und Energieausweis oder
    mindestens zwei gleiche Fotos), wenn alle Treffer dieselbe Adresse nennen. Seit 2026-10-30: die
    Routine hatte Währinger Straße 168 nicht gefunden, obwohl Lind dort Top 39 mit Adresse inserierte."""
    energie, fotos = index
    eigene = {x["id"] for x in gruppe}
    treffer, belege = [], []
    for x in gruppe:
        if (k := _haus_schluessel(x)):
            for e in energie.get(k, []):
                if e[0] not in eigene:
                    treffer.append(e)
                    belege.append(f"gleicher Makler und Energieausweis (HWB {k[1]:g}, fGEE {k[2]:g}) wie {e[0]}")
        gezaehlt = {}
        for f in _foto_schluessel(x):
            for e in fotos.get(f, []):
                if e[0] not in eigene:
                    gezaehlt[e] = gezaehlt.get(e, 0) + 1
        for e, n in gezaehlt.items():
            if n >= 2:
                treffer.append(e)
                belege.append(f"{n} gleiche Fotos wie {e[0]}")
    treffer = [e for e in treffer if e[1] == r.get("plz")]
    # "Währinger Straße 168/39" und "Währinger Straße 168" sind dasselbe Haus (Top abschneiden)
    haus = lambda a: re.sub(r"\s*/.*$", "", a).strip()  # noqa: E731
    adressen = {haus(e[2]).lower().replace("strasse", "straße") for e in treffer}
    if len(adressen) != 1:
        return None
    _, _, adresse, lat, lon = min(treffer, key=lambda e: len(e[2]))
    adresse = haus(adresse)
    # das Haus muss zum Portalpunkt passen: im Umkreis (versetzter Punkt) oder an der genannten Straße
    # (eine Straße ohne Nummer setzt willhaben in die Straßenmitte, Währinger Straße 168 lag 360 m daneben)
    strasse = lambda a: re.sub(r"\s*\d.*$", "", a or "").strip().lower().replace("strasse", "straße")  # noqa: E731
    gleiche_strasse = strasse(r.get("adresse")) and strasse(r.get("adresse")) == strasse(adresse)
    if r.get("lat") and not gleiche_strasse and _abstand_m(r, {"lat": lat, "lon": lon}) > (r.get("lage_radius") or 0) + 300:
        return None
    return {"adresse": adresse, "lat": lat, "lon": lon, "sicherheit": "genau", "quelle": "gleiches Haus",
            "begruendung": "; ".join(dict.fromkeys(belege))}


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
    markierungen = load_json(DATA / "markierungen.json", {})
    korb_zeit = markierungen.get("papierkorb") or {}
    korb = set(korb_zeit)
    nest = set(markierungen.get("gemerkt") or {})
    # neue Papierkorb-Einträge: war die Wohnung auf der zuletzt gebauten Karte ausgegraut? (die sah man
    # beim Rauswerfen); zurückgeholte vergessen, erneut rausgeworfene (neuer Zeitstempel) neu einordnen
    vorher = {i: w.get("offline", False) for w in load_json(MAP_DATA, {}).get("wohnungen", []) for i in w["ids"]}
    korb_status = {i: s for i, s in load_json(KORB_STATUS, {}).items() if i in korb}
    for i, zeit in korb_zeit.items():
        if (korb_status.get(i) or {}).get("zeit") != zeit:
            korb_status[i] = {"zeit": zeit, "offline": vorher.get(i, False)}
    archiv = load_json(PREISARCHIV, {})
    sichtbar = load_json(SICHTBAR, {})  # Inserat -> erster Tag auf der Karte
    recherche = []
    plaene = _neue_grundrisse()
    heute = dt.date.today()
    karte, pending, details = [], [], {}
    erster_lauf = min((r["erstmals"] for r in listings.values()), default=TODAY)
    zaehler = {"gruen": 0, "grau": 0, "raus": 0}
    # verschwundene Inserate noch zwei Wochen ausgegraut zeigen (damit man weiß, dass es sie nicht mehr gibt)
    stichtag = (DATA / "letzter_scrape.txt").read_text().strip() if (DATA / "letzter_scrape.txt").exists() else TODAY
    aktiv = [r for r in listings.values() if r.get("aktiv") or (
        not r.get("nachfolger") and (heute - dt.date.fromisoformat(r.get("zuletzt", TODAY))).days <= 14)]
    # Makler setzen manchmal denselben Standardpunkt für viele Inserate. Teilen sich 3+ verschiedene
    # Inserate exakt dieselben Koordinaten, ist der Punkt verdächtig (zusammenfuehren prüft dann den Text)
    titel_pro_punkt = {}
    for r in aktiv:
        if r.get("lat") and GENAU[r.get("lage_genauigkeit")] >= 2 and not r.get("bt_projekt"):
            titel_pro_punkt.setdefault((r["lat"], r["lon"]), set()).add((r.get("titel") or "")[:25].lower())
    verdaechtig = {p for p, t in titel_pro_punkt.items() if len(t) >= 3}
    aktiv = [{**r, "punkt_verdaechtig": True} if (r.get("lat"), r.get("lon")) in verdaechtig else r for r in aktiv]
    gruppen = gruppieren([r for r in aktiv if not _sammelinserat(r) and not r.get("bt_projekt")])
    # von Hand erkannte Doppelte (z. B. gleicher Grundriss, verschiedene Makler): reviews "gleich_wie"
    for a, rv in reviews.items():
        b = rv.get("gleich_wie")
        ga = next((g for g in gruppen if any(r["id"] == a for r in g)), None)
        gb = next((g for g in gruppen if any(r["id"] == b for r in g)), None)
        if ga is not None and gb is not None and ga is not gb:
            ga.extend(gb)
            gruppen.remove(gb)
    _m = load_json(DATA / "markierungen.json", {})
    bt_zugeordnet = _bautraeger_einsortieren(gruppen, [r for r in aktiv if r.get("bt_projekt")], listings,
                                             set(_m.get("papierkorb") or {}) | set(_m.get("gemerkt") or {}))
    log(f"Bauträger: {bt_zugeordnet} Einheiten bestehenden Einträgen zugeordnet")
    gruppen += [[r] for r in aktiv if _sammelinserat(r)]
    haeuser = haus_index(listings, reviews)  # für gleiches_haus: Adresse aus Schwester-Inseraten
    doppelt = sum(len(g) - 1 for g in gruppen)
    for gruppe in gruppen:
        r, rev = zusammenfuehren(gruppe, reviews)
        if ((rev.get("lage") or {}).get("sicherheit") != "genau" and not re.search(r"\d", r.get("adresse") or "")
                and (haus := gleiches_haus(r, gruppe, haeuser))):
            rev = {**rev, "lage": haus}
        b = bewerten({**r, "_alle": [(x.get("titel"), x.get("text"), x.get("baujahr")) for x in gruppe]}, rev)
        offline = r["zuletzt"] < stichtag  # beim letzten Scrape auf keinem Portal mehr gefunden
        if offline:
            d = r["zuletzt"].split("-")
            b["gruende"] = [f"Nicht mehr online (zuletzt gesehen {d[2]}.{d[1]}.)"] + b["gruende"]
        eck = rev.get("eckdaten") or {}
        # ausgegraut rausgeworfen und jetzt wieder online: zählt nicht mehr als Papierkorb
        frei = {i: korb_zeit[i] for i in r["ids"] if not offline and korb_status.get(i, {}).get("offline")}
        if not offline:
            zaehler[b["status"]] += 1
        if (not offline and b["status"] != "raus" and not lage_genau(r, rev, b)
                and not set(r["ids"]) & (erledigt | (korb - set(frei)))):
            recherche.append({
                "id": r["id"], "ids": r["ids"], "titel": r["titel"], "plz": r["plz"],
                "links": [l["url"] for l in r["links"]], "anbieter": r.get("anbieter"),
                "adresse_im_inserat": r.get("adresse"), "lage": b.get("lage"),
                "punkt": [b["lat"], b["lon"]], "versatz_m": r.get("lage_radius") or 0,
                "preis": r.get("preis"), "flaeche": r.get("flaeche"), "zimmer": r.get("zimmer"),
                "stockwerk": r.get("stockwerk"), "energie": r.get("energie"),
                "grundrisse": f"data/grundrisse/{r['id']}/", "im_nest": bool(set(r["ids"]) & nest),
                "dokumente": [d for i in r["ids"] for d in (listings.get(i) or {}).get("dokumente") or []],
                "erstmals": r["erstmals"],
            })
        if b["fragen"] and r.get("detail_am") and b["status"] != "raus" and not offline:
            pending.append({
                "id": r["id"], "fragen": b["fragen"], "url": r["url"], "titel": r["titel"],
                "plz": r["plz"], "adresse_im_inserat": r.get("adresse"),
                "heizung_felder": r.get("heizung_felder", []),
                "heizung_vorab": b.get("heizung", {}).get("text"),
                "text": (r.get("text") or "")[:9000],
            })
        im_nest = bool(set(r["ids"]) & nest)
        if (b["status"] == "raus" and b.get("art") == "filter" and not im_nest) or not b.get("lat"):
            continue
        # Anlegerpreise (netto) sind keine Preisänderung: aus dem Verlauf nehmen (2026-11-07: MAISON WÄHRING zeigte
        # 683.486 -> 745.000 als "+61.514", dabei ist 683.486 nur der Preis für Anleger mit Vorsteuerabzug)
        anleger = {_betrag(m.group(1)) for rx in _ANLEGER for m in rx.finditer(r.get("text") or "")}
        if b.get("preis") and r.get("preis") and b["preis"] != r["preis"]:
            anleger.add(r["preis"])
        anleger.discard(b.get("preis") or r.get("preis"))
        r["preisverlauf"] = [v for v in r["preisverlauf"] if v[1] not in anleger]
        if im_nest:  # Preisverlauf sammeln, über Neu-Inserate desselben Objekts hinweg
            schluessel = next((k for k, e in archiv.items() if set(e["ids"]) & set(r["ids"])), r["id"])
            e = archiv.setdefault(schluessel, {"ids": [], "verlauf": []})
            e["ids"] = sorted(set(e["ids"]) | set(r["ids"]))
            e["verlauf"] = sorted({tuple(v) for v in e["verlauf"] + r["preisverlauf"] if v[1] not in anleger})
            e["online_seit"] = min(e.get("online_seit") or r["online_seit"], r["online_seit"])
            r["preisverlauf"], r["online_seit"] = [list(v) for v in e["verlauf"]], e["online_seit"]
        # "neu" zählt ab dem Tag, an dem die Wohnung auf der Karte auftaucht (nicht ab dem ersten Fund):
        # so sind auch Wohnungen neu, die erst durch eine Regeländerung passen (z. B. Gasheizung)
        if b["status"] != "raus" and not offline:
            seit = min([sichtbar[i] for i in r["ids"] if i in sichtbar] or [TODAY])
            for i in r["ids"]:
                sichtbar.setdefault(i, seit)
        else:
            seit = r["erstmals"]
        if frei and b["status"] != "raus":  # wieder da: neu ab dem Tag der Rückkehr
            seit = max([seit] + [korb_status[i].setdefault("wieder_da", TODAY) for i in frei])
        # beim allerersten Lauf ist alles "neu" – das zählt nicht
        neu = seit > erster_lauf and (heute - dt.date.fromisoformat(seit)).days < CONFIG["neu_tage"]
        karte.append({
            "id": r["id"], "ids": r["ids"], "links": r["links"], "quelle": r["quelle"], "url": r["url"],
            "titel": r["titel"], "status": b["status"], "gruende": b["gruende"], "offline": offline, "lat": b["lat"], "lon": b["lon"],
            "ungefaehr": b["ungefaehr"], "radius": (r.get("lage_radius") or None) if b["ungefaehr"] else None,
            "preis": b.get("preis") or r.get("preis"),
            "preis_inserat": r.get("preis") if b.get("preis") else None, "preis_hinweis": b.get("preis_hinweis"),
            "flaeche": r.get("flaeche") or eck.get("flaeche"),
            "zimmer": r.get("zimmer") or eck.get("zimmer"), "plz": r["plz"], "adresse": b.get("adresse") or r.get("adresse"),
            "lage": b.get("lage"), "heizung": b.get("heizung"), "bild": r.get("bild"),
            "erstmals": r["erstmals"], "neu": neu, "preisverlauf": r["preisverlauf"], "online_seit": r["online_seit"],
            **({"korb_frei": frei, "neu_seit": seit} if frei else {}),
            "baujahr": r.get("baujahr"), "bauart": r.get("bauart"), "stockwerk": r.get("stockwerk"),
            "monatlich": (r.get("laufende_kosten") or {}).get("betrag"), "energie": r.get("energie"), "anbieter": r.get("anbieter"),
            "bilder": _mit_neuem_grundriss(r["ids"], _grundriss_nach_vorne(
                r.get("bilder") or ([r["bild"]] if r.get("bild") else [])), plaene),
            "freiflaeche": r.get("freiflaeche") or [], "zustand": r.get("zustand"),
            # nur 18./19. Bezirk und nur bei bekannter Lage (bei ungefährer Lage wäre die Zeit geraten)
            "guertel": ({**g, "ungefaehr": bool(b.get("landmarke"))}
                        if r["plz"] in (1180, 1190) and (not b["ungefaehr"] or b.get("landmarke"))
                        and (g := guertel_zeit(b["lat"], b["lon"])) else None),
        })
        if r.get("text"):
            details[r["id"]] = {"text": r["text"], "heizung_felder": r.get("heizung_felder", [])}
        if im_nest:
            e["stand"] = {**karte[-1], "zuletzt": r["zuletzt"]}
            e["details"] = details.get(r["id"])
    # Nest-Wohnungen, deren Inserat verschwunden ist: letzter Stand bleibt sichtbar
    auf_karte = {i for w in karte for i in w["ids"]}
    for e in archiv.values():
        w = e.get("stand")
        if w and set(e["ids"]) & nest and not set(e["ids"]) & auf_karte:
            karte.append({**w, "status": "grau", "neu": False, "offline": True, "preisverlauf": e["verlauf"],
                          "gruende": [f"Inserat nicht mehr online (zuletzt gesehen {w.get('zuletzt', '?')})"]})
            if e.get("details"):
                details[w["id"]] = e["details"]
    save_json(PREISARCHIV, archiv)
    save_json(SICHTBAR, sichtbar)
    save_json(KORB_STATUS, korb_status)
    # Street View vom Gehsteig aus mit Blick aufs Haus (nur bei genauer Lage; neue Punkte max. 150 pro Lauf)
    neu_abgefragt = 0
    for w in karte:
        if w.get("ungefaehr") or not w.get("lat") or w["status"] == "raus":
            continue
        try:
            from wohnungen import geocode as _g
            if neu_abgefragt >= 150 and f"{w['lat']:.6f},{w['lon']:.6f}" not in (_g._blick or {}):
                continue
            neu_abgefragt += 1
            w["sv"] = strassenblick(w["lat"], w["lon"])
        except Exception as e:  # Netz weg: dann eben ohne
            log(f"Street-View-Punkt {w['id']}: {e}")
    karte.sort(key=lambda x: (x["status"] != "gruen", x["erstmals"]), reverse=False)
    quellen = sorted({l["quelle"] for w in karte for l in w["links"]}, key=lambda q: (q != "willhaben", q))
    save_json(MAP_DATA, {"stand": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "anzahl": zaehler,
                         "quellen": quellen, "wohnungen": karte}, indent=None)
    save_json(PENDING, pending)
    # Reihenfolge = Vorrang für die Routine (sie schafft RECHERCHE_PRO_TAG): Nest, dann neueste
    recherche.sort(key=lambda e: e["erstmals"], reverse=True)
    recherche.sort(key=lambda e: not e["im_nest"])
    save_json(RECHERCHE, recherche)
    gr_offen = _grundriss_offen(karte, nest, korb, plaene)
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
        f"| {doppelt} Duplikate zusammengeführt | offene Prüfungen: {len(pending)} | Adress-Recherchen: {len(recherche)}"
        f" | Grundrisse ansehen: {len(gr_offen)}, neu gezeichnet: {len(plaene)}")


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
        for k in ("lage", "heizung", "eckdaten", "zustand", "gleich_wie", "preis", "kosten", "versteigerung"):
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
