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
_HOST = "nominatim.openstreetmap.org"


def _abruf(url):
    """Nominatim-Anfrage mit 1,1 s Abstand. Bei Sperre/Timeout False (nicht cachen); nach zwei
    Fehlschlägen in Folge fragt der Lauf Nominatim nicht mehr (wie http.get bei den Portalen)."""
    global _last
    from . import http
    if _HOST in http._gesperrt:
        return False
    time.sleep(max(0, 1.1 - (time.time() - _last)))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
            res = json.load(r)
    except (OSError, ValueError):  # URLError, HTTPError, Timeout, kaputtes JSON
        http.fehlschlag(_HOST)
        return False
    finally:
        _last = time.time()
    http.erfolg(_HOST)
    return res


def geocode(adresse):
    """-> (lat, lon) oder None. Adresse z. B. 'Karmeliterplatz 3, 1020 Wien'."""
    global _cache
    if _cache is None:
        _cache = load_json(CACHE, {})
    key = adresse.strip().lower()
    if key in _cache:
        return tuple(_cache[key]) if _cache[key] else None
    q = adresse if "wien" in key else adresse + ", Wien"
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "at",
         "viewbox": "16.18,48.33,16.58,48.11", "bounded": 1})
    res = _abruf(url)
    if res is False:
        return None
    _cache[key] = [round(float(res[0]["lat"]), 6), round(float(res[0]["lon"]), 6)] if res else None
    save_json(CACHE, _cache)
    return tuple(_cache[key]) if _cache[key] else None


BLICK_CACHE = DATA / "strassenblick_cache.json"
_blick = None


def strassenblick(lat, lon):
    """Für Street View: nächster Punkt auf der Straße vor dem Haus und Blickrichtung zum Haus.
    Am Hauspunkt selbst (Hof, Gebäudemitte) zeigt Google oft Nutzerfotos statt der Straßenansicht.
    -> {"lat", "lon", "heading"} oder None (keine Straße in 80 m gefunden)."""
    import math
    global _blick
    if _blick is None:
        _blick = load_json(BLICK_CACHE, {})
    key = f"{lat:.6f},{lon:.6f}"
    if key in _blick:
        return _blick[key]
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 17, "polygon_geojson": 1, "layer": "address"})
    res = _abruf(url)
    if res is False:
        return None
    geo = res.get("geojson") or {}
    linien = [geo["coordinates"]] if geo.get("type") == "LineString" else \
        geo.get("coordinates", []) if geo.get("type") == "MultiLineString" else []
    kx, ky = 111320 * math.cos(math.radians(lat)), 110540
    best = None
    for linie in linien:  # nächster Punkt auf dem Straßenzug (in Metern rechnen)
        for (ax, ay), (bx, by) in zip(linie, linie[1:]):
            ax, ay, bx, by = (ax - lon) * kx, (ay - lat) * ky, (bx - lon) * kx, (by - lat) * ky
            dx, dy = bx - ax, by - ay
            t = 0 if dx == dy == 0 else max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
            px, py = ax + t * dx, ay + t * dy
            d = math.hypot(px, py)
            if best is None or d < best[0]:
                best = (d, px, py)
    if best and best[0] <= 80:
        d, px, py = best
        heading = round((math.degrees(math.atan2(-px, -py)) + 360) % 360)  # vom Straßenpunkt zum Haus
        _blick[key] = {"lat": round(lat + py / ky, 6), "lon": round(lon + px / kx, 6), "heading": heading}
    else:
        _blick[key] = None
    save_json(BLICK_CACHE, _blick)
    return _blick[key]
