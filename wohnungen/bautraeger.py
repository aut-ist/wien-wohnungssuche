"""Neubauprojekte direkt bei Bauträgern und Vermarktern (Wunsch 2026-11-09).

Welche Projekte es gibt, steht in data/bautraeger_projekte.json (gepflegt von Claude, siehe REVIEW.md
"Neubauprojekte suchen"). Dieses Modul liest täglich die öffentliche Einheitenliste jedes Projekts und
liefert jede freie Einheit als normales Inserat; Filter, Lage, Duplikate gegen die Portale und Karte
macht die übliche Pipeline.

Eintrag: {"schluessel", "name", "bautraeger", "plz", "adresse", "lat", "lon", "url_einheiten", "url_projekt",
          "parser": "tabelle" | "attribute" | "state" | "regex", "regex": "...", "fertigstellung", "heizung", "aktiv"}.
- parser "tabelle": HTML-Tabelle mit Kopfzeile (Top, Zimmer, Wohnfläche, Preis; siehe _SPALTEN).
- parser "attribute": Karten mit data-price, data-status, data-size/area, data-zimmer/rooms (CROWND, Semper47).
- parser "state": Einheiten als JSON im Attribut data-state (RIWOG).
- parser "regex": je Einheit ein Treffer mit den benannten Gruppen top, zimmer, flaeche, preis, optional
  stiege, geschoss, status (für Karten statt Tabellen).
Dazu liest search() die Projektübersicht von 3SI (ein Format für alle Projekte), neue Projekte kommen von selbst dazu.
Nur normale öffentliche Seiten; ohne Preis (verkauft, "-", "auf Anfrage") zählt eine Einheit nicht, und
vermietete Einheiten (OPTIN schreibt das nur in den Link) auch nicht.
"""
import html as htmllib
import json
import re
import urllib.parse

from .config import CONFIG, DATA, load_json
from .http import get, numid

QUELLE = "Bauträger"
PREFIX = "bt"
PROJEKTE = DATA / "bautraeger_projekte.json"

_SPALTEN = [  # (Feld, Muster für die Kopfzelle); die erste passende Spalte gilt
    ("top", r"^(top|tür|tuer|whg|wohnung|einheit)\b|\btop\b"),
    ("stiege", r"stiege|haus\b|bauteil"),
    ("geschoss", r"geschoss|etage|stock|ebene"),
    ("zimmer", r"zimmer|\bzim\b|räume"),
    ("anleger", r"anleger"),
    ("eigennutzer", r"eigennutz|eigentümer|endnutz|brutto"),
    ("status", r"status|verfügbar"),
    ("garten", r"garten"), ("loggia", r"loggia"), ("balkon", r"balkon"), ("terrasse", r"terrasse"),
    ("freiflaeche", r"freifl|außenfl|aussenfl"),
    ("flaeche", r"wohnfl|nutzfl|wnfl|fläche|m²|m2"),
    ("preis", r"preis|€"),
]
_NICHT_FREI = re.compile(r"(?i)verkauft|reserviert|vergeben|\bsold\b|reserved|option")
_ZEILE_WEG = re.compile(r"(?i)--sold|--reserved|state-sold|state-reserved")
_KEINE_WOHNUNG = re.compile(r"(?i)\bbüro\b|\bpraxis\b|gewerbe|geschäftslokal|\blager\b|stellplatz|\bgarage\b")
_UEBERSICHT_3SI = "https://www.3si.at/de/bautraeger-projekte/"
_cache = {}  # id -> Einheit, von search() gefüllt
_3si = None  # Projekte aus der 3SI-Übersicht, einmal pro Lauf
_alles_gelesen = False


def _text(s):
    s = re.sub(r"(?is)<(script|style|svg)\b.*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", s)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return re.sub(r"\s*\n\s*", "\n", re.sub(r"[ \t]+", " ", s)).strip()


def _zelle(s):
    return re.sub(r"\s+", " ", _text(s)).strip()


