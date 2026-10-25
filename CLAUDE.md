# Wohnungssuche Wien

Privates Tool: täglich Eigentumswohnungen scrapen, nach Lage und Heizung filtern
und auf einer teilbaren Karte (GitHub Pages, `docs/`) zeigen.

- `python run.py all` scrapt und baut die Karte. `python run.py build` baut nur.
- Kriterien: `config.json` (Preis, m², Zimmer) und `geo/zones.geojson` (Zonen,
  erzeugt von `tools/build_zones.py`). Außerdem raus: Gasheizung (`wohnungen/heizung.py`),
  unbefristet vermietet und sanierungsbedürftig (`wohnungen/zustand.py`).
- Was die Automatik nicht eindeutig beurteilen kann, steht in `data/pending.json`.
  Das prüft Claude nach `REVIEW.md` und trägt es mit `python run.py review-file` ein.
- `data/listings.json` ist der Zustand (alle Inserate), `data/reviews.json` die
  Prüfergebnisse. Beides wird committet.
- Nur Python-Standardbibliothek, damit es überall ohne Installation läuft.
- Portale: ein Modul pro Portal in `wohnungen/` (Schnittstelle: `wohnungen/QUELLEN.md`,
  Liste: `wohnungen/quellen.py`). `python run.py scrape --quellen wh,is` scrapt nur einzelne.
  Nicht machbar (Stand 2026-10): immowelt (DataDome), RE/MAX (Cloudflare), wohnnet
  (Immobilienbereich liefert Fehlerseite), immmo (spiegelt nur andere Portale), EHL/Otto.
- Duplikate: `gruppieren()` in run.py führt dieselbe Wohnung über Portale zu einem Punkt
  zusammen (Preis ±1,5 %, Fläche ±1,5 m², pro Portal nur ein Inserat).
- Merken, Papierkorb und "angesehen" sind gemeinsam für alle Besucher: Firebase Realtime
  Database, Adresse in `docs/einstellungen.json`, Regeln in `tools/firebase-regeln.json`.
  Der tägliche Workflow sichert den Stand nach `data/markierungen.json`. Wiederherstellen:
  `curl -X PUT -d @data/markierungen.json <firebase-url>/markierungen.json` (dafür kurz
  `.write` auf `markierungen` erlauben).
