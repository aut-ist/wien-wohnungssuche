"""raiffeisen-immobilien.at: Eigentumswohnungen (Kauf) in Wien.

Die Ergebnisliste ist serverseitig gerendert (/de/immobilien?sales_type=buy&category[]=flat&zip[]=PLZ).
Raiffeisen hat in den Zielbezirken nur wenige Objekte; deshalb ohne Preis-/Flächenfilter abfragen,
damit Projekte (Preis "auf Anfrage", Flächenspanne) nicht herausfallen – die Pipeline filtert selbst.
Detailseiten haben weder Koordinaten noch eine strukturierte Adresse; die Straße steht (meist)
in der ersten Beschreibungszeile ("1090 Wien – Nußdorfer Straße") und wird daraus gelesen.
"""
import html as htmllib
import json
import re
import urllib.parse

from .http import get

QUELLE = "Raiffeisen Immobilien"
PREFIX = "ri"

BASE = "https://www.raiffeisen-immobilien.at"
GEOCODE = True  # gefundene Straße über Nominatim -> Koordinaten
# Testobjekt, das auf jeder Ergebnisseite als Banner erscheint
IGNORIERT = ("10009999999",)


def _txt(s):
    s = re.sub(r"(?i)<br\s*/?>", " ", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s).replace("\xa0", " ")).strip()


def _num(s):
    if s is None:
        return None
    m = re.search(r"\d[\d.]*(?:,\d+)?", str(s))
    if not m:
        return None
    t = m.group(0)
    try:
        if "," in t:
            return float(t.replace(".", "").replace(",", "."))
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
            return float(t.replace(".", ""))
        return float(t)
    except ValueError:
        return None


FREI_WORTE = {"Balkon": "Balkon", "Terrasse": "Terrasse", "Loggia": "Loggia", "Garten": "Garten",
              "Dachterrasse": "Terrasse"}


def _cards(page):
    out = []
    for blk in re.split(r'(?=<div class=" bg-white flex flex-col)', page)[1:]:
        m = re.search(r'href="/de/immobilien/kauf/(\d{4})/[^/"]+/([^"?]*?)\.(\d+)(?:\?[^"]*)?"[^>]*title="([^"]*)"', blk)
        if not m or m.group(3) in IGNORIERT:
            continue
        blk = blk[:6000]
        h = re.search(r"<h4[^>]*>(.*?)</h4>", blk, re.S)
        img = re.search(r'<img[^>]*src="([^"]+)"', blk)
        tags = [_txt(t) for t in re.findall(r"<li[^>]*>(.*?)</li>", blk, re.S)]
        facts = {}
        for dt, dd in re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", blk, re.S):
            facts[_txt(dt)] = _txt(dd)
        fl = facts.get("Wohnfläche") or facts.get("Fläche")
        out.append({
            "nr": m.group(3), "plz": int(m.group(1)),
            "slug": m.group(2),
            "titel": _txt(h.group(1)) if h else htmllib.unescape(m.group(4)),
            "bild": htmllib.unescape(img.group(1)) if img else None,
            "tags": tags,
            "projekt": "Projekt" in tags,
            "preis": _num(facts.get("Kaufpreis")) if re.search(r"\d", facts.get("Kaufpreis", "")) else None,
            "flaeche": _num(fl) if fl and "-" not in fl else None,
            "zimmer": _num(facts.get("Zimmer")) if re.search(r"\d", facts.get("Zimmer", "")) else None,
        })
    return out


def search(plz):
    gesehen = set()
    for page_no in range(1, 6):
        qs = urllib.parse.urlencode({"sales_type": "buy", "category[]": "flat", "zip[]": plz})
        page = get(f"{BASE}/de/immobilien?{qs}" + (f"&page={page_no}" if page_no > 1 else ""))
        if not page:
            break
        neu = 0
        for c in _cards(page):
            if c["nr"] in gesehen or c["plz"] != plz:
                continue
            gesehen.add(c["nr"])
            neu += 1
            frei = [FREI_WORTE[t] for t in c["tags"] if t in FREI_WORTE]
            yield {
                "id": f"{PREFIX}-{c['nr']}",
                "quelle": QUELLE,
                "url": f"{BASE}/de/immobilien/kauf/{plz}/wien/{c['slug']}.{c['nr']}",
                "titel": c["titel"],
                "preis": c["preis"],
                "flaeche": c["flaeche"],
                "zimmer": int(c["zimmer"]) if c["zimmer"] else None,
                "plz": plz,
                "adresse": None,
                "lat": None,
                "lon": None,
                "lage_genauigkeit": "bezirk",
                "bild": c["bild"],
                "bilder": [c["bild"]] if c["bild"] else [],
                "veroeffentlicht": None,
                "anbieter": "Raiffeisen Immobilien",
                "typ": "Eigentumswohnung",
                "freiflaeche": list(dict.fromkeys(frei)),
                "projekt": c["projekt"],
            }
        if not neu or "rel=\"next\"" not in page and f"page={page_no + 1}" not in page:
            break


STRASSE = re.compile(
    r"\b(1\d{3})\s+Wien\s*[–\-,|:]\s*(?:[A-ZÄÖÜ][\wäöüß.]*\s*[–\-,|:]\s*)?"
    r"([A-ZÄÖÜ][\wäöüß.\- ]*?(?i:straße|strasse|gasse|platz|weg|allee|gürtel|ring|markt|lände|zeile|steig|berg|hof|promenade|brücke|kai)\b)"
    r"(?:\s+(\d+[a-z]?(?:\s*[-/]\s*\d+[a-z]?)?))?")


