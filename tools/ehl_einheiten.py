"""EHL-Wohnprojekte: Einheitenlisten mit einem echten Browser lesen -> data/ehl_einheiten.json (Wunsch 2026-11-09).

EHL ist der größte Anbieter in den gesuchten Bezirken, baut die Einheitenliste aber per JavaScript auf (kein Bot-Schutz,
die Seite braucht nur einen Browser). Darum öffnet dieses Skript die Projektliste und die Einheitenseiten wie ein Besucher
(Playwright, im Workflow vor dem Scrape); wohnungen/bautraeger.py macht daraus Inserate wie bei den anderen Bauträgern.
"""
import datetime as dt
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wohnungen.config import CONFIG, DATA, save_json  # noqa: E402
from wohnungen.geocode import geocode  # noqa: E402
from wohnungen.http import get  # noqa: E402
from wohnungen import bautraeger as b  # noqa: E402

BASIS = "https://www.ehl.at/wohnen/wohnprojekte"
ZIEL = DATA / "ehl_einheiten.json"
# Adressen, die nicht im Link stehen (aus den Projektseiten und Inseraten)
ADRESSEN = {"apostelhof": "Apostelgasse 25-27", "grace": "Hetzgasse 8", "semper47": "Semperstraße 47", "the-legacy": "Landstraßer Hauptstraße 144",
            "augasse-17": "Augasse 17", "josephine": "Stoffellagasse"}

ZEILEN = """() => {
  const aus = [], fertig = new Set();
  for (const a of document.querySelectorAll('a[href*="/objekt/"]')) {
    if (a.href.includes('#') || fertig.has(a.href)) continue;
    fertig.add(a.href);
    let z = a;
    while (z.parentElement && !z.innerText.includes('€')) z = z.parentElement;
    aus.push({href: a.href, text: z.innerText});
  }
  return aus;
}"""


def adresse_aus_slug(slug):
    kern = re.sub(r"-\d{4}-wien$", "", slug)
    if kern in ADRESSEN:
        return ADRESSEN[kern]
    m = re.search(r"((?:[a-z0-9]+-)*?[a-z]*(?:strasse|gasse|platz|weg|ring))-(\d+[a-z]?)$", kern)
    if not m:
        return None
    s = m.group(1)
    for a, c in (("strasse", "straße"), ("ae", "ä"), ("oe", "ö"), ("ue", "ü")):
        s = s.replace(a, c)
    # die Projektnamen stehen vorn im Link (sophie-nordbergstrasse-13, the-pearl-grosse-schiffgasse-9)
    for vorn in ("sophie-", "the-pearl-", "cloud-9-", "q-tower-", "leopoldquartier-living-", "laurenzi-am-fluss-"):
        s = s.removeprefix(vorn)
    s = re.sub(r"^village-im-dritten-bf\w+-", "", s)
    return "-".join(w.capitalize() for w in s.split("-")).replace("Grosse", "Große").replace("Obere-", "Obere ").replace("Große-", "Große ") + " " + m.group(2)


def einheit(text, href):
    """Text einer Zeile: Top, Stockwerk, Zimmer, Wohnfläche, Freifläche, Preis, 'Jetzt anfragen', Freiflächen im Detail."""
    z = [t.strip() for t in text.split("\n") if t.strip()]
    if "Jetzt anfragen" in z:
        kopf, rest = z[:z.index("Jetzt anfragen")], z[z.index("Jetzt anfragen"):]
    else:
        kopf, rest = z, []
    preis = next((t for t in reversed(kopf) if "€" in t), None)
    i = next((n for n, t in enumerate(kopf) if re.search(r"m2|m²", t)), 0)
    if i < 2 or not preis:  # vor der Wohnfläche stehen Stockwerk und Zimmer, davor je nach Projekt Top und Stiege
        return None
    w = {"top": kopf[0] if i >= 3 else "", "stiege": kopf[1] if i >= 4 else "", "geschoss": kopf[i - 2], "zimmer": kopf[i - 1],
         "flaeche": kopf[i], "eigennutzer": preis, "href": href}
    for t in rest:
        m = re.match(r"(Balkon|Terrassen|Loggia|Garten)fläche\s+([\d.,]+)", t)
        if m:
            w[{"Balkon": "balkon", "Terrassen": "terrasse", "Loggia": "loggia", "Garten": "garten"}[m.group(1)]] = m.group(2).replace(".", ",") + " m²"
    return w


def main():
    from playwright.sync_api import sync_playwright
    plz = CONFIG["bezirke"]["ganz"] + CONFIG["bezirke"]["mit_zonen"]
    seite = get(BASIS) or ""
    slugs = sorted(s for s in set(re.findall(r"/wohnen/wohnprojekte/([a-z0-9-]+)", seite))
                   if (m := re.search(r"-(\d{4})-wien$", s)) and int(m.group(1)) in plz)
    print(len(slugs), "EHL-Projekte in den gesuchten Bezirken", flush=True)
    aus = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        tab = browser.new_page(locale="de-AT")
        for slug in slugs:
            url = f"{BASIS}/{slug}"
            try:
                html = get(url, retries=2) or ""
                m = re.search(r"2020-ehl-projectfilter/\?project=(\d+)", html)
                if not m:
                    print(slug, "ohne Einheitenliste", flush=True)
                    continue
                tab.goto(f"https://www.ehl.at/2020-ehl-projectfilter/?project={m.group(1)}", wait_until="networkidle", timeout=45000)
                try:
                    tab.wait_for_selector('a[href*="/objekt/"]', timeout=12000)
                except Exception:
                    pass
                einheiten = [w for z in tab.evaluate(ZEILEN) if (w := einheit(z["text"], z["href"]))]
                name = (tab.title().split("|")[0] or slug).strip()
                adresse = adresse_aus_slug(slug)
                nr = int(re.search(r"-(\d{4})-wien$", slug).group(1))
                eintrag = {"schluessel": "ehl-" + slug, "name": name, "bautraeger": "EHL Wohnen", "plz": nr, "adresse": adresse,
                           "url_projekt": url, "url_einheiten": url, "parser": "datei", "text": b._beschreibung(html), "galerie": b._galerie(html, url), "einheiten": einheiten}
                if adresse and (pos := geocode(f"{adresse}, {nr} Wien")):
                    eintrag["lat"], eintrag["lon"] = pos
                aus.append(eintrag)
                print(slug, "|", name, "|", adresse, "|", len(einheiten), "Einheiten", flush=True)
            except Exception as e:  # ein Projekt soll die anderen nicht stoppen
                print(slug, "Fehler:", e, flush=True)
            time.sleep(1.5)
        browser.close()
    if not aus:
        sys.exit("keine EHL-Projekte gelesen, alte Datei bleibt")
    save_json(ZIEL, {"stand": dt.date.today().isoformat(), "projekte": aus})
    print("gespeichert:", len(aus), "Projekte,", sum(len(p["einheiten"]) for p in aus), "Einheiten", flush=True)


if __name__ == "__main__":
    main()
