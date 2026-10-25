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
- Öffi-Zeit zum Gürtel (18./19. Bezirk): `tools/oeffi_zeiten.py` rechnet aus dem GTFS-Fahrplan der
  Wiener Linien die mittlere Zeit je Haltestelle bis zu einer U6-Station am Gürtel ->
  `geo/guertel_zeiten.json`; `guertel_zeit()` in run.py addiert den Fußweg. Neu rechnen, wenn
  sich Fahrpläne ändern (z. B. zum Fahrplanwechsel im Dezember).
- Nest-Recherche: JEDE Wohnung, die ins Nest gelegt wird, wird auf ihre Lage geprüft (auch mit
  "genauen" Portal-Koordinaten: Makler setzen teils Standardpunkte, z. B. MAISON WÄHRING zeigte
  Kreuzgasse 23 statt Staudgasse 40). Neue Nest-Wohnungen meldet das
  `tools/nest_waechter.py` (läuft im Hintergrund einer Claude-Sitzung, beendet sich beim Fund).
  Vorgehen: alle Portaltexte der Gruppe lesen → Grundrisse unter den Fotos ansehen
  (`python tools/grundrisse.py ID ZIEL` speichert sie; das Schriftfeld nennt oft Projekt und
  Adresse, und gleiche Grundrisse entlarven Doppelte verschiedener Makler → review "gleich_wie")
  → Websuche nach dem Inserat auf anderen Seiten
  (oft steht dort die Adresse) → bei Projekten alle Einheiten auf ImmoScout24 suchen (ohne
  Preisgrenze) und die zufällig versetzten Punkte mitteln → Gehzeiten/Entfernungen aus dem Text
  mit `tools/ortung.py` einmessen. Ergebnis mit `run.py review ID --lat --lon --sicherheit`
  eintragen, in `data/nest_geprueft.json` vermerken, bauen, pushen, Wächter neu starten.
  Reicht schon die Info im Inserat für ±100 m, nicht weiter recherchieren.
- Duplikate: `gruppieren()` in run.py führt dieselbe Wohnung über Portale zu einem Punkt
  zusammen (Preis ±1,5 %, Fläche ±1,5 m², pro Portal nur ein Inserat).
- Merken, Papierkorb und "angesehen" sind gemeinsam für alle Besucher: Firebase Realtime
  Database, Adresse in `docs/einstellungen.json`, Regeln in `tools/firebase-regeln.json`.
  Der tägliche Workflow sichert den Stand nach `data/markierungen.json`. Wiederherstellen:
  `curl -X PUT -d @data/markierungen.json <firebase-url>/markierungen.json` (dafür kurz
  `.write` auf `markierungen` erlauben).
