"""Adresse -> Koordinaten über OpenStreetMap Nominatim (max. 1 Anfrage/Sekunde, mit Cache)."""
import json
import time
import urllib.parse
import urllib.request

from .config import DATA, load_json, save_json

CACHE = DATA / "geocode_cache.json"
UA = "wien-wohnungssuche/1.0 (private Wohnungssuche; github.com)"
_cache = None
_last = 0.0


def geocode(adresse):
    """-> (lat, lon) oder None. Adresse z. B. 'Karmeliterplatz 3, 1020 Wien'."""
    global _cache, _last
    if _cache is None:
        _cache = load_json(CACHE, {})
    key = adresse.strip().lower()
    if key in _cache:
        return tuple(_cache[key]) if _cache[key] else None
    q = adresse if "wien" in key else adresse + ", Wien"
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "at",
         "viewbox": "16.18,48.33,16.58,48.11", "bounded": 1})
    time.sleep(max(0, 1.1 - (time.time() - _last)))
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        res = json.load(r)
    _last = time.time()
    _cache[key] = [round(float(res[0]["lat"]), 6), round(float(res[0]["lon"]), 6)] if res else None
    save_json(CACHE, _cache)
    return tuple(_cache[key]) if _cache[key] else None
