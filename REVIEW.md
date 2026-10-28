# Prüfanleitung (für Claude)

`python run.py build` schreibt `data/pending.json`: Inserate, bei denen die Automatik
Lage oder Heizung nicht eindeutig beurteilen konnte. Jeder Eintrag hat `fragen`:
`lage`, `heizung`, `zustand`, `eckdaten` oder `preis`. Lies `titel`, `adresse_im_inserat`, `heizung_felder`
und `text`, beantworte nur die gestellten Fragen und trag das Ergebnis ein.

Steht dieselbe Wohnung auf mehreren Portalen, ist sie zu einem Eintrag zusammengeführt.
`text` enthält dann die Texte aller Portale, jeweils mit einer Kopfzeile wie
`## ===== ImmoScout24 =====`, und `heizung_felder` hat die Quelle in Klammern. Nutze alle
Texte. Oft nennt ein Portal die Straße, ein anderes nicht. Widersprechen sich die Portale
bei der Heizung, gilt die konkretere Angabe; im Zweifel `unklar` mit Begründung.

## Suchgebiet (Kontext für `lage`)
- Ganz erlaubt: 8., 18., 19. Bezirk.
- 9. Bezirk erlaubt, **außer** Lichtental-Nord: nördlich der Alserbachstraße und östlich
  der Liechtensteinstraße bis Spittelau, Franz-Josefs-Bahnhof (Althan Quartier) und Friedensbrücke.
  Im Zweifel (Lage nur ungefähr) bleibt die Wohnung drin.
  Servitenviertel, Rossau, Alservorstadt und Himmelpfortgrund sind super.
- 2. Bezirk nur Karmeliterviertel und Augarten-Süd: Obere Augartenstraße, Donaukanal und
  Praterstraße als Grenzen (Taborstraße, Karmeliterplatz, Leopoldsgasse, Große Mohrengasse
  bis Nestroyplatz). Nichts Richtung Volkertviertel, Praterstern oder Stuwerviertel.
- 1. Bezirk nur der Nordwesten: Börse, Schottenring, Freyung, Salzgries, Morzinplatz bis
  Hoher Markt und Herrengasse. Nicht das Zentrum um Stephansplatz und Graben.
- Ob ein Punkt drin ist, rechnet `run.py` selbst. Du lieferst nur die beste Adresse.

## Frage `lage`
Im 1., 2. und 9. Bezirk entscheidet die Lage, ob die Wohnung drin ist. Im 18. und 19. passt sie
sowieso; dort wird die Adresse für die Öffi-Zeit zum Gürtel gebraucht. Achte deshalb auch auf
Projektnamen mit Adresse ("M86" = Martinstraße 86), Hausnamen und Straßen in Grundriss-Texten.

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
Seit 2026-10-28 schließt Gas nichts mehr aus: die Heizung ist ein Filter auf der Karte (kein Gas,
unklar, Gas). Trotzdem genau einordnen, sonst stimmt der Filter nicht.
- `gas` heißt, die Wohnung wird mit Gas beheizt: Gasetagenheizung, Gastherme,
  Gaskombitherme, Gas-Zentralheizung, Energieträger Gas. Auch dann, wenn ein Umstieg
  nur geplant ist.
- `kein_gas` heißt, Fernwärme, Wärmepumpe, Erdwärme, Pellets, Strom/Infrarot oder
  ausdrücklich "gasfrei".
- `unklar` heißt, es gibt keine Angabe zum Energieträger, nur ein "Gasanschluss
  vorhanden" ohne Heizbezug, oder die Angaben widersprechen sich. "Etagenheizung" oder
  "Zentralheizung" ohne Energieträger ist `unklar`.
Ein Gasherd allein ist keine Gasheizung.

## Frage `zustand`
Die Käufer wollen selbst einziehen und nichts sanieren. Antworte mit
`{"ergebnis": "raus" | "ok" | "hinweis", "begruendung": "..."}`:
- `raus` wenn die Wohnung **unbefristet vermietet** ist. Das gilt auch, wenn "vermietet"
  ohne jedes Enddatum dasteht, typisch bei Anleger- oder Vorsorgewohnungen mit
  Mietertrag. Ebenso `raus`, wenn sie **saniert oder renoviert werden muss**:
  sanierungs- oder renovierungsbedürftig, Originalzustand, für Handwerker,
  Rohdachboden, "nach Ihren Vorstellungen sanieren". Auch **belagsfertig**, Edelrohbau oder
  ohne Bodenbeläge (Böden, Fliesen oder Bad fehlen noch) sind `raus`; schlüsselfertig ist ok.
- `hinweis` wenn sie **befristet** vermietet ist (z. B. "befristet bis 2027") oder nur kleine
  Arbeiten nötig sind. Die Wohnung bleibt drin, `begruendung` erscheint als Hinweis.
- `ok` heißt bestandsfrei, saniert oder Erstbezug. Ebenso, wenn "Mieter" nur allgemein
  erwähnt wird ("ideal für Eigennutzer oder Anleger") oder Arbeiten nur das Haus
  betreffen (Fassade wird saniert).

## Frage `eckdaten`
Zimmeranzahl und/oder Wohnfläche fehlen in den Inseratsfeldern. Such sie im Text,
etwa "4-Zimmer-Wohnung", "ca. 95 m² Wohnfläche" oder eine Raumaufstellung, und trag ein,
was du findest: `{"zimmer": 4, "flaeche": 95}`. Findest du nichts, trag `{}` ein.
Halbe Zimmer werden abgerundet.

## Frage `preis`
Das Inserat zeigt vermutlich den **Anlegerpreis** (netto, "zzgl. 20 % USt", "für Anleger mit
Vorsteuerabzug", Vorsorgewohnung). Das Paar will selbst einziehen, zählt also der Preis für
Eigennutzer bzw. Endnutzer. Steht er im Text ("Eigennutzerpreis: € 899.000", "€ 899.000 für
Endnutzer"), trag ihn ein: `{"eigennutzer": 899000, "begruendung": "..."}`. Steht nur der
Nettopreis, rechne +20 % USt. Ist der gezeigte Preis schon der Eigennutzerpreis, trag ihn ein.

## Eintragen
Viele auf einmal (bevorzugt): JSON-Liste in eine temporäre Datei schreiben, dann
`python run.py review-file datei.json`:

```json
[
  {"id": "wh-123", "lage": {"adresse": "Karmeliterplatz", "sicherheit": "genau", "begruendung": "\"direkt am Karmeliterplatz\""},
   "heizung": {"ergebnis": "kein_gas", "begruendung": "Fernwärme laut Ausstattung"}},
  {"id": "wh-456", "heizung": {"ergebnis": "gas", "begruendung": "\"Gaskombitherme 2019 erneuert\""}},
  {"id": "wh-789", "eckdaten": {"zimmer": 4, "flaeche": 102}},
  {"id": "wh-321", "preis": {"eigennutzer": 899000, "begruendung": "\"€ 899.000,- für Endnutzer / € 810.500,- exkl. 20% USt. für Anleger\""}}
]
```

`begruendung` kurz halten und wenn möglich die Textstelle zitieren. Sie erscheint auf
der Karte. Danach `python run.py build`.
