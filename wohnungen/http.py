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
        _warten(host, pause)
        try:
            req = urllib.request.Request(url, headers=h, data=data)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
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
