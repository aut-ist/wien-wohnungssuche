"""Wartet, bis im Nest eine Wohnung mit unsicherer Lage liegt, die noch nicht recherchiert wurde.

Läuft im Hintergrund einer Claude-Sitzung: sobald ein Fall auftaucht, gibt er ihn als JSON-Zeile
aus und beendet sich – dadurch wird Claude geweckt, recherchiert die Lage (siehe REVIEW.md /
tools/ortung.py), trägt sie in data/nest_geprueft.json ein und startet den Wächter neu.

    python tools/nest_waechter.py            (prüft jede Minute)
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIREBASE = json.loads((ROOT / "docs" / "einstellungen.json").read_text(encoding="utf-8"))["firebase"].rstrip("/")
KARTE = "https://aut-ist.github.io/wien-wohnungssuche/listings.json"
GEPRUEFT = ROOT / "data" / "nest_geprueft.json"


def laden(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Cache-Control": "no-cache"}), timeout=60) as r:
        return json.load(r)


def offene_faelle():
    mark = laden(f"{FIREBASE}/markierungen.json") or {}
    nest, korb = set((mark.get("gemerkt") or {})), set((mark.get("papierkorb") or {}))
    # lokale Kartendaten, falls neuer als die veröffentlichten (z. B. direkt nach einem Build)
    lokal = ROOT / "docs" / "listings.json"
    daten = laden(f"{KARTE}?t={int(time.time())}")
    if lokal.exists():
        l = json.loads(lokal.read_text(encoding="utf-8"))
        if l.get("stand", "") > daten.get("stand", ""):
            daten = l
    geprueft = json.loads(GEPRUEFT.read_text(encoding="utf-8")) if GEPRUEFT.exists() else {}
    erledigt = {i for e in geprueft.values() for i in e.get("ids", [])} | set(geprueft)
    return [w for w in daten["wohnungen"]
            if set(w["ids"]) & nest and not set(w["ids"]) & korb
            and w.get("ungefaehr") and not set(w["ids"]) & erledigt]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pause = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    while True:
        try:
            faelle = offene_faelle()
        except Exception as e:  # Netz weg o. Ä.: einfach weiter versuchen
            print(f"(Wächter: {e})", file=sys.stderr)
            faelle = []
        if faelle:
            for w in faelle:
                print(json.dumps({"id": w["id"], "ids": w["ids"], "titel": w["titel"], "plz": w["plz"],
                                  "lage": w.get("lage"), "links": [l["url"] for l in w["links"]]}, ensure_ascii=False))
            return
        time.sleep(pause)


if __name__ == "__main__":
    main()
