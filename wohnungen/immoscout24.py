"""immobilienscout24.at: Suche und Exposés über das eingebettete Redux-/Apollo-JSON.

Suche: https://www.immobilienscout24.at/regional/wien/wien/<bezirk>/wohnung-kaufen[/seite-N]
       ?primaryPriceFrom=..&primaryPriceTo=..&primaryAreaFrom=..&primaryAreaTo=..
       -> window.__INITIAL_STATE__.reduxAsyncConnect.pageData.results.{totalHits,hits}
Detail: https://www.immobilienscout24.at/expose/<exposeId>
       -> window.__APOLLO_STATE__ (Expose:<id>)

Quirk der Suche: Der Server liefert pro Seite nur 15 Treffer, rechnet die Seitenzahl aber mit 25
(totalHits/25). Mehrere Seiten verlieren so ~40 % der Treffer. Deshalb wird der Preisbereich
adaptiv in Intervalle zerlegt, bis eine einzige Seite alle Treffer des Intervalls enthält
(len(hits) >= totalHits); die Ergebnisse werden per exposeId zusammengeführt.
"""
import html as htmllib
import re

from .http import get, numid

BASE = "https://www.immobilienscout24.at"
SLUGS = {
    1010: "1-bezirk-innere-stadt",
    1020: "2-bezirk-leopoldstadt",
    1080: "8-bezirk-josefstadt",
    1090: "9-bezirk-alsergrund",
    1180: "18-bezirk-waehring",
    1190: "19-bezirk-doebling",
}
QUELLE = "ImmoScout24"
PREFIX = "is"
MAX_REQUESTS = 70          # Obergrenze Suchseiten pro Bezirk (Normalfall 30-50)
MAX_PAGES_FALLBACK = 3     # wenn ein Intervall nicht weiter teilbar ist
PIC = "https://pictures.immobilienscout24.de/prod.www.immobilienscout24.at/pictureserver/loadPicture?q=70&id="

# numerische Pipeline-ID -> exposeId (Exposé-IDs sind 24-stellige Hex-Strings, passen nicht in 15 Ziffern).
# detail() wird von run.py im selben Prozess nach search() aufgerufen.
_IDS = {}


# ---------------------------------------------------------------- Hilfsfunktionen
def _json_after(page, marker):
    """JSON-Objekt nach `marker` im HTML (JS-Literal mit `undefined`)."""
    import json
    i = page.find(marker)
    if i < 0:
        return None
    t = re.sub(r":undefined\b", ":null", page[i + len(marker):])
    try:
        return json.JSONDecoder().raw_decode(t.lstrip())[0]
    except ValueError:
        return None


def _state(page):
    return _json_after(page, "window.__INITIAL_STATE__=") if page else None


def html_to_text(s):
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</ul>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _num(s):
    if s in (None, ""):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = re.sub(r"[^\d,.\-]", "", str(s))
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _pid(expose_id):
    n = numid(expose_id)
    _IDS[n] = expose_id
    return f"{PREFIX}-{n}"


def _pic(src):
    """Thumbnail-/CDN-URL -> Original (pictureserver) anhand der Bild-ID am Ende."""
    if not src:
        return None
    if "/dims3/" in src and "/prod.www.immobilienscout24.at/" in src:
        return PIC + src.rsplit("/", 1)[-1].split("?")[0]
    return src


def _slug(plz):
    plz = int(plz)
    if plz in SLUGS:
        return SLUGS[plz]
    raise KeyError(f"ImmoScout24: kein Bezirks-Slug für {plz}")


# ---------------------------------------------------------------- Suche
def _address_parts(addr, plz):
    """addressString ('Rögergasse 14B, 1090 Wien', 'Nordbergstraße, 1090 Wien', '1090 Wien')
    -> (strasse_mit_nr oder None, plz)"""
    addr = (addr or "").strip()
    m = re.search(r"\b(1\d{3})\b", addr)
    zip_ = int(m.group(1)) if m else plz
    first = addr.split(",")[0].strip()
    if not first or re.match(r"^1\d{3}\b", first):
        return None, zip_
    return first, zip_


