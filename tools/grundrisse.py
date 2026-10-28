"""Findet unter den Fotos einer Wohnung die Grundrisse (überwiegend weiß, kaum Farbe) und speichert
sie gut lesbar ab – dort steht oft ein Schriftfeld mit Projekt und Adresse. Für die Nest-Recherche.

    python tools/grundrisse.py WOHNUNGS-ID [ZIELORDNER]
    python tools/grundrisse.py --recherche    für alle in data/recherche.json nach data/grundrisse/ID/
                                              (alte Ordner werden entfernt; läuft im täglichen Workflow)
"""
import io
import json
import shutil
import sys
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"}


def bewerten(img):
    """Anteil fast weißer, farbloser Pixel (Grundrisse: hoch)."""
    klein = img.convert("RGB").resize((120, 120))
    px = list(klein.get_flattened_data()) if hasattr(klein, "get_flattened_data") else list(klein.getdata())
    weiss = sum(1 for r, g, b in px if min(r, g, b) > 225)
    grau = sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) < 18)
    return 0.7 * weiss / len(px) + 0.3 * grau / len(px)


def speichern(w, ziel, wid=None):
    """Die bis zu 4 grundrissartigsten Bilder einer Wohnung (aus docs/listings.json) nach ziel."""
    wid = wid or w["id"]
    ziel.mkdir(parents=True, exist_ok=True)
    kandidaten = []
    for i, url in enumerate(dict.fromkeys(w["bilder"])):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                img = Image.open(io.BytesIO(r.read()))
                img.load()
        except Exception:
            continue
        s = bewerten(img) + (0.5 if "grundriss" in url.lower() else 0)
        kandidaten.append((s, i, url, img))
    kandidaten.sort(key=lambda k: -k[0])
    for s, i, url, img in kandidaten[:4]:
        if s < 0.55:
            break
        img.thumbnail((1600, 1600))
        pfad = ziel / f"{wid}_{i:02d}.jpg"  # JPEG: die Recherche-Grundrisse landen im Repo
        img.convert("RGB").save(pfad, quality=85)
        print(f"{pfad}\t{s:.2f}\t{url}")


def main():
    daten = json.loads((ROOT / "docs" / "listings.json").read_text(encoding="utf-8"))["wohnungen"]
    if sys.argv[1] == "--recherche":
        basis = ROOT / "data" / "grundrisse"
        # nur die, die die Routine heute recherchiert (Liste ist nach Vorrang sortiert)
        offen = json.loads((ROOT / "data" / "recherche.json").read_text(encoding="utf-8"))[:15]
        ids = {e["id"] for e in offen}
        if basis.exists():
            for d in basis.iterdir():
                if d.name not in ids:
                    shutil.rmtree(d)
        for e in offen:
            if not (basis / e["id"]).exists():
                speichern(next(x for x in daten if x["id"] == e["id"]), basis / e["id"])
        return
    wid = sys.argv[1]
    ziel = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("grundrisse")
    speichern(next(x for x in daten if wid in x["ids"]), ziel, wid)


if __name__ == "__main__":
    main()
