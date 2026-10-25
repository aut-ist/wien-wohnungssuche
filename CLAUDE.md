# Wohnungssuche Wien

Privates Tool: täglich Eigentumswohnungen scrapen, nach Lage und Heizung filtern
und auf einer teilbaren Karte (GitHub Pages, `docs/`) zeigen.

- `python run.py all` scrapt und baut die Karte. `python run.py build` baut nur.
- Kriterien: `config.json` (Preis, m², Zimmer) und `geo/zones.geojson` (Zonen,
  erzeugt von `tools/build_zones.py`).
- Was die Automatik nicht eindeutig beurteilen kann, steht in `data/pending.json`.
  Das prüft Claude nach `REVIEW.md` und trägt es mit `python run.py review-file` ein.
- `data/listings.json` ist der Zustand (alle Inserate), `data/reviews.json` die
  Prüfergebnisse. Beides wird committet.
- Nur Python-Standardbibliothek, damit es überall ohne Installation läuft.