def _summary(h, plz):
    exid = h["exposeId"]
    adr, zip_ = _address_parts(h.get("addressString"), plz)
    loc = h.get("location") or {}
    ltype = loc.get("type")
    lat, lon = loc.get("lat"), loc.get("lon")
    if ltype == "POINT" and lat and adr:
        genau, lat, lon = ("adresse" if re.search(r"\d", adr) else "strasse"), round(lat, 6), round(lon, 6)
    elif lat and lon:            # CIRCLE: absichtlich versetzter Mittelpunkt, Radius 250-420 m
        genau, lat, lon = "bezirk", round(lat, 6), round(lon, 6)
    else:                        # SHAPE_ID: nur Straßenname, keine Koordinaten -> Pipeline geokodiert
        genau, lat, lon = ("strasse" if adr else "bezirk"), None, None

    meta = h.get("meta") or {}
    preis = h.get("primaryPrice") or None
    projekt = bool(meta.get("hasChildren")) or (str(h.get("displayType", "")).startswith("DEVELOPER") and not preis)
    zimmer = h.get("numberOfRooms")

    bilder = []
    for p in [h.get("primaryPictureImageProps")] + list(h.get("thumbnailPicturesImageProps") or []):
        u = _pic((p or {}).get("src"))
        if u and u not in bilder:
            bilder.append(u)

    badges = {(b.get("details") or {}).get("value") for b in h.get("typedBadges") or []}
    frei = [n for k, n in (("BALCONY", "Balkon"), ("TERRACE", "Terrasse"), ("LOGGIA", "Loggia"),
                           ("GARDEN", "Garten")) if k in badges]
    rc = h.get("realtorContact") or {}
    return {
        "id": _pid(exid),
        "quelle": QUELLE,
        "url": (h.get("links") or {}).get("absoluteURL") or f"{BASE}/expose/{exid}",
        "projekt": projekt,
        "titel": h.get("headline"),
        "preis": float(preis) if preis else None,
        "flaeche": float(h["primaryArea"]) if h.get("primaryArea") else None,
        "zimmer": int(zimmer) if zimmer else None,
        "plz": zip_,
        "adresse": adr,
        "lat": lat,
        "lon": lon,
        "lage_genauigkeit": genau,
        "bild": bilder[0] if bilder else None,
        "bilder": bilder[:30],
        "freiflaeche": frei,
        "veroeffentlicht": (h.get("dateCreated") or "")[:10] or None,
        "anbieter": "privat" if h.get("isPrivate") else (rc.get("company") or rc.get("name")),
        "typ": None,
    }


def _fetch(slug, pmin, pmax, amin, amax, page=1):
    url = f"{BASE}/regional/wien/wien/{slug}/wohnung-kaufen" + ("" if page == 1 else f"/seite-{page}")
    q = [f"primaryPriceFrom={pmin}", f"primaryPriceTo={pmax}", f"primaryAreaFrom={amin}"]
    if amax:
        q.append(f"primaryAreaTo={amax}")
    st = _state(get(url + "?" + "&".join(q)))
    if not st:
        return 0, [], 1
    r = st["reduxAsyncConnect"]["pageData"]["results"]
    return int(r.get("totalHits") or 0), r.get("hits") or [], int((r.get("pagination") or {}).get("totalPages") or 1)


