"""Neu gezeichnete Grundrisse: data/grundriss_plaene/ID.json -> docs/grundrisse/ID.svg (macht auch `run.py build`).

    python tools/grundriss_zeichnen.py               alle Pläne zeichnen
    python tools/grundriss_zeichnen.py ID --png P    zusätzlich als PNG nach P (zum Ansehen, braucht playwright)
Aufbau eines Plans: wohnungen/grundriss_svg.py.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wohnungen.grundriss_svg import zeichnen  # noqa: E402

PLAENE = ROOT / "data" / "grundriss_plaene"
ZIEL = ROOT / "docs" / "grundrisse"


def alle():
    ZIEL.mkdir(parents=True, exist_ok=True)
    fertig = []
    for p in sorted(PLAENE.glob("*.json")):
        svg = zeichnen(json.loads(p.read_text(encoding="utf-8")))
        z = ZIEL / f"{p.stem}.svg"
        if not z.exists() or z.read_text(encoding="utf-8") != svg:
            z.write_text(svg, encoding="utf-8")
        fertig.append(z)
    return fertig


def png(wid, pfad):
    from playwright.sync_api import sync_playwright
    svg = (ZIEL / f"{wid}.svg").read_text(encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        s = b.new_page(viewport={"width": 1200, "height": 1200})
        s.set_content(f'<body style="margin:0"><div style="width:1200px">{svg}</div>'
                      '<style>svg{width:100%;height:auto;display:block}</style></body>')
        s.wait_for_timeout(300)
        s.locator("svg").screenshot(path=pfad)
        b.close()


if __name__ == "__main__":
    for z in alle():
        print(z.relative_to(ROOT))
    if len(sys.argv) > 2 and sys.argv[2] == "--png":
        png(sys.argv[1], sys.argv[3])
