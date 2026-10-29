"""derStandard Immobilien: Suche und Detailseiten über die eingebetteten Next.js-Flight-Daten
(self.__next_f.push) der Seiten https://immobilien.derstandard.at/suche/... und /detail/<id>.

Besonderheiten: Das Portal liefert keine Koordinaten. Es gibt nur ein Freitextfeld "street"
(oft leer, manchmal nur Gegend/U-Bahn wie "Kreuzgasse, AKH, U6"). Die Pipeline geocodiert daraus."""
import html as htmllib
import json
import re

from .http import get

BASE = "https://immobilien.derstandard.at"
SLUGS = {
    1010: "wien-innere-stadt",
    1020: "wien-leopoldstadt",
    1080: "wien-josefstadt",
    1090: "wien-alsergrund",
    1180: "wien-waehring",
    1190: "wien-doebling",
}
QUELLE = "derStandard"
PREFIX = "ds"
MAX_SEITEN = 20

FREIFLAECHEN = {"BALCONY": "Balkon", "TERRACE": "Terrasse", "GARDEN": "Garten",
                "LOGGIA": "Loggia", "WINTER_GARDEN": "Wintergarten"}
HEIZUNGSART = {"NO_HEATING": "keine Heizung", "OVEN": "Ofen", "CENTRAL_HEATING": "Zentralheizung",
               "FLOOR_HEATING": "Etagenheizung", "UNDERFLOOR_HEATING": "Fußbodenheizung",
               "DISTRICT_HEATING": "Fernwärme"}
ENERGIETRAEGER = {"OIL": "Öl", "GAS": "Gas", "ELECTRIC": "Elektrisch", "ALTERNATIVE": "Alternativ",
                  "SOLAR": "Solar", "GEOTHERMAL": "Erdwärme", "HEAT_PUMP": "Wärmepumpe",
                  "HEAT_AND_POWER_PLANT": "Blockheizkraftwerk", "PELLETS": "Pellets"}
BAUART = {"NEW_BUILDING": "Neubau", "OLD_BUILDING": "Altbau", "NEW_BUILD_PROJECT": "Neubauprojekt"}
ZUSTAND = {"FIRST_TIME_USE": "Erstbezug", "NEEDS_RENOVATION": "Sanierungsbedürftig",
           "REQUIRES_REFURBISHMENT": "Sanierungsbedürftig"}
_PUSH = re.compile(r'self\.__next_f\.push\(\[\d+,(".*?")\]\)</script>', re.S)


def _flight(page):
    """Alle Next.js-Flight-Chunks einer Seite zu einem String zusammengesetzt."""
    teile = []
    for m in _PUSH.finditer(page or ""):
        try:
            teile.append(json.loads(m.group(1)))
        except ValueError:
            pass
    return "".join(teile)


def _objekt(flight, marker):
    """Das erste JSON-Objekt, das mit marker beginnt."""
    i = flight.find(marker)
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(flight[i:])[0]
    except ValueError:
        return None


def _ref_text(flight, ref):
    """Löst eine Referenz wie "$5f" auf einen Textchunk ("5f:T<hexlänge>,<text>") auf."""
    m = re.search(r"(?:^|\n)%s:T([0-9a-f]+)," % re.escape(ref.lstrip("$")), flight)
    if not m:
        return None
    n = int(m.group(1), 16)  # Länge in UTF-8-Bytes
    return flight[m.end():m.end() + n].encode("utf-8")[:n].decode("utf-8", errors="replace")


def html_to_text(s):
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</ul>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def _cost(prop, kind):
    for c in (prop.get("costs") or {}).get("details") or []:
        if c.get("kind") == kind:
            return c.get("gross") if c.get("gross") is not None else c.get("net")
    return None


def _area(prop, kind):
    for a in (prop.get("areas") or {}).get("details") or []:
        if a.get("kind") == kind:
            return a.get("value")
    return None


def _flaeche(prop):
    v = _area(prop, "LIVING_SPACE")
    if v is None:
        m = (prop.get("areas") or {}).get("main") or {}
        v = m.get("value") if m.get("kind") in ("LIVING_SPACE", "USABLE_AREA") else _area(prop, "USABLE_AREA")
    return float(v) if v is not None else None