def _quantile_cuts(values, k, lo, hi):
    """Teilpunkte b mit lo <= b < hi aus der Stichprobe (Quantile), aufsteigend und eindeutig."""
    vals = sorted(values)
    cuts = []
    for i in range(1, k):
        b = vals[min(len(vals) - 1, i * len(vals) // k)]
        if lo <= b < hi and (not cuts or b > cuts[-1]):
            cuts.append(b)
    if not cuts:                 # alle Werte am oberen Rand: größten Wert unter hi nehmen
        below = [v for v in vals if lo <= v < hi]
        if below:
            cuts = [below[len(below) // 2]]
    return cuts


def search(plz):
    """Eigentumswohnungen (Kauf) in Wien <plz>, Preis ≤ preis_max, Fläche ≥ flaeche_min."""
    from .config import CONFIG
    f = CONFIG["filter"]
    slug = _slug(plz)
    pmax_all, amin_all = int(f["preis_max"]), int(f["flaeche_min"])
    seen = set()
    budget = [MAX_REQUESTS]

    # Arbeitsliste von Intervallen: (preis_von, preis_bis, flaeche_von, flaeche_bis|None)
    todo = [(0, pmax_all, amin_all, None)]
    while todo:
        lo, hi, alo, ahi = todo.pop(0)
        if budget[0] <= 0:
            break
        budget[0] -= 1
        total, hits, _pages = _fetch(slug, lo, hi, alo, ahi)
        for h in hits:
            if h["exposeId"] not in seen:
                seen.add(h["exposeId"])
                yield _summary(h, plz)
        if total <= len(hits):                       # Seite 1 enthält alles
            continue

        k = max(2, min(8, -(-total // 12)))          # Ziel ~12 Treffer je Teilintervall
        prices = [h["primaryPrice"] for h in hits if h.get("primaryPrice")]
        cuts = _quantile_cuts(prices, k, lo, hi) if hi > lo and len(set(prices)) > 1 else []
        if cuts:
            edges = [lo - 1] + cuts + [hi]
            todo[:0] = [(a + 1, b, alo, ahi) for a, b in zip(edges, edges[1:])]
            continue

        # Preis nicht weiter teilbar (z. B. viele Einheiten zum selben Preis): nach Fläche teilen
        areas = [h["primaryArea"] for h in hits if h.get("primaryArea")]
        top = ahi if ahi else 10000
        cuts = [c for c in _quantile_cuts([int(a) for a in areas], k, alo, top) if alo < c < top]
        if cuts:
            edges = [alo] + cuts + [ahi]
            todo[:0] = [(lo, hi, a, b) for a, b in zip(edges, edges[1:])]
            continue

        # letzter Ausweg: weitere Seiten (liefern andere, aber unvollständige Treffer)
        for page in range(2, MAX_PAGES_FALLBACK + 1):
            if budget[0] <= 0:
                break
            budget[0] -= 1
            _t, more, _p = _fetch(slug, lo, hi, alo, ahi, page)
            if not more:
                break
            for h in more:
                if h["exposeId"] not in seen:
                    seen.add(h["exposeId"])
                    yield _summary(h, plz)


# ---------------------------------------------------------------- Detail
def _chars(ex):
    """characteristics -> {key: text}"""
    out = {}
    for c in ex.get("characteristics") or []:
        for it in c.get("items") or []:
            out.setdefault(it.get("key"), it.get("text"))
    return out


def _val(av):
    return (av or {}).get("value") if isinstance(av, dict) else None


def detail(listing_id):
    """Volltext, Heizung, Energieausweis, Fotos eines Exposés (None, wenn offline)."""
    exid = _IDS.get(listing_id.removeprefix(PREFIX + "-"))
    if not exid:
        return None              # nur nach search() im selben Prozess auflösbar
    page = get(f"{BASE}/expose/{exid}")
    if not page:
        return None
    ap = _json_after(page, "window.__APOLLO_STATE__=")
    ex = (ap or {}).get(f"Expose:{exid}")
    if not ex:
        return None

    d = ex.get("description") or {}
    teile = []
    for titel, key in (("Beschreibung", "descriptionNote"), ("Lage", "locationNote"),
                       ("Ausstattung", "fittingNote"), ("Sonstiges", "miscellaneousNote")):
        if d.get(key):
            teile.append(f"## {titel}\n{html_to_text(d[key])}")
    ch = _chars(ex)
    merkmale = [c_it.get("text") for c in ex.get("characteristics") or [] for c_it in c.get("items") or []
                if c_it.get("text")]
    if merkmale:
        teile.append("## Merkmale\n" + "\n".join("- " + m for m in merkmale))
    text = "\n\n".join(teile)

    cond = ex.get("condition") or {}
    heiz = [f"Heizung: {h['label']}" for h in cond.get("heatingTypes") or [] if h.get("label")]
    heiz += [f"Energieträger: {h['label']}" for h in cond.get("firingTypes") or [] if h.get("label")]
    fit = ex.get("fitting") or {}
    heiz += [f"Heizung: {h['label']}" for h in fit.get("heatingTypes") or [] if isinstance(h, dict) and h.get("label")]
    heiz += [w for w in re.findall(r"- ([^\n]+)", text)
             if re.search(r"(?i)heiz|wärme|therme|energieträger", w)]

    ec = cond.get("energyCertification") or {}
    energie = {
        "hwb": _num(_val(ec.get("heatingDemand"))),
        "hwb_class": _val(ec.get("heatingDemandClass")),
        "fgee": _num(_val(ec.get("totalEnergyEfficiencyFactor"))),
        "fgee_class": _val(ec.get("totalEnergyEfficiencyFactorClass")),
    }

    addr = (ex.get("localization") or {}).get("address") or {}
    strasse = " ".join(x for x in (addr.get("street"), addr.get("streetNumber")) if x) or None
    area = ex.get("area") or {}
    kf = ex.get("keyfacts") or {}
    fl = kf.get("floor")
    stock = (fl.get("label") if isinstance(fl, dict) else None) or kf.get("floorLabel")
    monatlich = None
    laufend = [_num(c.get("price")) for c in (ex.get("costs") or {}).get("running") or []]
    laufend = [x for x in laufend if x]
    if laufend:
        monatlich = round(sum(laufend), 2)
    bilder = [p["url"] for p in ex.get("pictures") or [] if p.get("url")][:30]
    frei = [{"BALCONY": "Balkon", "TERRACE": "Terrasse", "LOGGIA": "Loggia", "GARDEN": "Garten"}.get(o, o)
            for o in area.get("outdoorSpaces") or []]
    zimmer = area.get("numberOfRooms")
    flaeche = area.get("livingArea") or area.get("primaryArea") or area.get("totalArea")
    return {
        "text": text,
        "heizung_felder": list(dict.fromkeys(heiz)),
        "energie": energie,
        "baujahr": cond.get("yearOfConstruction"),
        "bauart": ch.get("age"),
        "zustand": ch.get("condition_type"),
        "stockwerk": stock,
        "monatlich": monatlich,
        "adresse": strasse,
        "lat": None,             # Exposé enthält keine Koordinaten (nur die Suche liefert sie)
        "lon": None,
        "flaeche": float(flaeche) if flaeche else None,
        "zimmer": int(zimmer) if zimmer else None,
        "preis": (ex.get("priceInformation") or {}).get("primaryPrice") or None,
        "bilder": bilder,
        "typ": ch.get("estate_detail_type"),
        "freiflaeche": frei,
    }