def _strasse(text):
    m = STRASSE.search(text[:1500])
    if not m:
        return None, None
    nr = m.group(3)
    return (m.group(2) + (" " + nr.split("-")[0].split("/")[0].strip() if nr else "")).strip(), bool(nr)


def detail(listing_id):
    nr = listing_id.removeprefix(PREFIX + "-")
    # /de/immobilien/<Nr> liefert (wie die Slug-URL) direkt die Detailseite
    page = get(f"{BASE}/de/immobilien/{nr}")
    if not page or "Ausstattung und Eigenschaften" not in page:
        return None
    ld = {}
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            x = json.loads(m.group(1), strict=False)
        except ValueError:
            continue
        if isinstance(x, dict) and x.get("datePublished"):
            ld = x
            break

    # Beschreibung
    m = re.search(r'<div class="col-span-8 break-normal prose prose-sm">(.*?)(?=<!-- Properties and Downloads|Ausstattung und Eigenschaften)', page, re.S)
    desc = m.group(1) if m else ""
    d = re.sub(r"(?i)<li[^>]*>", "\n- ", desc)
    d = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</ul>|</h\d>", "\n", d)
    d = re.sub(r"<[^>]+>", "", d)
    d = htmllib.unescape(d).replace("\xa0", " ")
    d = re.sub(r"[ \t]+", " ", d)
    d = re.sub(r"\n\s*\n+", "\n", d).strip()
    # Maklervertrag-Textbaustein (FAGG) abschneiden
    d = re.split(r"\n!? ?Wir möchten Sie informieren", d)[0].strip()

    # Eigenschaften
    eig = []
    for k, v in re.findall(r'<div class="break-words font-light">\s*([^<]*?)\s*</div>\s*<div class="break-words text-right">\s*([^<]*?)\s*</div>', page):
        eig.append((htmllib.unescape(k).strip(), htmllib.unescape(v).strip()))
    key = {}
    heiz = []
    for k, v in eig:
        key.setdefault(k, v)
        if re.search(r"(?i)heizung|befeuerung|energieträger|warmwasser", k) and v:
            heiz.append(f"{k}: {v}")
    heiz += [w.strip("-• ").strip() for w in re.findall(r"(?m)^[-•]?\s*([^\n]*(?:[Hh]eiz|[Ff]ernwärme|[Tt]herme|[Kk]aminofen|[Ww]ärmepumpe)[^\n]*)$", d) if len(w) < 160]

    # Energieausweis (Blocktext)
    plain = ""
    for m in re.finditer(r"Energieausweis", page):
        plain = _txt(page[m.start():m.start() + 12000])
        if "HWB" in plain[:600]:
            break
    en = {"hwb": None, "hwb_class": None, "fgee": None, "fgee_class": None}
    m = re.search(r"HWB-Wert\s*([\d.,]+)", plain)
    en["hwb"] = _num(m.group(1)) if m else None
    m = re.search(r"HWB Klasse\s*([A-G][+]*)", plain)
    en["hwb_class"] = m.group(1) if m else None
    m = re.search(r"fGEE Wert\s*([\d.,]+)", plain)
    en["fgee"] = _num(m.group(1)) if m else None
    m = re.search(r"fGEE Klasse\s*([A-G][+]*)", plain)
    en["fgee_class"] = m.group(1) if m else None

    ausst = [f"{k}: {v}" for k, v in eig if v]
    teile = []
    if d:
        teile.append("## Beschreibung\n" + d)
    if ausst:
        teile.append("## Ausstattung und Eigenschaften\n" + "\n".join("- " + a for a in ausst))

    bilder = []
    for u, h in re.findall(r'srcset="(https://www\.raiffeisen-immobilien\.at/realty-media/\d+/(\w+)\.\w+\?fit=max[^"]*)"', page):
        if h not in [x[0] for x in bilder]:
            bilder.append((h, htmllib.unescape(u)))
    bilder = [u for _, u in bilder]

    strasse, mit_nr = _strasse(d)
    lat = lon = None
    if GEOCODE and strasse:
        try:
            from .geocode import geocode
            plz = re.search(r'/kauf/(\d{4})/', page)
            pos = geocode(f"{strasse}, {plz.group(1) if plz else ''} Wien")
            if pos:
                lat, lon = pos
        except Exception:
            pass

    def feld(label):
        for k, v in eig:
            if k == label:
                return v
        return None

    kosten = None
    m = re.search(r"Monatliche Kosten\s*</[^>]+>\s*<[^>]+>\s*([^<]+)<", page)
    if m:
        kosten = _num(m.group(1))
    preis = None
    m = re.search(r"Kaufpreis\s*</[^>]+>\s*<[^>]+>\s*([\d.,]+)\s*€", page)
    if m:
        preis = _num(m.group(1))
    zimmer = _num(feld("Gesamtzimmeranzahl"))
    flaeche = _num(feld("Wohnfläche")) or _num(feld("Nutzfläche"))
    plz_m = re.search(r"/kauf/(\d{4})/", page)

    return {
        "text": "\n\n".join(teile),
        "heizung_felder": list(dict.fromkeys(heiz)),
        "energie": en,
        "baujahr": feld("Baujahr"),
        "bauart": feld("Bauart"),
        "zustand": feld("Zustand"),
        "stockwerk": feld("Stockwerk") or feld("Etage"),
        "monatlich": kosten,
        "adresse": strasse,
        "lat": lat,
        "lon": lon,
        "flaeche": flaeche,
        "zimmer": int(zimmer) if zimmer else None,
        "preis": preis,
        "bilder": bilder[:30],
        "veroeffentlicht": ld.get("datePublished"),
    }