def _preis(prop):
    v = ((prop.get("costs") or {}).get("main") or {}).get("value")
    if v is None:
        v = _cost(prop, "PURCHASE_PRICE")
    return float(v) if v is not None else None


def _strasse(loc):
    s = (loc.get("street") or "").strip()
    if not s or re.search(r"(?i)^wien\b|bezirk", s):
        return None
    return s


def _genauigkeit(adresse):
    """Ohne Koordinaten: nur die Qualität der Straßenangabe. Hausnummer -> adresse."""
    if not adresse:
        return "bezirk"
    if re.search(r"[A-Za-zÄÖÜäöüß]{4,}\.?\s*\d+[a-zA-Z]?\b", adresse):
        return "adresse"
    if re.search(r"(?i)stra(ß|ss)e|gasse|platz|weg|allee|gürtel|ring|markt|lände|steig|zeile|promenade|kai|damm|brücke|hof", adresse):
        return "strasse"
    return "bezirk"  # nur Gegend/Sehenswürdigkeit/U-Bahn ("AKH", "Türkenschanzpark")


def _coords(loc):
    c = loc.get("coordinates")
    if isinstance(c, dict):
        lat = c.get("lat") or c.get("latitude")
        lon = c.get("lon") or c.get("lng") or c.get("longitude")
        if lat and lon:
            return round(float(lat), 6), round(float(lon), 6)
    return None, None


def _typ(titel):
    t = (titel or "").lower()
    for key, name in (("penthouse", "Penthouse"), ("maisonette", "Maisonette"),
                      ("dachgeschoss", "Dachgeschoßwohnung"), ("dachgeschoß", "Dachgeschoßwohnung"),
                      ("dg-", "Dachgeschoßwohnung"), ("gartenwohnung", "Gartenwohnung"),
                      ("altbau", "Altbauwohnung")):
        if key in t:
            return name
    return None


def _anbieter(e, entries):
    """Der Anbieter ist bei mehreren Inseraten derselben Firma nur als Referenz
    ("$36:...:entries:1:advertiser") auf den Eintrag mit dem ersten Vorkommen angegeben."""
    a = e.get("advertiser")
    if isinstance(a, str):
        m = re.search(r"entries:(\d+):advertiser", a)
        a = entries[int(m.group(1))].get("advertiser") if m and int(m.group(1)) < len(entries) else None
    if not isinstance(a, dict):
        return None
    return ((a.get("company") or {}).get("name")) or None


def _summary(e, plz, entries=()):
    p = e.get("property") or {}
    loc = p.get("location") or {}
    zimmer = _area(p, "ROOM_COUNT")
    bilder = [i["path"] for i in (e.get("media") or {}).get("images") or [] if i.get("path")][:30]
    adr = _strasse(loc)
    lat, lon = _coords(loc)
    pub = ((e.get("metaData") or {}).get("publishedAt") or "")[:10] or None
    firma = _anbieter(e, entries)
    return {
        "id": f"{PREFIX}-{e['id']}",
        "quelle": QUELLE,
        "url": f"{BASE}/detail/{e['id']}",
        "projekt": False,  # Neubauprojekte erscheinen als einzelne Wohnungen, nicht als Sammelinserat
        "titel": e.get("title"),
        "preis": _preis(p),
        "flaeche": _flaeche(p),
        "zimmer": int(zimmer) if zimmer else None,
        "plz": int(loc.get("zipCode") or plz),
        "adresse": adr,
        "lat": lat,
        "lon": lon,
        "lage_genauigkeit": "bezirk" if lat and not adr else _genauigkeit(adr),
        "bild": bilder[0] if bilder else None,
        "bilder": bilder,
        "freiflaeche": [FREIFLAECHEN[a] for a in p.get("amenities") or [] if a in FREIFLAECHEN],
        "veroeffentlicht": pub,
        "anbieter": firma,
        "typ": _typ(e.get("title")),
    }


def _get(url):
    """derStandard bremst Server-Adressen (GitHub Actions) mit 403: langsam abfragen; nach
    wiederholter Sperre überspringt http.get das Portal für den Rest des Laufs (keine Umgehung).
    Früher wurde nach jedem 403 2,5 min gewartet, das sprengte am 2026-10-29 den Lauf."""
    return get(url, pause=(7.0, 11.0))


