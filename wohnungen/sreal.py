"""sreal.at (s REAL, Erste Bank/Sparkassen): Eigentumswohnungen (Kauf) in Wien.

Suche: /de/immobilien-suche?f[buyingType]=buy&f[location_or_id][]=d_Wien 9., Alsergrund (Bezirksfilter;
die PLZ-Suche "c_1090 Wien" liefert nichts). Der Objektart-Filter wird nicht benutzt (Kombinationen
liefern 0 Treffer); Häuser/Grundstücke werden über den Titel aussortiert. s REAL hat in den
Zielbezirken nur wenige Inserate.
Detailseiten enthalten Koordinaten, aber mit Unschärfe-Kreis (radius ~250 m) -> lage "bezirk".
"""
import html as htmllib
import re
import urllib.parse

from .http import get

QUELLE = "s REAL"
PREFIX = "sr"

BASE = "https://www.sreal.at"
BEZIRKE = {
    1010: "Wien 1., Innere Stadt",
    1020: "Wien 2., Leopoldstadt",
    1080: "Wien 8., Josefstadt",
    1090: "Wien 9., Alsergrund",
    1180: "Wien 18., Währing",
    1190: "Wien 19., Döbling",
}
NICHT_WOHNUNG = re.compile(r"(?i)\b(haus|villa|grundst[üu]ck|baugrund|zinshaus|garage|stellplatz|büro|buero|geschäft|lokal)\b")
PROJEKT = re.compile(r"(?i)wohnungspaket|\b\d+\s*(?:wohnungen|einheiten)\b|projekt")


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


def _txt(s):
    s = re.sub(r"(?i)<br\s*/?>", " ", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s).replace("\xa0", " ")).strip()


def _lid(portal_id):
    """'960-75014' -> '0960075014' (reversibel, nur Ziffern)."""
    a, b = portal_id.split("-")
    return f"{int(a):04d}{int(b):06d}"


def _portal_id(lid):
    d = lid.removeprefix(PREFIX + "-")
    return f"{int(d[:4])}-{int(d[4:])}"


def search(plz):
    if plz not in BEZIRKE:
        return
    gesehen = set()
    for p in range(1, 6):
        prm = {"f[buyingType]": "buy", "f[location_or_id][]": ["d_" + BEZIRKE[plz]]}
        if p > 1:
            prm["p"] = p
        page = get(f"{BASE}/de/immobilien-suche?" + urllib.parse.urlencode(prm, doseq=True))
        if not page:
            break
        neu = 0
        for blk in re.split(r'(?=<div class="realty-item-container)', page)[1:]:
            m = re.search(r'href="/de/immobilie/(\d+-\d+)/([^"]*)"', blk)
            if not m or m.group(1) in gesehen:
                continue
            titel = re.search(r"<h3[^>]*>\s*<span>(.*?)</span>", blk, re.S)
            titel = _txt(titel.group(1)) if titel else None
            ort = re.search(r"<small>(\d{4}) Wien</small>", blk)
            if ort and int(ort.group(1)) != plz:
                continue
            gesehen.add(m.group(1))
            neu += 1
            if titel and NICHT_WOHNUNG.search(titel) and "wohnung" not in titel.lower():
                continue
            info = {}
            for v, l in re.findall(r"<strong>(.*?)</strong>\s*<br/>\s*<small>(.*?)</small>", blk, re.S):
                info[_txt(l)] = _txt(v)
            img = re.search(r'<img src="([^"]+)"', blk)
            bild = BASE + htmllib.unescape(img.group(1)) if img else None
            preis = _num(info.get("Kaufpreis")) if re.search(r"\d", info.get("Kaufpreis", "")) else None
            yield {
                "id": f"{PREFIX}-{_lid(m.group(1))}",
                "quelle": QUELLE,
                "url": f"{BASE}/de/immobilie/{m.group(1)}/{m.group(2)}",
                "titel": titel,
                "preis": preis,
                "flaeche": _num(info.get("Wohnfläche")),
                "zimmer": None,
                "plz": plz,
                "adresse": None,
                "lat": None,
                "lon": None,
                "lage_genauigkeit": "bezirk",
                "bild": bild,
                "bilder": [bild] if bild else [],
                "veroeffentlicht": None,
                "anbieter": "s REAL",
                "typ": "Wohnung",
                "freiflaeche": [],
                "projekt": bool(titel and PROJEKT.search(titel)),
            }
        if not neu or f"p={p + 1}" not in page.replace("%5D=", "]=").replace("&amp;", "&"):
            break


