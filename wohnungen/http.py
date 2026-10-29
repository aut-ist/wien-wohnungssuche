import json
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")

_last = {}  # letzte Anfrage pro Host: Pausen gelten je Portal, Portale laufen parallel
_lock = threading.Lock()

# Schutz vor Endlos-Läufen (2026-10-29: derStandard 403 und FindMyHome-Timeouts gegen GitHub Actions
# kosteten je Seite Minuten, der Lauf wurde nach 2 h abgebrochen und nichts gespeichert):
# - nach SPERRE_NACH Fehlschlägen (403/Timeout) in Folge gilt ein Host für den Rest des Laufs als gesperrt
# - nach SCRAPE_MAX_MIN Minuten (Umgebungsvariable, Standard 75) bricht jede Anfrage sofort ab,
#   damit der Lauf noch speichert, bevor GitHub ihn beendet
SPERRE_NACH = 2
_fehler_folge, _gesperrt = {}, set()
_ENDE = time.time() + float(__import__("os").environ.get("SCRAPE_MAX_MIN", "75")) * 60


class Gesperrt(Exception):
    """Host gesperrt oder Zeitbudget aufgebraucht: heute nicht weiter versuchen."""


def pruefen(host):
    if host in _gesperrt:
        raise Gesperrt(f"{host} heute gesperrt (wiederholt 403/Timeout)")
    if time.time() > _ENDE:
        raise Gesperrt("Zeitbudget des Laufs aufgebraucht")


def fehlschlag(host):
    with _lock:
        _fehler_folge[host] = _fehler_folge.get(host, 0) + 1
        if _fehler_folge[host] >= SPERRE_NACH and host not in _gesperrt:
            _gesperrt.add(host)
            print(f"{host}: {SPERRE_NACH} Fehlschläge in Folge, für den Rest des Laufs übersprungen", flush=True)


def erfolg(host):
    with _lock:
        _fehler_folge[host] = 0


def _warten(host, pause):
    with _lock:
        jetzt = time.time()
        start = max(jetzt, _last.get(host, 0) + random.uniform(*pause))
        _last[host] = start
    if start > jetzt:
        time.sleep(start - jetzt)


def get(url, headers=None, pause=(1.0, 2.0), retries=3, data=None):
    """GET (oder POST mit data) mit Browser-User-Agent, Pause pro Host und Wiederholung."""
    host = urllib.parse.urlsplit(url).netloc
    h = {"User-Agent": UA, "Accept-Language": "de-AT,de;q=0.9"}
    h.update(headers or {})
    for attempt in range(retries):
        pruefen(host)
        _warten(host, pause)
        try:
            req = urllib.request.Request(url, headers=h, data=data)
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", errors="replace")
            erfolg(host)
            return text
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                erfolg(host)
                return None
            if e.code in (403, 429):  # Sperre: Wiederholen bringt nichts
                fehlschlag(host)
                raise
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            fehlschlag(host)
            if attempt == retries - 1 or host in _gesperrt:
                raise
        time.sleep(5 * (attempt + 1))


def numid(s):
    """Stabile Ziffern-ID für Portale mit nicht-numerischen IDs (die Datenbankregeln
    für gemeinsame Markierungen erlauben nur Ziffern)."""
    s = str(s)
    if s.isdigit() and 4 <= len(s) <= 15:
        return s
    import hashlib
    return str(int(hashlib.sha1(s.encode()).hexdigest(), 16) % 10**12).zfill(12)


def next_data(html):
    """Das eingebettete Next.js-JSON einer Seite."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None
