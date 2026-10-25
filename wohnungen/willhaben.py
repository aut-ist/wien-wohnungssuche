"""willhaben.at: Suche und Detailseiten über das eingebettete Next.js-JSON."""
import html as htmllib
import re

from .http import get, next_data

QUELLE = "willhaben"
PREFIX = "wh"
BASE = "https://www.willhaben.at/iad/"
BILD_BASE = "https://cache.willhaben.at/mmo/"
SLUGS = {
    1010: "wien-1010-innere-stadt",
    1020: "wien-1020-leopoldstadt",
    1080: "wien-1080-josefstadt",
    1090: "wien-1090-alsergrund",
    1180: "wien-1180-waehring",
    1190: "wien-1190-doebling",
}
ROWS = 90


def _attrs(obj):
    return {a["name"]: a["values"] for a in obj["attributes"]["attribute"] if a.get("values")}


def _first(attrs, name):
    v = attrs.get(name)
    return v[0] if v else None


def _num(s):
    if s in (None, ""):
        return None
    try:
        return float(str(s).replace(".", "").replace(",", ".")) if "," in str(s) else float(s)
    except ValueError:
        return None


def html_to_text(s):
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</ul>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def _lage_genauigkeit(q):
    q = _num(q) or 0
    if q >= 0.95:
        return "adresse"
    if q >= 0.7:
        return "strasse"
    return "bezirk"


def _coords(s):
    if not s or "," not in s:
        return None, None
    lat, lon = s.split(",")[:2]
    return round(float(lat), 6), round(float(lon), 6)


def _summary(ad, plz):
    a = _attrs(ad)
    lat, lon = _coords(_first(a, "COORDINATES"))
    mmo = _first(a, "MMO")
    zimmer = _num(_first(a, "NUMBER_OF_ROOMS"))
    seo = _first(a, "SEO_URL") or ""
    return {
        "id": f"wh-{ad['id']}",
        "quelle": "willhaben",
        "url": BASE + seo if str(ad["id"]) in seo else f"{BASE}object?adId={ad['id']}",
        # Sammelinserat eines Neubauprojekts; die einzelnen Wohnungen sind eigene Inserate
        "projekt": "/neubauprojekt/" in seo,
        "titel": ad.get("description") or _first(a, "HEADING"),
        "preis": _num(_first(a, "PRICE")),
        "flaeche": _num(_first(a, "ESTATE_SIZE/LIVING_AREA")) or _num(_first(a, "ESTATE_SIZE")),
        "zimmer": int(zimmer) if zimmer else None,
        "plz": int(_first(a, "POSTCODE") or plz),
        "adresse": _first(a, "ADDRESS"),
        "lat": lat,
        "lon": lon,
        "lage_genauigkeit": _lage_genauigkeit(_first(a, "LOCATION_QUALITY")),
        "bild": BILD_BASE + mmo if mmo else None,
        "bilder": [BILD_BASE + b for b in (_first(a, "ALL_IMAGE_URLS") or "").split(";") if b][:30],
        "freiflaeche": a.get("FREE_AREA_TYPE_NAME") or [],
        "veroeffentlicht": _first(a, "PUBLISHED_String"),
        "anbieter": _first(a, "ORGNAME") or ("privat" if _first(a, "ISPRIVATE") == "1" else None),
        "typ": _first(a, "PROPERTY_TYPE"),
    }


def search(plz):
    """Alle Eigentumswohnungen im Bezirk bis Preis-/Flächengrenze (Zimmer filtern wir selbst,
    damit Inserate ohne Zimmerangabe nicht verloren gehen)."""
    from .config import CONFIG
    f = CONFIG["filter"]
    page = 1
    while True:
        url = (f"{BASE}immobilien/eigentumswohnung/wien/{SLUGS[plz]}?rows={ROWS}&page={page}"
               f"&PRICE_TO={f['preis_max']}&ESTATE_SIZE/LIVING_AREA_FROM={f['flaeche_min']}")
        data = next_data(get(url))
        sr = data["props"]["pageProps"]["searchResult"]
        ads = sr["advertSummaryList"]["advertSummary"]
        for ad in ads:
            yield _summary(ad, plz)
        if len(ads) < ROWS or page * ROWS >= sr["rowsFound"]:
            break
        page += 1


def detail(listing_id):
    """Volltext, Heizung, Energieausweis und genaue Adresse eines Inserats."""
    ad_id = listing_id.removeprefix("wh-")
    page = get(f"{BASE}object?adId={ad_id}")
    data = next_data(page) if page else None
    ad = (data or {}).get("props", {}).get("pageProps", {}).get("advertDetails")
    if not ad:
        return None
    a = _attrs(ad)
    teile = []
    for name, werte in a.items():
        if name == "DESCRIPTION" or name.startswith("GENERAL_TEXT_ADVERT/"):
            titel = name.split("/", 1)[1] if "/" in name else "Beschreibung"
            teile.append(f"## {titel}\n{html_to_text(werte[0])}")
    text = "\n\n".join(teile)
    heiz = [w for w in re.findall(r"- ([^\n]+)", text) if re.search(r"(?i)heiz|wärme|therme|energieträger", w)]
    if _first(a, "HEATING"):
        heiz.insert(0, f"Heizung: {_first(a, 'HEATING')}")
    lat, lon = _coords(_first(a, "COORDINATES"))
    bilder = [img.get("referenceImageUrl") or img.get("mainImageUrl")
              for img in (ad.get("advertImageList") or {}).get("advertImage", [])][:30]
    zimmer = _num(_first(a, "NO_OF_ROOMS"))
    return {
        "text": text,
        "heizung_felder": list(dict.fromkeys(heiz)),
        "energie": {k: _first(a, f"ENERGY_{k.upper()}") for k in ("hwb", "hwb_class", "fgee", "fgee_class")},
        "baujahr": _first(a, "CONSTRUCTION_YEAR"),
        "bauart": _first(a, "BUILDING_TYPE"),
        "zustand": _first(a, "BUILDING_CONDITION"),
        "stockwerk": _first(a, "FLOOR"),
        "monatlich": _num(_first(a, "ESTATE_PRICE/MONTHCOSTS_GROSS")),
        "adresse": _first(a, "LOCATION/ADDRESS_1"),
        "lat": lat,
        "lon": lon,
        "flaeche": _num(_first(a, "ESTATE_SIZE/LIVING_AREA")) or _num(_first(a, "ESTATE_SIZE/USEABLE_AREA")),
        "zimmer": int(zimmer) if zimmer else None,
        "preis": _num(_first(a, "PRICE")),
        "bilder": [b for b in bilder if b],
    }
