"""findmyhome.at: Eigentumswohnungen (Kauf) in Wien.

Die Suche läuft über das normale Suchformular (POST an search.redirect.php, danach
Weiterleitung auf eine GET-URL mit Bezirkscode, Preis- und Flächenfilter); weitere Seiten
sind normale Links (20 pro Seite). Die Seiten sind gemischt UTF-8 / Latin-1 codiert
(http.get würde Umlaute zerstören), deshalb eigenes Abrufen mit zeilenweiser Dekodierung.
Detailseiten haben keine Koordinaten, nur die Straße (ohne Hausnummer).
"""
import html as htmllib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import http

QUELLE = "FindMyHome"
PREFIX = "fm"

BASE = "https://www.findmyhome.at"
# Bezirkswerte des Suchformulars (bezirk[]), PLZ -> Wert
BEZIRK = {1010: 100, 1020: 101, 1080: 107, 1090: 108, 1180: 117, 1190: 118}
GEOCODE = True  # Straße (ohne Hausnummer) über Nominatim -> Koordinaten (lage = "strasse")


def _decode(b):
    out = []
    for line in b.split(b"\n"):
        try:
            out.append(line.decode("utf-8"))
        except UnicodeDecodeError:
            out.append(line.decode("cp1252", errors="replace"))
    return "\n".join(out)


