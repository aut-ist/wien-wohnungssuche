# Wohnungssuche Wien

Privates Tool: täglich Eigentumswohnungen scrapen, nach Lage und Heizung filtern
und auf einer teilbaren Karte (GitHub Pages, `docs/`) zeigen.

- `python run.py all` scrapt und baut die Karte. `python run.py build` baut nur.
- Kriterien: `config.json` (Preis, m², ab 3 Zimmer seit 2026-10-28; auf der Karte Auswahl 3 / 4 / 5+) und `geo/zones.geojson` (Zonen,
  erzeugt von `tools/build_zones.py`). Außerdem raus: unbefristet vermietet und
  sanierungsbedürftig oder teilsaniert (`wohnungen/zustand.py`), befristet vermietet über Ende September 2027 hinaus
  (`miete_bis` liest das Enddatum). Seit 2026-10-28 außerdem: genau 3 Zimmer nur bis 700.000 €
  (`filter_grund`) und im 18./19. nur bis 10 min Öffis zum Gürtel (`bewerten`; bei ungefährer Lage
  grau statt raus, solange es vom Umkreis aus reichen könnte); für 4+ Zimmer gilt beides nicht.
  Einzug spätestens Q3 2027 (`config.json` `einzug_spaetestens`): `zustand.bezug_einschaetzen`
  liest Fertigstellung/Bezug/"Verfügbar ab" aus allen Inseraten der Gruppe (der späteste Termin
  zählt; Lift, Balkone, Energieausweis, Miete zählen nicht) und sonst das Baujahr-Feld (2027 ohne
  Monat -> Frage an die Routine); review `{"zustand": {..., "bezug_ok": true}}` hebt es auf. Die Heizung (`wohnungen/heizung.py`: Gas, kein Gas,
  unklar) schließt seit 2026-10-28 nichts mehr aus; oben gibt es den Schalter "ohne Gasheizung".
  Sonst gelten für Gaswohnungen alle Regeln wie für alle anderen.
- Adress-Recherche: höchstens `RECHERCHE_PRO_TAG` (25) pro Morgen, `data/recherche.json` ist nach
  Vorrang sortiert (Nest, dann neueste; Gaswohnungen sind ganz normale Wohnungen); Grundrisse lädt der Workflow nur für diese.
- Täglicher Ablauf: GitHub Actions scrapt (`taeglich.yml`, drei Termine ab 04:23 UTC, wer heute
  schon gescrapt hat, überspringt; Datum in `data/letzter_scrape.txt`; die GitHub-Termine fallen oft
  aus oder kommen Stunden später). Um 05:00 UTC (06:00 Wien, Winterzeit) startet eine Claude-Cloud-Routine, stößt den Scrape an, wartet bis 100 min, prüft
  `data/pending.json` und recherchiert; sie wartet mit ihrer Zusammenfassung (= Benachrichtigung)
  bis 09:15 Wiener Zeit, so will es das Paar. In der Cloud blockt der Proxy die Portale, dort nie
  scrapen; fehlt der Scrape, committet die Routine `data/anstoss.txt`, das startet den Workflow.
  Erreicht `run.py scrape` gar kein Portal, bricht er ab (Exit 2), ohne etwas zu speichern.
  derStandard (403) und FindMyHome (Timeouts) sperren GitHub-Server teilweise: `wohnungen/http.py`
  überspringt einen Host nach 2 Fehlschlägen in Folge für den Rest des Laufs (auch Nominatim), und
  nach `SCRAPE_MAX_MIN` (75) bricht jede Anfrage ab, damit der Lauf noch speichert. Nie wieder lange
  Warte-/Wiederholschleifen pro Anfrage einbauen: am 2026-10-29 lief der Scrape so in den 2-h-Abbruch.
  Ein voller Scrape dauert 40 bis 60 Minuten; pusht in der Zeit jemand, nimmt der Workflow den
  neuen Stand von main, legt nur die Scrape-Daten darüber und baut neu (kein Rebase-Konflikt).