def detail(listing_id):
    pid = _portal_id(listing_id)
    page = get(f"{BASE}/de/immobilie/{pid}/x")
    if not page or "Objektbeschreibung" not in page:
        return None

    pairs = [(_txt(k), v) for k, v in re.findall(r'<span class="label">([^<]*)</span>\s*<span class="value">(.*?)</span>', page, re.S)]
    key = {}
    for k, v in pairs:
        key.setdefault(k, _txt(v))
    # Kopfzahlen stehen im Matomo-Datenblock: 'price': '1.699.000 €', 'area': '150', 'rooms': '3', 'subType': 'Wohnung'
    meta = {k: v for k, v in re.findall(r"'(\w+)':\s*'([^']*)'", page[page.find("'attributes'"):][:1500])} if "'attributes'" in page else {}
    meta = {k: htmllib.unescape(v.replace("\\/", "/")).replace(" ", " ") for k, v in meta.items()}
    preis = _num(meta.get("price")) if re.search(r"\d", meta.get("price", "")) else None

    # Ausstattungs-Häkchen (Fernwärme, Zentralheizung, ...)
    status = [_txt(x) for x in re.findall(r'eg_status[^>]*>\s*<div class="data-wrapper">\s*<span class="label">([^<]*)', page)]
    heiz = [f"Heizung: {s}" for s in status if re.search(r"(?i)heiz|fernwärme|therme|wärmepumpe|gas|pellets|öl|strom|kamin|ofen|solar", s)]
    for k in key:
        if re.search(r"(?i)energieträger|befeuerung|heizungsart", k):
            heiz.append(f"{k}: {key[k]}")

    m = re.search(r'<div class="realty-detail-description">(.*?)</div>\s*</div>', page, re.S)
    desc = m.group(1) if m else ""
    d = re.sub(r"(?i)<li[^>]*>", "\n- ", desc)
    d = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</ul>|</h\d>", "\n", d)
    d = re.sub(r"<[^>]+>", "", d)
    d = htmllib.unescape(d).replace("\xa0", " ")
    d = re.sub(r"[ \t]+", " ", d)
    d = re.sub(r"\n\s*\n+", "\n", d).strip()
    d = re.split(r"\nKauf und Finanzierung aus einer Hand", d)[0].strip()
    teile = []
    if d:
        teile.append("## Objektbeschreibung\n" + d)
    m = re.search(r"<h3[^>]*>\s*Lagebeschreibung\s*</h3>(.*?)(?=<h3|<div class=\"page-break)", page, re.S)
    if m:
        lage = _txt(re.sub(r"(?i)</p>|<br\s*/?>", "\n", m.group(1)))
        if len(lage) > 40:
            teile.append("## Lagebeschreibung\n" + lage)
    feat = [f"{k}: {v}" for k, v in key.items() if v]
    if status:
        feat.append("Ausstattung: " + ", ".join(status))
    if feat:
        teile.append("## Merkmale\n" + "\n".join("- " + f for f in feat))

    mm = re.search(r"var radius = (\d+);.*?var objectLocation = \{\s*lat:\s*([\d.]+),\s*lng:\s*([\d.]+)\s*\}", page, re.S)
    lat = lon = None
    if mm:
        lat, lon = round(float(mm.group(2)), 6), round(float(mm.group(3)), 6)

    bilder = []
    for u in re.findall(r'class="item"\s+data-original="([^"]+)"', page):
        u = BASE + htmllib.unescape(u)
        if u not in bilder:
            bilder.append(u)

    monatlich = None
    m = re.search(r"Monatliche Gesamtbelastung\s*([\d.,]+)", _txt(page[page.find("Monatliche Gesamtbelastung") - 200:][:600])) if "Monatliche Gesamtbelastung" in page else None
    if m:
        monatlich = _num(m.group(1))

    key.setdefault("Baujahr", meta.get("yearBuilt"))
    key.setdefault("Alter", meta.get("age"))
    hwb = _num(key.get("Heizwärmebedarf"))
    fgee = _num(key.get("fGEE"))
    zimmer = _num(key.get("Zimmer")) or _num(meta.get("rooms"))
    flaeche = _num(key.get("Wohnfläche")) or _num(meta.get("area"))
    if flaeche is None:
        m = re.search(r"Wohnfläche\s*([\d.,]+)\s*m", _txt(page))
        flaeche = _num(m.group(1)) if m else None
    return {
        "text": "\n\n".join(teile),
        "heizung_felder": list(dict.fromkeys(heiz)),
        "energie": {"hwb": hwb, "hwb_class": key.get("Heizwärmeklasse"),
                    "fgee": fgee, "fgee_class": key.get("fGEE Klasse")},
        "baujahr": key.get("Baujahr"),
        "bauart": key.get("Alter"),
        "zustand": key.get("Zustandsbewertung"),
        "stockwerk": key.get("Stockwerk") or key.get("Etage"),
        "monatlich": monatlich,
        "adresse": None,
        "lat": lat,
        "lon": lon,
        "flaeche": flaeche,
        "zimmer": int(zimmer) if zimmer else None,
        "preis": preis,
        "bilder": bilder[:30],
        "koordinaten_unscharf": bool(mm and int(mm.group(1)) > 0),
    }