def _fetch(url, data=None, retries=3):
    host = urllib.parse.urlsplit(url).netloc
    for attempt in range(retries):
        http._warten(host, (1.0, 2.0))
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": http.UA, "Accept-Language": "de-AT,de;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return _decode(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(5 * (attempt + 1))


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
        # "729.000,-" -> 729000 ; "47,82" -> 47.82 ; "2.5" (Zimmer) -> 2.5
        if "," in t:
            return float(t.replace(".", "").replace(",", "."))
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
            return float(t.replace(".", ""))
        return float(t)
    except ValueError:
        return None


FREI = ["Dachterrasse", "Terrasse", "Balkon", "Loggia", "Garten", "Eigengarten", "Wintergarten"]


def _frei(text):
    t = text.lower()
    out = []
    for w in ("Balkon", "Terrasse", "Loggia", "Garten"):
        if w.lower() in t:
            out.append(w)
    return out


def _cards(page):
    out = []
    parts = re.split(r"(?=<a href='/\d+[^']*' onclick='' class='btnImageErgebnisliste'>)", page)
    for p in parts[1:]:
        m = re.match(r"<a href='/(\d+)", p)
        if not m:
            continue
        p = p[:12000]
        title = re.search(r"class='btnHeadlineErgebnisliste'>(.*?)</a>", p, re.S)
        img = re.search(r"<img src='(https://media\.findmyhome\.at/[^']+)'", p)
        desc = re.search(r'<p class="immobilie_description[^>]*>(.*?)</p>', p, re.S)
        ort = re.search(r"Ort: (\d{4})</strong>\s*([^<]*)", p)
        preis = re.search(r"Kauf: </strong><br>\s*([^<]+)", p)
        fl = re.search(r"Fl&auml;che: </strong><br>\s*([^<]+)", p)
        zi = re.search(r"Zimmer: </strong><br>\s*([^<]+)", p)
        out.append({
            "nr": m.group(1),
            "titel": _txt(title.group(1)) if title else None,
            "bild": img.group(1) if img else None,
            "desc": _txt(desc.group(1)) if desc else "",
            "plz": int(ort.group(1)) if ort else None,
            "preis": _num(preis.group(1)) if preis and re.search(r"\d", preis.group(1)) else None,
            "flaeche": _num(htmllib.unescape(fl.group(1))) if fl else None,
            "zimmer": _num(zi.group(1)) if zi and re.search(r"\d", zi.group(1)) else None,
            "top": "TOP:" in p[:1500],
        })
    return out


def _pages(first_url, first_data=None):
    """Ergebnisseiten. Die Reihenfolge ohne Sortierung rotiert (TOP-Inserate), darum nach der ersten
    Seite mit fester Sortierung (Preis aufsteigend) neu blättern, damit nichts doppelt/gar nicht kommt."""
    page = _fetch(first_url, first_data)
    if not page:
        return
    link = re.search(r"href=\"(/index\.php\?[^\"]*entry=\d+[^\"]*)\"", page)
    if not link:
        yield page
        return
    tmpl = htmllib.unescape(link.group(1))
    tmpl = re.sub(r"entry=\d+", "entry={entry}", tmpl)
    tmpl = re.sub(r"sort=[^&]*", "sort=sort_pr", tmpl)
    tmpl = re.sub(r"dir=[^&]*", "dir=ASC", tmpl)
    for entry in range(0, 400, 20):
        page = _fetch(BASE + tmpl.format(entry=entry))
        if not page or not _cards(page):
            break
        yield page


def search(plz):
    if plz not in BEZIRK:
        return
    from .config import CONFIG
    f = CONFIG["filter"]
    form = [("id", "14"), ("lang", "de"), ("module", "select"), ("land", "AT"), ("bl", "9"),
            ("w_e", "1"), ("bezirk[]", str(BEZIRK[plz])), ("zimmer", "0"),
            ("prb", str(int(f["preis_max"]))), ("flv", str(int(f["flaeche_min"])))]
    gesehen = set()
    for page in _pages(BASE + "/search.redirect.php", urllib.parse.urlencode(form).encode()):
        for c in _cards(page):
            if c["nr"] in gesehen or c["plz"] != plz:
                continue
            gesehen.add(c["nr"])
            titel = c["titel"] or ""
            projekt = c["zimmer"] is None and bool(
                re.search(r"(?i)projekt|\b\d+\s*(?:wohnungen|einheiten)\b", titel + " " + c["desc"][:300]))
            bild = c["bild"]
            bild = re.sub(r"/s\d/", "/s1/", bild) if bild else None
            yield {
                "id": f"{PREFIX}-{c['nr']}",
                "quelle": QUELLE,
                "url": f"{BASE}/{c['nr']}",
                "titel": titel,
                "preis": c["preis"],
                "flaeche": c["flaeche"],
                "zimmer": int(c["zimmer"]) if c["zimmer"] else None,
                "plz": plz,
                "adresse": None,
                "lat": None,
                "lon": None,
                "lage_genauigkeit": "bezirk",
                "bild": bild,
                "bilder": [bild] if bild else [],
                "veroeffentlicht": None,
                "anbieter": None,
                "typ": "Eigentumswohnung",
                "freiflaeche": _frei(titel + " " + c["desc"]),
                "projekt": projekt,
            }


def _description(page):
    i = page.find('id="show_1_desc"')
    if i < 0:
        return ""
    blk = page[i:i + 60000]
    m = re.search(r"id='immoExpose'>(.*)", blk, re.S)
    blk = m.group(1) if m else blk
    # Ende der Beschreibung: Entfernungsliste (nur Luftlinien), Skripte oder nächster Seitenblock
    ende = [blk.find(x) for x in ("Infrastruktur / Entfernungen", "<script", '<div class="row', "<a id=\"moreExpose\"", "<!--")]
    ende = [e for e in ende if e > 0]
    if ende:
        blk = blk[:min(ende)]
    blk = re.sub(r"(?is)<h3[^>]*>(.*?)</h3>", lambda x: "", blk, count=1) if "<h3" in blk[:50] else blk
    blk = re.sub(r"(?i)<li[^>]*>", "\n- ", blk)
    blk = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</ul>|</h\d>", "\n", blk)
    blk = re.sub(r"<[^>]+>", "", blk)
    blk = htmllib.unescape(blk).replace("\xa0", " ")
    blk = re.sub(r"[ \t]+", " ", blk)
    blk = re.sub(r"\n\s*\n+", "\n", blk).strip()
    return blk


def detail(listing_id):
    nr = listing_id.removeprefix(PREFIX + "-")
    page = _fetch(f"{BASE}/{nr}")
    if not page or "Externe Immobilien-ID" not in page:
        return None
    rows = {}
    for k, v in re.findall(r'<tr><td[^>]*>(.*?)</td>(?:<a[^>]*></a>)?\s*<td[^>]*>(.*?)</td></tr>', page, re.S):
        rows.setdefault(_txt(k).rstrip(":"), v)

    heiz = []
    bef = rows.get("Befeuerung")
    if bef:
        arten = [_txt(b) for b in re.findall(r"<b>(.*?)</b>", bef, re.S)]
        for a in arten:
            if a:
                heiz.append(f"Befeuerung: {a}")

    # Energieausweis
    eb = re.search(r"id='energieausweis2'[^>]*>(.*?)</div>", page, re.S)
    en = {"hwb": None, "hwb_class": None, "fgee": None, "fgee_class": None}
    if eb:
        t = eb.group(1)
        m = re.search(r"Heizw(?:&auml;|ä)rmebedarf in kWh/m2/Jahr:\s*([\d.,]+)", t)
        en["hwb"] = _num(m.group(1)) if m else None
        m = re.search(r"Klasse f(?:&uuml;|ü)r Heizw(?:&auml;|ä)rmebdarf:\s*([A-G][+]*)", t)
        en["hwb_class"] = m.group(1) if m else None
        m = re.search(r"Gesamtenergieeffizienz-Faktor:\s*([\d.,]+)", t)
        en["fgee"] = _num(m.group(1)) if m else None
        m = re.search(r"Klasse f(?:&uuml;|ü)r Gesamtenergieeffizienz-Faktor:\s*([A-G][+]*)", t)
        en["fgee_class"] = m.group(1) if m else None

    text = _description(page)
    hz = [w for w in re.findall(r"(?m)^[-•]?\s*([^\n]*(?:[Hh]eiz|[Ff]ernwärme|[Tt]herme|[Ff]ußbodenheizung|[Ee]nergieträger|[Kk]aminofen)[^\n]*)$", text) if len(w) < 160]
    heiz += [h.strip("-?• ").strip() for h in hz]

    anschrift = rows.get("Anschrift")
    strasse = None
    if anschrift:
        first = re.split(r"(?i)<br\s*/?>", anschrift)[0]
        s = _txt(first)
        if s and not re.match(r"^\d{4}\b", s):
            strasse = s
    plz_m = re.search(r"(\d{4})\s*Wien", _txt(anschrift or ""))

    bilder = []
    for u in re.findall(r'data-src="(//media\.findmyhome\.at/[^"]+)"', page):
        u = "https:" + u
        if u not in bilder:
            bilder.append(u)

    anbieter = re.search(r"<b>([^<]+)</b><br />\s*[^<]*<br />\s*<div class=\"row margin-top-20\">", page)
    zimmer = _num(_txt(rows.get("Zimmer", "")))
    lat = lon = None
    if GEOCODE and strasse:
        try:
            from .geocode import geocode
            pos = geocode(f"{strasse}, {plz_m.group(1) if plz_m else ''} Wien".replace(" ,", ","))
            if pos:
                lat, lon = pos
        except Exception:
            pass
    return {
        "text": ("## Beschreibung\n" + text) if text else "",
        "heizung_felder": list(dict.fromkeys(heiz)),
        "energie": en,
        "baujahr": _txt(rows.get("Baujahr", "")) or None,
        "bauart": None,
        "zustand": None,
        "stockwerk": _txt(rows.get("Stock", "")) or None,
        "monatlich": None,
        "adresse": strasse,
        "lat": lat,
        "lon": lon,
        "flaeche": _num(_txt(rows.get("Fläche", ""))),
        "zimmer": int(zimmer) if zimmer else None,
        "preis": _num(_txt(rows.get("Kaufpreis", ""))),
        "bilder": bilder[:30],
        "anbieter": anbieter.group(1).strip() if anbieter else None,
        "immobilienart": _txt(rows.get("Immobilienart", "")) or None,
    }