- Seitencheck (`tools/seitencheck.py`, Playwright, iPhone-Emulation): öffnet docs/ und prüft JS-Fehler,
  Eier, Karten, geladene Bilder (< 150), DOM-Größe -> `data/seitencheck.json`. Läuft im täglichen
  Workflow (die Routine meldet Probleme ganz oben) und als eigener Workflow bei jeder Änderung an
  docs/index.html (schlägt fehl -> Mail). Vor jedem Push von docs/index.html lokal laufen lassen.
  Hintergrund: 2026-10-29 stürzte die Seite am iPhone ab, weil die Liste alle Karten mit je 12
  Fotos auf einmal baute; jetzt 30 Karten pro Schritt (`listeRendern`), Fotos erst beim Wischen.
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
  Punkt). So ein Inserat ist "Lage ungefähr", raus, wenn der Punkt selbst außerhalb liegt (die
  Zonen gelten streng, Toleranz 50 m für Ungenauigkeit der Zeichnung), grau mit Lage-Frage, wenn
  der Umkreis eine Zonengrenze schneidet (`geo.pruefe_umkreis`). Die blauen Zonen werden auf der
  Karte nur nicht angezeigt (Wunsch), sie gelten aber. Umgekehrt bei der roten Zone im 9.
  (Lichtental-Nord, Westgrenze Liechtensteinstraße): bei unsicherer Lage (versetzter Punkt, nur
  Straße, ungefähre Prüfung) nur raus, wenn der ganze Umkreis darin liegt, sonst grau
  (`rot_vielleicht_draussen` in run.py) – im Zweifel bleibt die Wohnung. Seit 2026-10-29 gibt es
  eine zweite rote Zone im 19. (Heiligenstadt): alles östlich der Straßenbahn 37 (Nußdorfer Straße,
  Döblinger Hauptstraße, Hohe Warte bis zur Schleife) bis zum Donaukanal, vom Gürtel bis zur Kante
  Hohe-Warte-Schleife – Bahnhof Heiligenstadt. Punkte der Straßenbahn aus geo/oeffis.geojson, Ost-
  und Südrand ist die Bezirksgrenze (`zuschneiden: "genau"` in tools/build_zones.py, braucht shapely);
  es gilt dieselbe Im-Zweifel-drin-Regel.
- Öffi-Linien auf der Karte (tools/fetch_oeffis.py, lokal laufen lassen, braucht shapely): 8., 9., 18., 19.
  und die blaue Zone im 2. Straßenbahn/Bus/U-Bahn aus dem GTFS der Wiener Linien (aktuelle Wege, U-Bahn
  in Linienfarbe, ohne Nachtbusse und Sonderfahrpläne); OEFFLINIENOGD von data.wien.gv.at ist veraltet
  (13A, Linie 2) und liefert nur noch S-Bahn-Strecken und U-/S-Stationen. Die U5 (in Bau, bis
  Frankhplatz ab 2030, bis Hernals Mitte 2030er) ist auf Wunsch eingezeichnet, als gäbe es sie schon
  (`U5_STATIONEN`); die Öffi-Zeiten zum Gürtel rechnen ohne sie.
- Fläche: seit 2026-10-30 ab 75 m² (`flaeche_min`); Wohnungen, die vorher schon gefunden wurden
  (`erstmals` der Gruppe, auch über Neu-Inserate), bleiben ab 70 m² (`flaeche_min_bestand`), so wollte
  es das Paar. Der Scrape lädt Detailseiten noch ab 70 m², weil er nicht weiß, ob ein neues Inserat
  zu einer bekannten Wohnung gehört.
- Nest-Recherche: JEDE Wohnung, die ins Nest gelegt wird, wird auf ihre Lage geprüft (auch mit
  "genauen" Portal-Koordinaten: Makler setzen teils Standardpunkte, z. B. MAISON WÄHRING zeigte
  Kreuzgasse 23 statt Staudgasse 40). Neue Nest-Wohnungen meldet das
  `tools/nest_waechter.py` (läuft im Hintergrund einer Claude-Sitzung, beendet sich beim Fund).
  Genauso jede Wohnung auf der Karte (grün oder grau, nicht im Papierkorb, auch ältere, die nach einer
  Regeländerung wieder auftaucht) ohne Adresse mit Hausnummer: `run.py build` listet sie
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
- Schwester-Inserate automatisch (seit 2026-10-30, `gleiches_haus` in run.py): hat ein Inserat ohne
  Hausnummer denselben Makler und Energieausweis (HWB + fGEE) wie ein Inserat mit Hausnummer, oder
  mindestens zwei gleiche willhaben-Fotodateien, übernimmt `build` dessen Adresse (Top nach "/" weg),
  wenn alle Treffer dasselbe Haus nennen. Anlass: Lind "Idealer Grundriss…" (Währinger Straße 168,
  Top 39 + Nachbarwohnung) hatte die Routine nur als "Währinger Straße" eingetragen. Grundrisse:
  `tools/grundrisse.py` erkennt auch farbige Pläne (schwarze Mauern + große einfarbige Flächen);
  vorher fand es sie nicht, und die Routine schrieb "keine Grundrisse".