def _zahl(s):
    """'1.191.300 €' -> 1191300.0 ; '109,54 m²' -> 109.54 ; '132.11' -> 132.11 ; '-' -> None"""
    m = re.search(r"\d[\d.\s]*(?:,\d+)?", str(s or "").replace("\xa0", " "))
    if not m:
        return None
    t = re.sub(r"\s", "", m.group(0)).rstrip(".")
    try:
        if "," in t:
            return float(t.replace(".", "").replace(",", "."))
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
            return float(t.replace(".", ""))
        return float(t)
    except ValueError:
        return None


def _spalten(kopf):
    belegt = {}
    for feld, muster in _SPALTEN:
        for i, k in enumerate(kopf):
            if i in belegt.values() or not k or not re.search(muster, k.lower()):
                continue
            if feld == "flaeche" and re.search(r"(?i)frei|garten|terrasse|balkon|loggia|keller", k):
                continue
            if feld == "preis" and re.search(r"(?i)anleger|m²|m2|garage|stellplatz|\bbk\b", k):
                continue
            belegt[feld] = i
            break
    return belegt


def _aus_tabellen(page):
    """Einheiten aus allen HTML-Tabellen, die wie eine Einheitenliste aussehen."""
    for tb in re.findall(r"(?is)<table\b.*?</table>", page):
        sp = None
        for attr, z in re.findall(r"(?is)<tr\b([^>]*)>(.*?)</tr>", tb):
            zellen = [_zelle(x) for x in re.findall(r"(?is)<t[hd]\b[^>]*>(.*?)</t[hd]>", z)]
            if sp is None:
                k = _spalten(zellen)
                if {"top", "zimmer", "flaeche"} <= set(k) and ({"preis", "eigennutzer"} & set(k)):
                    sp = k
                continue
            if len(zellen) <= max(sp.values()) or _ZEILE_WEG.search(attr) or "vermietet" in z.lower():
                continue
            if _KEINE_WOHNUNG.search(" ".join(zellen)):  # Apostelhof: "Büro / Praxis" mit Zimmern und Preis
                continue
            w = {f: zellen[i] for f, i in sp.items()}
            w["attr_id"] = (re.search(r'data-[a-z-]*id="([^"]+)"', attr) or [None, None])[1]
            w["href"] = (re.search(r'(?i)(?:data-href|href)="(?!mailto:|tel:|javascript:)([^"#][^"]*)"', attr + z) or [None, None])[1]
            yield w


def _aus_attributen(page):
    """Karten mit data-Attributen; dieselbe Einheit kann doppelt vorkommen (Karte und Liste)."""
    for m in re.finditer(r'(?is)<[a-z]+\b[^>]*\bdata-price="[^"]*"[^>]*>', page):
        a = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', m.group(0)))
        nach = page[m.end():m.end() + 2500]
        t = re.search(r"(?i)top[-\s]*(\d[\w/+-]*)", a.get("slug") or "") or re.search(r"(?i)\btop\s*(\d[\w/+-]*)", _zelle(nach))
        h = re.search(r'(?i)href="([^"#][^"]*)"', nach)
        b = re.search(r'(?i)<img\b[^>]*\bsrc="(https?://[^"]+)"', nach)
        yield {"top": t.group(1) if t else "", "status": a.get("status", ""), "preis": a.get("price"),
               "flaeche": a.get("size") or a.get("area"), "zimmer": a.get("zimmer") or a.get("rooms"),
               "href": h.group(1) if h else None, "bild": htmllib.unescape(b.group(1)) if b else None}


def _aus_state(page):
    """RIWOG: Einheiten als HTML-maskiertes JSON im Attribut data-state, nicht in der sichtbaren Tabelle."""
    for roh in re.findall(r'data-state="(\{&quot;totalSize.*?)"', page, re.S):
        for e in json.loads(htmllib.unescape(roh)).get("items", []):
            if e.get("Sold") or e.get("Reserved") or e.get("MarketingType") != "purchase":
                continue
            plan = re.search(r'href="([^"]+)"', e.get("RenderedPlanGallery") or "")
            yield {"top": e.get("DoorNumber") or "", "stiege": e.get("Stair") or "", "geschoss": e.get("Tier"),
                   "zimmer": e.get("RoomCount"), "flaeche": e.get("Area"), "preis": e.get("GenericPrice"),
                   "balkon": e.get("BalconyArea"), "terrasse": e.get("TerraceArea"), "loggia": e.get("LoggiaArea"),
                   "garten": e.get("GardenArea"), "status": e.get("Status") or "", "href": e.get("RealtyLink"),
                   "bild": e.get("ImageLink"), "plan": plan.group(1) if plan else None,
                   "hinweis": e.get("SanitizedTitle"), "heizung": e.get("EquipmentDescription")}


