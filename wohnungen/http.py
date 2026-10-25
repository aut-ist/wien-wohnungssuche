import json
import random
import re
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")

_last = 0.0


def get(url, headers=None, pause=(1.0, 2.0), retries=3):
    """GET mit Browser-User-Agent, Pause zwischen Requests und Wiederholung."""
    global _last
    wait = random.uniform(*pause) - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    h = {"User-Agent": UA, "Accept-Language": "de-AT,de;q=0.9"}
    h.update(headers or {})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                _last = time.time()
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            _last = time.time()
            if e.code in (404, 410):
                return None
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(5 * (attempt + 1))


def next_data(html):
    """Das eingebettete Next.js-JSON einer Seite."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None
