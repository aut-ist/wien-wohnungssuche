"""Alle Portal-Module (Schnittstelle: QUELLEN.md). Fehlt ein Modul, wird es übersprungen."""
import importlib

NAMEN = ["willhaben", "immoscout24", "immowelt", "derstandard", "wohnnet", "immmo",
         "findmyhome", "remax", "sreal", "raiffeisen", "ehl", "otto", "immodirekt"]

QUELLEN = {}
for _n in NAMEN:
    try:
        _m = importlib.import_module(f"wohnungen.{_n}")
    except ModuleNotFoundError as e:
        if e.name != f"wohnungen.{_n}":
            print(f"Quelle {_n} übersprungen: {e}")
        continue
    except Exception as e:  # ein kaputtes Modul soll die anderen nicht stoppen
        print(f"Quelle {_n} übersprungen: {e}")
        continue
    QUELLEN[_m.PREFIX] = _m


def modul(listing_id):
    return QUELLEN.get(listing_id.split("-", 1)[0])
