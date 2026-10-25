# Schnittstelle für Portal-Module

Jedes Portal ist ein Modul `wohnungen/<name>.py` mit:

```python
QUELLE = "ImmoScout24"   # Anzeigename auf der Karte
PREFIX = "is"            # genau 2 Kleinbuchstaben, eindeutig (willhaben = "wh")

def search(plz: int):     # yield Zusammenfassungen: Eigentumswohnungen (KAUF) in Wien mit dieser PLZ
def detail(listing_id: str) -> dict | None   # Detailseite; None wenn offline
```

`run.py` ruft `search(plz)` für 1010, 1020, 1080, 1090, 1180, 1190 auf und `detail(id)`
nur für neue Kandidaten. Filtern (Preis ≤ 1 Mio, ≥ 70 m², ≥ 4 Zimmer, Lage, Heizung)
macht die Pipeline. Das Modul soll aber die Suchfilter des Portals nutzen, wo möglich
(Kauf, Wohnung, Ort, Preis bis 1.000.000, Fläche ab 70), damit wenig Seiten nötig sind.

## Zusammenfassung (search)
Unbekannt → `None`.

| Feld | Inhalt |
|---|---|
| id | `f"{PREFIX}-{ziffern}"`, bei nicht-numerischer Portal-ID `numid()` aus `http.py` |
| quelle | `QUELLE` |
| url | Link zum Inserat |
| titel | Überschrift |
| preis | Kaufpreis in € (float) |
| flaeche | Wohnfläche m² (float) |
| zimmer | Zimmer (int) |
| plz | int |
| adresse | Straße [+ Hausnummer] oder None |
| lat, lon | float oder None |
| lage_genauigkeit | `"adresse"` (Hausnummer genau), `"strasse"`, `"bezirk"` (nur ungefähr/Bezirksmitte) |
| bild | erstes Foto (URL) |
| bilder | Liste Foto-URLs (max. 30) |
| veroeffentlicht | ISO-Datum oder None |
| anbieter | Makler/Firma oder "privat" |
| typ | z. B. "Dachgeschoßwohnung" |
| freiflaeche | Liste, z. B. `["Balkon", "Terrasse"]` |
| projekt | True nur für Neubauprojekt-Sammelinserate mit mehreren Einheiten |

## Detail (detail)
`text` (Klartext, Abschnitte als `## Titel\n…`), `heizung_felder` (Liste wie
`"Heizung: Fernwärme"`, `"Heizungsart: Gas"`), `energie` (`{hwb, hwb_class, fgee, fgee_class}`),
`baujahr`, `bauart`, `zustand`, `stockwerk`, `monatlich`, `adresse`, `lat`, `lon`,
`flaeche`, `zimmer`, `preis`, `bilder`. Unbekanntes weglassen oder None.

## Regeln
- Nur Python-Standardbibliothek. HTTP über `from .http import get, next_data, numid`
  (`get` hat Browser-User-Agent, Pausen und Retries und liefert bei 404 None).
- Keine Logins, keine Umgehung von Bot-Schutz (Captcha, Cloudflare-Challenge, DataDome).
  Blockt ein Portal, wird es weggelassen.
- Ungefähre Koordinaten (Bezirksmitte, bei vielen Inseraten identisch) → `lage_genauigkeit = "bezirk"`.
