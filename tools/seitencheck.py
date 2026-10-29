"""Seitencheck: öffnet die gebaute Karte (docs/) in einem echten Browser wie ein iPhone und prüft,
ob sie lädt (keine JS-Fehler, Eier auf der Karte, Karten in der Liste) und nicht zu schwer wird.
Am 2026-10-29 stürzte die Seite am iPhone ab ("wiederholt ein Problem"), weil die Liste 1.169 Fotos
auf einmal enthielt; das soll hier auffallen, bevor es am Handy auffällt.

Ergebnis -> data/seitencheck.json; die Morgen-Routine meldet Probleme ganz oben.
Braucht playwright (pip install playwright && python -m playwright install --with-deps chromium).
Aufruf: python tools/seitencheck.py
"""
import datetime as dt
import json
import pathlib
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = pathlib.Path(__import__("os").environ.get("SEITENCHECK_DOCS") or ROOT / "docs")
ZIEL = ROOT / "data" / "seitencheck.json"
GRENZEN = {"bilder_geladen": 150, "dom": 8000, "listings_mb": 6.0, "heap_mb": 250}


def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    from playwright.sync_api import sync_playwright
    port = freier_port()
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                            "--directory", str(DOCS)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    probleme, werte, fehler = [], {}, []
    try:
        time.sleep(1)
        werte["listings_mb"] = round((DOCS / "listings.json").stat().st_size / 1e6, 2)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(**p.devices["iPhone 13"])
            page = ctx.new_page()
            page.on("pageerror", lambda e: fehler.append(f"JS-Fehler: {e}"))
            page.on("console", lambda m: fehler.append(f"Konsole: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text and "net::" not in m.text else None)
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load", timeout=60000)
            page.wait_for_timeout(6000)
            messen = """() => ({
                eier: document.querySelectorAll('.ei-icon').length,
                karten: document.querySelectorAll('.karte').length,
                bilder_geladen: [...document.images].filter(i => i.getAttribute('src')).length,
                dom: document.getElementsByTagName('*').length,
                heap_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null })"""
            werte.update(page.evaluate(messen))
            # wie beim Durchscrollen: ein paar Mal "weitere laden", dann nochmal messen
            for _ in range(3):
                if not page.evaluate("() => { const m = document.querySelector('.mehr-laden'); if (m) m.click(); return !!m; }"):
                    break
                page.wait_for_timeout(800)
            nach = page.evaluate(messen)
            werte.update({f"{k}_gescrollt": v for k, v in nach.items()})
            browser.close()
    except Exception as e:  # Seite lädt gar nicht / Browser fehlt
        probleme.append(f"Seitencheck selbst fehlgeschlagen: {e}")
    finally:
        srv.terminate()

    probleme += fehler[:5]
    if werte.get("eier", 0) < 20:
        probleme.append(f"nur {werte.get('eier', 0)} Eier auf der Karte")
    if not werte.get("karten"):
        probleme.append("keine Wohnungen in der Liste")
    for k, grenze in GRENZEN.items():
        for kk in (k, f"{k}_gescrollt"):
            if werte.get(kk) is not None and werte[kk] > grenze:
                probleme.append(f"{kk} = {werte[kk]} (Grenze {grenze}): Seite wird am Handy zu schwer")
    ergebnis = {"datum": dt.date.today().isoformat(), "zeit": dt.datetime.now().strftime("%H:%M"),
                "ok": not probleme, "probleme": probleme, "werte": werte}
    ZIEL.write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
    print(("Seitencheck OK " if ergebnis["ok"] else "SEITENCHECK PROBLEM: " + "; ".join(probleme)) + f" {werte}")


if __name__ == "__main__":
    main()