def _aus_regex(page, muster):
    for m in re.finditer(muster, page, re.S):
        yield {k: _zelle(v) for k, v in m.groupdict().items() if v is not None}


def _medien(page, attr_id):
    """Fotos und Grundriss der Einheit, wenn die Seite je Zeile einen <template id="…-ID"> Block hat."""
    if not attr_id:
        return [], []
    m = re.search(r'(?is)<template\b[^>]*id="[^"]*-' + re.escape(attr_id) + r'".*?</template>', page)
    if not m:
        return [], []
    b = list(dict.fromkeys(re.findall(r'(?i)<img\b[^>]*\bsrc="(https?://[^"]+)"', m.group(0))))
    d = [{"name": _zelle(n) or "Grundriss", "url": u} for u, n in
         re.findall(r'(?is)<a\b[^>]*href="(https?://[^"]+\.pdf)"[^>]*>(.*?)</a>', m.group(0))]
    return b[:30], d


def _aus_3si_uebersicht(bekannt):
    """Neue 3SI-Projekte in den gesuchten Bezirken, die noch nicht in der Liste stehen (einmal pro Lauf)."""
    global _3si
    if _3si is None:
        plz = CONFIG["bezirke"]["ganz"] + CONFIG["bezirke"]["mit_zonen"]
        _3si = []
        try:
            page = get(_UEBERSICHT_3SI) or ""
        except Exception as e:
            print(f"3SI-Übersicht: {e}", flush=True)
            page = ""
        for slug in sorted(set(re.findall(r"bautraeger-projekte/(\d{4}-wien-[a-z0-9-]+)/", page))):
            if int(slug[:4]) not in plz or f"{_UEBERSICHT_3SI}{slug}/" in bekannt:
                continue
            teile = slug.split("-")[2:]
            # Slug: Straße, dann Projektname, oft die Straße noch einmal mit Hausnummer (…-hetzgasse-hetzgasse-3a)
            k = next((n for n in range(1, len(teile) // 2 + 1) if teile[:n] == teile[n:2 * n]), None)
            rest = teile[k:] if k else teile
            woerter = [t for t in rest if not t[0].isdigit()]
            nummer = "-".join(t for t in rest if t[0].isdigit()).upper()
            strasse = "-".join(woerter).title()
            for a, b in (("ae", "ä"), ("oe", "ö"), ("ue", "ü"), ("strasse", "straße")):
                strasse = strasse.replace(a, b)
            name = f"{strasse} {nummer}".strip()
            adresse = name if k and nummer else None
            _3si.append({"schluessel": "3si-" + slug, "name": name, "bautraeger": "3SI Immogroup", "plz": int(slug[:4]),
                         "adresse": adresse, "url_einheiten": f"{_UEBERSICHT_3SI}{slug}/", "parser": "tabelle"})
    return _3si


def _projekte():
    alle = load_json(PROJEKTE, [])
    return [p for p in alle if p.get("aktiv", True)] + _aus_3si_uebersicht({p.get("url_einheiten") for p in alle})


def _ort(p):
    """Koordinaten für automatisch gefundene Projekte."""
    if p.get("lat") or not p.get("adresse"):
        return
    try:
        from .geocode import geocode
        pos = geocode(f"{p['adresse']}, {p['plz']} Wien")
        if pos:
            p["lat"], p["lon"] = pos
    except Exception:
        pass


def _beschreibung(page):
    """Fließtext der Projektseite, ohne Tabellen und Technik; die Pipeline liest daraus Bezug, Zustand usw."""
    s = re.sub(r"(?is)<(template|table|nav|footer|header|form|noscript)\b.*?</\1>", " ", page)
    m = re.search(r"(?is)<body\b.*", s)
    zeilen = [z for z in _text(m.group(0) if m else s).split("\n") if len(z) > 40]
    return "\n".join(zeilen)[:5000]


def _eur(x):
    return f"€ {x:,.0f}".replace(",", ".")


def _einheiten(p):
    """-> Liste fertiger Einheiten dieses Projekts (nur frei, mit Preis und Zimmern)."""
    page = get(p["url_einheiten"], retries=2)
    if not page:
        return []
    _ort(p)
    art = p.get("parser")
    if art == "regex":
        roh = _aus_regex(page, p["regex"])
    elif art == "attribute":
        roh = _aus_attributen(page)
    elif art == "state":
        roh = _aus_state(page)
    else:
        roh = _aus_tabellen(page)
    text_projekt = _beschreibung(page)
    og = re.search(r'(?i)<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
    aus, gesehen = [], set()
    for w in roh:
        preis = _zahl(w.get("eigennutzer")) or _zahl(w.get("preis"))
        flaeche, zimmer = _zahl(w.get("flaeche")), _zahl(w.get("zimmer"))
        top = re.sub(r"(?i)^top\s*", "", (w.get("top") or "").split("|")[0]).strip(" -")
        if not w.get("href") and top:  # 3SI: die eigene Seite der Einheit steht nur beim Foto-Slider ("zu Top 1/6")
            h = re.search(r'href="([^"]+)"[^>]*>\s*zu Top\s*' + re.escape(top) + r"\s*<", page)
            w["href"] = h.group(1) if h else None
        slug = (w.get("href") or "").rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        if not (preis and preis > 50000 and flaeche and zimmer and (top or slug)) or _NICHT_FREI.search(w.get("status") or ""):
            continue
        stiege = (w.get("stiege") or "").strip()
        marke = f"{p['schluessel']}|{stiege}|{top or slug}"
        if marke in gesehen:
            continue
        gesehen.add(marke)
        bilder, dokumente = _medien(page, w.get("attr_id"))
        if not bilder and w.get("bild"):
            bilder = [w["bild"]]
        if w.get("plan"):
            bilder.append(w["plan"])
        if not bilder and og:
            bilder = [htmllib.unescape(og.group(1))]
        frei = [n.capitalize() for n in ("balkon", "terrasse", "loggia", "garten") if (_zahl(w.get(n)) or 0) > 0]
        geschoss = (w.get("geschoss") or "").strip() or None
        name_top = f"{stiege}/{top}" if stiege and top else top
        kopf = (f"Top {name_top}" if name_top else "Wohnung") + (f", {geschoss}" if geschoss else "")
        zeilen = [f"## Einheit\n{kopf}, {flaeche:g} m², {int(zimmer)} Zimmer",
                  ("Eigennutzerpreis: " if w.get("eigennutzer") else "Kaufpreis: ") + _eur(preis)]
        if _zahl(w.get("anleger")):
            zeilen.append("Anlegerpreis (netto): " + _eur(_zahl(w["anleger"])))
        zeilen += [f"{n.capitalize()}: {w[n]}" for n in ("garten", "loggia", "balkon", "terrasse") if (_zahl(w.get(n)) or 0) > 0]
        if w.get("hinweis"):
            zeilen.append(w["hinweis"])
        if p.get("fertigstellung"):
            zeilen.append(f"Fertigstellung: {p['fertigstellung']}")
        zeilen.append(f"Bauträger: {p.get('bautraeger') or p.get('name')}")
        text = "\n".join(zeilen) + "\n\n## Projekt\n" + text_projekt
        if w.get("href"):
            url = urllib.parse.urljoin(p["url_einheiten"], w["href"])
        else:
            url = p["url_einheiten"] + (f"#{w['attr_id']}" if w.get("attr_id") else "")
        genau = "adresse" if p.get("lat") and re.search(r"\d", p.get("adresse") or "") else "strasse" if p.get("lat") else "bezirk"
        aus.append({
            "id": f"{PREFIX}-{numid(marke)}", "quelle": QUELLE, "url": url,
            "titel": p["name"] + (f" – Top {name_top}" if name_top else "") + f", {int(zimmer)} Zimmer",
            "preis": preis, "flaeche": flaeche, "zimmer": int(zimmer), "plz": p["plz"],
            "adresse": p.get("adresse"), "lat": p.get("lat"), "lon": p.get("lon"), "lage_genauigkeit": genau,
            "bild": bilder[0] if bilder else None, "bilder": bilder, "veroeffentlicht": None,
            "anbieter": p.get("vermarkter") or p.get("bautraeger"), "typ": "Eigentumswohnung",
            "freiflaeche": frei, "projekt": False,
            # für den Abgleich mit den Portalen in run.py (_bautraeger_einsortieren)
            "bt_projekt": p["schluessel"], "bt_name": p["name"], "bt_anleger": _zahl(w.get("anleger")),
            "_seite": p["url_einheiten"],
            "_detail": {"text": text, "heizung_felder": [f"Heizung: {h}" for h in (p.get("heizung"), w.get("heizung")) if h],
                        "stockwerk": geschoss, "baujahr": p.get("baujahr"), "bauart": p.get("bauart"),
                        "dokumente": dokumente, "energie": p.get("energie"), "monatlich": None},
        })
    return aus


def search(plz):
    for p in _projekte():
        if p.get("plz") != plz:
            continue
        try:
            einheiten = _einheiten(p)
        except Exception as e:  # ein kaputtes Projekt soll die anderen nicht stoppen
            print(f"Bauträger {p.get('schluessel')}: {e}", flush=True)
            continue
        print(f"Bauträger {p.get('schluessel')}: {len(einheiten)} freie Einheiten", flush=True)
        for e in einheiten:
            _cache[e["id"]] = e
            yield {k: v for k, v in e.items() if not k.startswith("_")}


_FOTO = re.compile(r'(?i)(?:src|data-src)="([^"]+(?:/assets/immobilien/|justimmo|/fileadmin/realestate/|/wp-content/uploads/)[^"]+\.(?:jpe?g|png|webp)[^"]*)"')


def _einheit_seite(e, d):
    """Hat die Einheit eine eigene Seite: deren Text (Zustand, Vermietung, Kosten) und Fotos dazunehmen."""
    url = e["url"]
    if "#" in url or url == e.get("_seite"):
        return
    page = get(url, retries=1)
    if not page:
        return
    d["text"] = d["text"].replace("\n\n## Projekt\n", "\n\n## Wohnung\n" + _beschreibung(page) + "\n\n## Projekt\n", 1)
    fotos = [urllib.parse.urljoin(url, htmllib.unescape(u)) for u in _FOTO.findall(page) if "__Scale" not in u]
    if fotos:
        d["bilder"] = list(dict.fromkeys(fotos))[:30]


def detail(listing_id):
    global _alles_gelesen
    if listing_id not in _cache and not _alles_gelesen:  # Einzelaufruf (Nest-Prüfung): alle Projekte einmal lesen
        _alles_gelesen = True
        for p in _projekte():
            try:
                for e in _einheiten(p):
                    _cache[e["id"]] = e
            except Exception:
                continue
    e = _cache.get(listing_id)
    if not e:
        return None
    d = dict(e["_detail"])
    try:
        _einheit_seite(e, d)
    except Exception as ex:  # die Einheitenliste gilt auch ohne Zusatzseite
        print(f"Bauträger Einheit {e['url']}: {ex}", flush=True)
    return d


if __name__ == "__main__":  # python -m wohnungen.bautraeger tabelle URL: zeigt, was der Crawler auf einer Seite findet
    import sys
    for e in _einheiten({"schluessel": "test", "name": "Test", "plz": 0, "parser": sys.argv[1], "url_einheiten": sys.argv[2]}):
        print(e["titel"], e["preis"], e["flaeche"], e["url"])