def search(plz):
    """Eigentumswohnungen im Bezirk mit Preis-/Flächenfilter des Portals (16 Treffer pro Seite)."""
    from .config import CONFIG
    f = CONFIG["filter"]
    gesehen = set()
    for seite in range(1, MAX_SEITEN + 1):
        url = (f"{BASE}/suche/{SLUGS[plz]}/kaufen-wohnung?priceTo={int(f['preis_max'])}"
               f"&areaFrom={int(f['flaeche_min'])}&page={seite}")
        page = _get(url)
        if not page:  # hinter der letzten Seite antwortet das Portal mit 404
            break
        res = _objekt(_flight(page), '{"__typename":"PaginatedPropertyEntriesResponse"')
        entries = (res or {}).get("entries") or []
        if not entries:
            break
        neu = 0
        for e in entries:
            if e["id"] in gesehen:  # hervorgehobene Inserate stehen auf mehreren Seiten
                continue
            gesehen.add(e["id"])
            if (e.get("availability") or {}).get("tenureOption", "BUY") != "BUY":
                continue
            neu += 1
            yield _summary(e, plz, entries)
        if len(gesehen) >= res.get("totalEntries", 0) or not neu and seite > 1:
            break


def detail(listing_id):
    """Volltext, Heizung, Energieausweis und Adresse eines Inserats."""
    ad_id = listing_id.removeprefix(PREFIX + "-")
    page = _get(f"{BASE}/detail/{ad_id}")
    if not page:
        return None
    flight = _flight(page)
    e = _objekt(flight, '{"__typename":"PropertyEntryResponse"')
    if not e or e.get("expired"):
        return None
    p = e.get("property") or {}
    loc = p.get("location") or {}
    energie = p.get("energyConsumption") or {}
    cond = p.get("condition") or {}

    ld = {}
    m = re.search(r'<script id="realEstateListingJsonLd" type="application/ld\+json">(.*?)</script>', page, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
        except ValueError:
            pass
    beschr = (ld.get("description") or "").strip()
    if not beschr and isinstance(e.get("description"), str):
        d = e["description"]
        beschr = html_to_text(_ref_text(flight, d) or "") if d.startswith("$") else html_to_text(d)
    ausst = [f["name"] for f in (ld.get("mainEntity") or {}).get("amenityFeature") or []
             if f.get("name") and f.get("value")]
    teile = []
    if beschr:
        teile.append("## Beschreibung\n" + beschr)
    if ausst:
        teile.append("## Ausstattung\n" + "\n".join("- " + a for a in ausst))
    text = "\n\n".join(teile)

    heiz = []
    for t in energie.get("heatingTypes") or []:
        heiz.append(f"Heizungsart: {HEIZUNGSART.get(t, t)}")
    for t in energie.get("fuelTypes") or []:
        heiz.append(f"Energieträger: {ENERGIETRAEGER.get(t, t)}")
    heiz += [w.strip() for w in re.findall(r"[^\n]*(?i:heiz|fernwärme|therme|energieträger|wärmepumpe)[^\n]*", beschr)
             if len(w.strip()) < 200]

    def cv(key):
        return energie.get(key) or {}

    lat, lon = _coords(loc)
    zimmer = _area(p, "ROOM_COUNT")
    bilder = [i["path"] for i in (e.get("media") or {}).get("images") or [] if i.get("path")][:30]
    adr = _strasse(loc)
    return {
        "text": text,
        "heizung_felder": list(dict.fromkeys(heiz)),
        "energie": {"hwb": cv("hwb").get("value"), "hwb_class": cv("hwb").get("class"),
                    "fgee": cv("fgee").get("value"), "fgee_class": cv("fgee").get("class")},
        "baujahr": cond.get("yearOfConstruction"),
        "bauart": BAUART.get(cond.get("buildingType")),
        "zustand": ZUSTAND.get(cond.get("status")) or (cond.get("status") or "").replace("_", " ").capitalize() or None,
        "stockwerk": None,
        "monatlich": _cost(p, "MONTHLY_COSTS"),
        "adresse": adr,
        "lat": lat,
        "lon": lon,
        "flaeche": _flaeche(p),
        "zimmer": int(zimmer) if zimmer else None,
        "preis": _preis(p),
        "bilder": bilder,
    }
