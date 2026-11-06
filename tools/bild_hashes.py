"""Rechnet je Foto-URL einen Bild-Fingerabdruck (dHash, 64 bit) und einen Grundriss-Wert (wie
tools/grundrisse.py) und speichert beides in data/bild_hashes.json ({url: {"h": hash, "g": wert}}).
run.py (nur Standardbibliothek) liest den Cache: pro Wohnung alle Fotos aller Portale, gleiche Fotos nur
einmal, und der Grundriss als zweites Foto (Wünsche 2026-11-06).

    python tools/bild_hashes.py            Nest-Wohnungen und alle Wohnungen auf der Karte (fehlende Hashes)
    python tools/bild_hashes.py --nest     nur Nest-Wohnungen
    python tools/bild_hashes.py --max 60   höchstens so viele Wohnungen (täglicher Workflow)
Braucht pillow.
"""
import io
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grundrisse import bewerten  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "bild_hashes.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36"}


def dhash(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            img = Image.open(io.BytesIO(r.read()))
            img.load()
    except Exception:
        return None
    g = img.convert("L").resize((9, 8))
    px = list(g.get_flattened_data()) if hasattr(g, "get_flattened_data") else list(g.getdata())
    bits = "".join("1" if px[y * 9 + x] > px[y * 9 + x + 1] else "0" for y in range(8) for x in range(8))
    return {"h": f"{int(bits, 2):016x}", "g": round(bewerten(img) + (0.5 if "grundriss" in url.lower() else 0), 2)}


def main():
    nur_nest = "--nest" in sys.argv
    max_w = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    listings = json.loads((ROOT / "data" / "listings.json").read_text(encoding="utf-8"))
    karte = json.loads((ROOT / "docs" / "listings.json").read_text(encoding="utf-8"))["wohnungen"]
    nest = set((json.loads((ROOT / "data" / "markierungen.json").read_text(encoding="utf-8")).get("gemerkt") or {}))
    gruppen = [w["ids"] for w in karte if set(w["ids"]) & nest]
    if not nur_nest:
        gruppen += [w["ids"] for w in karte if w["status"] != "raus" and not w.get("offline") and not set(w["ids"]) & nest]
    offen = []
    for g in gruppen:
        urls = [u for i in g for u in (listings.get(i) or {}).get("bilder") or [] if u not in cache]
        if urls:
            offen.append(urls)
    if max_w:
        offen = offen[:max_w]
    urls = list(dict.fromkeys(u for g in offen for u in g))
    print(f"{len(offen)} Wohnungen, {len(urls)} Fotos ohne Fingerabdruck")
    with ThreadPoolExecutor(8) as ex:
        for k, (u, h) in enumerate(zip(urls, ex.map(dhash, urls)), 1):
            if h:
                cache[u] = h
            if k % 500 == 0:
                print(f"  {k}/{len(urls)}", flush=True)
                CACHE.write_text(json.dumps(cache), encoding="utf-8")
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    print(f"gespeichert: {len(cache)} Fingerabdrücke")


if __name__ == "__main__":
    main()