- Google-Maps-Link: geprüfte Adresse, sonst der Punkt ("ungefähr"), nie nur der Bezirk. Street View
  startet am nächsten Straßenpunkt vor dem Haus mit Blick aufs Haus (`strassenblick` in
  wohnungen/geocode.py, Cache `data/strassenblick_cache.json`); am Hauspunkt selbst zeigt Google
  oft Nutzerfotos aus Höfen statt der Straßenansicht.
- Preis für Eigennutzer: manche Inserate zeigen den Anlegerpreis netto (ohne 20 % USt). Das Paar
  zieht selbst ein, also zählt der Eigennutzerpreis (Filter und Anzeige): `eigennutzer_preis()` in
  run.py liest ihn aus dem Text ("Eigennutzerpreis: € …", "… für Endnutzer"), sonst Anlegerpreis
  + 20 % und Frage `preis` an die Routine; von Hand per review `{"preis": {"eigennutzer": N}}`.
- Online-Status: Nest-Wohnungen werden beim Scrape einzeln aufgerufen (`online_pruefen`), auch
  wenn die Suche sie nicht zeigt. Verschwundene Inserate bleiben 14 Tage in der Liste, ausgegraut
  ("nicht mehr online"), aber nicht auf der Karte. Neu inserierte Wohnungen (gleicher Makler,
  Portal, m², Zimmer, Stock, HWB; `neu_inseriert`) übernehmen Verlauf, Nest und Prüfungen der alten Nummer,
  auch wenn die alte schon Wochen weg ist (bis sie gelöscht wird; Rausgeworfenes bleibt dafür ein Jahr in
  listings.json).
- Papierkorb und Neu-Inserate (Wunsch 2026-10-30): wer eine ausgegraute ("nicht mehr online") Wohnung
  rauswirft und sie taucht wieder auf, sieht sie wieder, als NEU ab dem Tag der Rückkehr; wer eine
  online stehende rauswirft, sieht dieselbe Wohnung auch neu inseriert nicht mehr. `build` merkt sich
  in `data/papierkorb_status.json` pro Eintrag (Zeitstempel), ob die Wohnung auf der zuletzt gebauten
  Karte ausgegraut war, und gibt wieder Aufgetauchten `korb_frei` (id -> Zeitstempel) und `neu_seit`
  mit; die Seite ignoriert genau diese Einträge. Erneut rausgeworfen = neuer Zeitstempel = weg.
- Preisverlauf: jedes Inserat merkt sich Preisänderungen (`preis_historie`), die Gruppe führt sie
  über alle Portale zusammen (`preisverlauf`, dazu `online_seit` = frühestes Inseratsdatum). Für
  Nest-Wohnungen hält `data/preisverlauf.json` den Verlauf und den letzten Stand fest, auch über
  Neu-Inserate hinweg; verschwindet das Inserat, bleibt die Wohnung grau "nicht mehr online" sichtbar.
- Duplikate: `gruppieren()` in run.py führt dieselbe Wohnung über Portale zu einem Punkt
  zusammen (Preis ±1,5 %, Fläche ±1,5 m², pro Portal nur ein Inserat). Anderer Energieausweis
  (HWB > 5 % Abweichung) oder anderes Baujahr heißt anderes Haus: nie zusammenführen.
- "Neu" auf der Karte zählt ab dem ersten Tag, an dem eine Wohnung auf der Karte steht
  (`data/sichtbar_seit.json`), nicht ab dem ersten Fund; so sind auch Wohnungen neu, die erst nach
  einer Regeländerung passen ("NEU" nur in der Liste). Karte: grünes Ei für alles, was in Frage
  kommt, hell-oranges Ei mit Gasheizung (bewusst blasser als das goldorange Nest-Ei; blass = schon angeschaut, gestrichelt = Lage ungefähr),
  goldenes Ei = im Nest, goldorange = im Nest mit Gasheizung; keine passt/unklar/raus- und keine
  Neu-Markierung auf der Karte (Wunsch).
- Merken, Papierkorb und "angesehen" sind gemeinsam für alle Besucher: Firebase Realtime
  Database, Adresse in `docs/einstellungen.json`, Regeln in `tools/firebase-regeln.json`.
  Der tägliche Workflow sichert den Stand nach `data/markierungen.json`. Wiederherstellen:
  `curl -X PUT -d @data/markierungen.json <firebase-url>/markierungen.json` (dafür kurz
  `.write` auf `markierungen` erlauben).
