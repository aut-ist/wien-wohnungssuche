# Wohnungssuche Wien

Privates Tool: täglich Eigentumswohnungen scrapen, nach Lage und Heizung filtern
und auf einer teilbaren Karte (GitHub Pages, `docs/`) zeigen.

- `python run.py all` scrapt und baut die Karte. `python run.py build` baut nur.
- Kriterien: `config.json` (Preis, m², Zimmer) und `geo/zones.geojson` (Zonen,
  erzeugt von `tools/build_zones.py`). Außerdem raus: Gasheizung (`wohnungen/heizung.py`),
  unbefristet vermietet und sanierungsbedürftig (`wohnungen/zustand.py`).
- Täglicher Ablauf: GitHub Actions scrapt (`taeglich.yml`, drei Termine ab 04:23 UTC, wer heute
  schon gescrapt hat, überspringt; Datum in `data/letzter_scrape.txt`). Um 05:04 UTC prüft eine
  Claude-Cloud-Routine `data/pending.json`. In der Cloud blockt der Proxy die Portale, dort nie
  scrapen; fehlt der Scrape, committet die Routine `data/anstoss.txt`, das startet den Workflow.
  Erreicht `run.py scrape` gar kein Portal, bricht er ab (Exit 2), ohne etwas zu speichern.
  Ein voller Scrape dauert 40 bis 60 Minuten; pusht in der Zeit jemand, nimmt der Workflow den
  neuen Stand von main, legt nur die Scrape-Daten darüber und baut neu (kein Rebase-Konflikt).
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
- Versetzte Punkte: willhaben-Detailseiten nennen `POSITION_RADIUS_METERS` (oft 250–270 m), dann
  liegt das Haus nur irgendwo in diesem Umkreis (`lage_radius`; ImmoScout24 übernimmt denselben
  Punkt). So ein Inserat ist "Lage ungefähr", raus nur, wenn der ganze Umkreis außerhalb liegt,
  und grau mit Lage-Frage, wenn der Umkreis eine Zonengrenze schneidet (`geo.pruefe_umkreis`).
- Nest-Recherche: JEDE Wohnung, die ins Nest gelegt wird, wird auf ihre Lage geprüft (auch mit
  "genauen" Portal-Koordinaten: Makler setzen teils Standardpunkte, z. B. MAISON WÄHRING zeigte
  Kreuzgasse 23 statt Staudgasse 40). Neue Nest-Wohnungen meldet das
  `tools/nest_waechter.py` (läuft im Hintergrund einer Claude-Sitzung, beendet sich beim Fund).
  Genauso jede neue passende Wohnung (grün) ohne Adresse mit Hausnummer: `run.py build` listet sie
  in `data/recherche.json`, der Workflow legt ihre Grundrisse nach `data/grundrisse/ID/`, und die
  tägliche Routine recherchiert sie (in der Cloud sind die Portalseiten gesperrt, Bauträger- und
  Maklerseiten nicht). Erledigt = Eintrag in `data/nest_geprueft.json`, auch wenn nichts gefunden wurde.
  Ziel ist die Hausnummer, möglichst auch das Top. Vorgehen: alle Portaltexte der Gruppe lesen →
  Grundrisse ansehen (siehe unten) → Bauträger bzw. Projekt herausfinden und die eigenen Webseiten
  von Bauträger und Makler mit der Projektseite bzw. dem Exposé suchen: dort stehen meist Straße mit Hausnummer und eine
  Einheitenliste (Top, Zimmer, m², Preis), an der man die Wohnung eindeutig erkennt. Das ist
  verlässlicher als Portaladressen: Bei der ESTINA-Gartenwohnung nannten willhaben und
  ImmoScout24 beide Krottenbachstraße 105, laut Einheitenliste ist es Krottenbachstraße 182, Top 2.7
  ("Punkt identisch" auf zwei Portalen beweist nichts) → Grundrisse: die Bilder unter den Fotos
  (`python tools/grundrisse.py ID ZIEL` speichert sie; das Schriftfeld nennt oft Projekt und
  Adresse, und gleiche Grundrisse entlarven Doppelte verschiedener Makler → review "gleich_wie")
  → Websuche nach dem Inserat und dem Projektnamen auf anderen Seiten (weekend.at, immomarktplatz,
  Firmenbuch, Pressemeldungen; oft steht dort die Adresse) → sonst rückwärts erschließen: bei
  Projekten alle Einheiten auf ImmoScout24 suchen (ohne Preisgrenze) und die zufällig versetzten
  Punkte mitteln, Schwester-Inserate desselben Hauses (gleicher Energieausweis) vergleichen, bei
  versetzten Punkten den Umkreis absuchen, Gehzeiten/Entfernungen aus dem Text mit `tools/ortung.py`
  einmessen. Ergebnis mit `run.py review ID --adresse/--lat --lon --sicherheit` für alle IDs der
  Gruppe eintragen, in `data/nest_geprueft.json` vermerken, bauen, pushen, Wächter neu starten.
- Duplikate: `gruppieren()` in run.py führt dieselbe Wohnung über Portale zu einem Punkt
  zusammen (Preis ±1,5 %, Fläche ±1,5 m², pro Portal nur ein Inserat).
- Merken, Papierkorb und "angesehen" sind gemeinsam für alle Besucher: Firebase Realtime
  Database, Adresse in `docs/einstellungen.json`, Regeln in `tools/firebase-regeln.json`.
  Der tägliche Workflow sichert den Stand nach `data/markierungen.json`. Wiederherstellen:
  `curl -X PUT -d @data/markierungen.json <firebase-url>/markierungen.json` (dafür kurz
  `.write` auf `markierungen` erlauben).
