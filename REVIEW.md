# Prüfanleitung (für Claude)

`python run.py build` schreibt `data/pending.json`: Inserate, bei denen die Automatik
Lage oder Heizung nicht eindeutig beurteilen konnte. Jeder Eintrag hat `fragen`:
`lage` und/oder `heizung`. Lies `titel`, `adresse_im_inserat`, `heizung_felder`
und `text`, beantworte nur die gestellten Fragen und trag das Ergebnis ein.

## Suchgebiet (Kontext für `lage`)
- Ganz erlaubt: 8., 18., 19. Bezirk.
- 9. Bezirk erlaubt, **außer** Lichtental-Nord: nördlich der Alserbachstraße und östlich
  der Nußdorfer Straße bis Spittelau, Franz-Josefs-Bahnhof und Friedensbrücke.
  Servitenviertel, Rossau, Alservorstadt und Himmelpfortgrund sind super.
- 2. Bezirk nur Karmeliterviertel und Augarten-Süd: Obere Augartenstraße, Donaukanal und
  Praterstraße als Grenzen (Taborstraße, Karmeliterplatz, Leopoldsgasse, Große Mohrengasse
  bis Nestroyplatz). Nichts Richtung Volkertviertel, Praterstern oder Stuwerviertel.
- 1. Bezirk nur der Nordwesten: Börse, Schottenring, Freyung, Salzgries, Morzinplatz bis
  Hoher Markt und Herrengasse. Nicht das Zentrum um Stephansplatz und Graben.
- Ob ein Punkt drin ist, rechnet `run.py` selbst. Du lieferst nur die beste Adresse.

## Frage `lage`
Finde aus Text und Titel die genaueste Lage: Straße mit Hausnummer, Straße, Kreuzung,
Platz oder eindeutige Landmarke ("direkt am Karmeliterplatz", "Blick auf den Augarten",
"Ecke Taborstraße/Heinestraße"). Vage Makler-Floskeln ("Nähe Innenstadt",
"zentrale Lage") reichen nicht.
- `sicherheit: genau` heißt, Straße oder Platz sind explizit genannt.
- `sicherheit: ungefaehr` heißt, es gibt eine Landmarke oder Gegend, aus der die Lage klar
  hervorgeht. Dann trag eine repräsentative Straße oder einen Platz dort ein.
- `sicherheit: unklar` heißt, es gibt keinen brauchbaren Hinweis. Die Wohnung bleibt
  dann grau auf der Karte.
`adresse` immer ohne PLZ, etwa "Leopoldsgasse 12" oder "Karmeliterplatz".

## Frage `heizung`
- `gas` heißt, die Wohnung wird mit Gas beheizt: Gasetagenheizung, Gastherme,
  Gaskombitherme, Gas-Zentralheizung, Energieträger Gas. Auch dann, wenn ein Umstieg
  nur geplant ist.
- `kein_gas` heißt, Fernwärme, Wärmepumpe, Erdwärme, Pellets, Strom/Infrarot oder
  ausdrücklich "gasfrei".
- `unklar` heißt, es gibt keine Angabe zum Energieträger, nur ein "Gasanschluss
  vorhanden" ohne Heizbezug, oder die Angaben widersprechen sich. "Etagenheizung" oder
  "Zentralheizung" ohne Energieträger ist `unklar`.
Ein Gasherd allein ist keine Gasheizung.

## Frage `eckdaten`
Zimmeranzahl und/oder Wohnfläche fehlen in den Inseratsfeldern. Such sie im Text,
etwa "4-Zimmer-Wohnung", "ca. 95 m² Wohnfläche" oder eine Raumaufstellung, und trag ein,
was du findest: `{"zimmer": 4, "flaeche": 95}`. Findest du nichts, trag `{}` ein.
Halbe Zimmer werden abgerundet.

## Eintragen
Viele auf einmal (bevorzugt): JSON-Liste in eine temporäre Datei schreiben, dann
`python run.py review-file datei.json`:

```json
[
  {"id": "wh-123", "lage": {"adresse": "Karmeliterplatz", "sicherheit": "genau", "begruendung": "\"direkt am Karmeliterplatz\""},
   "heizung": {"ergebnis": "kein_gas", "begruendung": "Fernwärme laut Ausstattung"}},
  {"id": "wh-456", "heizung": {"ergebnis": "gas", "begruendung": "\"Gaskombitherme 2019 erneuert\""}},
  {"id": "wh-789", "eckdaten": {"zimmer": 4, "flaeche": 102}}
]
```

`begruendung` kurz halten und wenn möglich die Textstelle zitieren. Sie erscheint auf
der Karte. Danach `python run.py build`.
