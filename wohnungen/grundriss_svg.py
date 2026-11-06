"""Zeichnet einen sauberen Grundriss als SVG aus einer Raumliste (Wunsch 2026-11-06: abfotografierte,
technische oder bekritzelte Pläne neu zeichnen und als zweites Foto zeigen). Nur Standardbibliothek, damit
die Cloud-Routine und `run.py build` es ohne Installation können.

Plan (data/grundriss_plaene/ID.json), alle Maße in Metern, x nach rechts, y nach unten:
    {
      "ids": ["wh-1", "is-2"],            Inserate der Wohnung (wie in docs/listings.json)
      "ersetzt": ["https://…"],           die hässlichen Original-Pläne (kommen ans Ende der Fotos)
      "titel": "Grundriss Top 12",        optional
      "raeume": [
        {"name": "Wohnzimmer", "m2": 23.4, "art": "wohnen",
         "punkte": [[0, 0], [5.2, 0], [5.2, 4.5], [0, 4.5]],
         "beschriftung": [2.6, 2.2]}       optional, sonst Flächenschwerpunkt
      ],
      "fenster": [[[0.8, 0], [2.0, 0]]],   Strecke auf einer Wand
      "tueren": [{"von": [5.2, 1.0], "bis": [5.2, 1.9], "seite": 1}],   seite: 1/-1 = Aufschlagrichtung,
                                           "offen": true = Durchgang ohne Türblatt
      "texte": [{"text": "Galerie", "pos": [12, -0.5]}],   optional, Überschriften (Ebenen nebeneinander legen)
      "wohnflaeche": 91.01,                optional: Gesamtfläche laut Plan (sonst Summe, nur wenn jeder Raum m² hat)
      "hinweis": "…"                       optional, sonst Standardhinweis
    }
Die Texte zählen nicht zum Rahmen: Überschriften innerhalb der Raumfläche oder knapp darüber setzen.
art: wohnen, schlafen, zimmer, kueche, bad, wc, flur, abstell, freiflaeche (Balkon/Loggia/Terrasse/Garten).
"""
import html
import math

FARBEN = {
    "wohnen": "#f4e9d6", "zimmer": "#f4e9d6", "schlafen": "#e9eef5", "kueche": "#f3e2c3",
    "bad": "#dcecf3", "wc": "#dcecf3", "flur": "#efefec", "abstell": "#e6e6e2", "freiflaeche": "#e3f0da",
}
WAND = "#2f2f2f"
WAND_M = 0.14
TEXT = "#2b2b2b"


def _flaeche_schwerpunkt(p):
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(p, p[1:] + p[:1]):
        k = x1 * y2 - x2 * y1
        a += k
        cx += (x1 + x2) * k
        cy += (y1 + y2) * k
    if abs(a) < 1e-9:
        return sum(x for x, _ in p) / len(p), sum(y for _, y in p) / len(p)
    return cx / (3 * a), cy / (3 * a)


def _m2(v):
    return f"{v:.2f}".replace(".", ",") + " m²"


def zeichnen(plan):
    """Plan -> SVG-Text."""
    raeume = plan["raeume"]
    pkt = [q for r in raeume for q in r["punkte"]]
    x0, y0 = min(x for x, _ in pkt), min(y for _, y in pkt)
    x1, y1 = max(x for x, _ in pkt), max(y for _, y in pkt)
    breite, hoehe = x1 - x0, y1 - y0
    s = 100.0  # 1 m = 100 Einheiten
    rand = max(breite, hoehe) * 0.06 * s + 40
    gross = max(breite, hoehe)
    schrift = max(22.0, min(40.0, gross * 3.1))
    fuss = 60 + schrift * 4.6  # Titel, Flächen, Hinweis, darunter der Maßstab
    W, H = breite * s + 2 * rand, hoehe * s + 2 * rand + fuss
    # schmale Pläne: Seite so breit, dass der Hinweis passt, Zeichnung in der Mitte
    dx = max(0.0, (34 * schrift - W) / 2)
    W += 2 * dx

    def P(q):
        return (q[0] - x0) * s + rand + dx, (q[1] - y0) * s + rand

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
         f'font-family="Helvetica, Arial, sans-serif">', f'<rect width="{W:.0f}" height="{H:.0f}" fill="#ffffff"/>']
    # Räume: Fläche, dann Wände darüber (gemeinsame Wände decken sich)
    for r in raeume:
        pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in map(P, r["punkte"]))
        frei = r.get("art") == "freiflaeche"
        o.append(f'<polygon points="{pts}" fill="{FARBEN.get(r.get("art"), FARBEN["zimmer"])}" '
                 f'stroke="none"/>')
        strich = ' stroke-dasharray="18 10"' if frei else ""
        o.append(f'<polygon points="{pts}" fill="none" stroke="{"#7a8f6e" if frei else WAND}" '
                 f'stroke-width="{(0.06 if frei else WAND_M) * s:.1f}" stroke-linejoin="miter"{strich}/>')
    for f in plan.get("fenster") or []:
        (a, b), (c, d) = P(f[0]), P(f[1])
        o.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{c:.1f}" y2="{d:.1f}" stroke="#ffffff" '
                 f'stroke-width="{WAND_M * s - 2:.1f}"/>')
        o.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{c:.1f}" y2="{d:.1f}" stroke="#6fa7cf" stroke-width="4"/>')
    for t in plan.get("tueren") or []:
        (a, b), (c, d) = P(t["von"]), P(t["bis"])
        o.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{c:.1f}" y2="{d:.1f}" stroke="#ffffff" '
                 f'stroke-width="{WAND_M * s + 2:.1f}"/>')
        laenge = math.hypot(c - a, d - b)
        if laenge < 1 or t.get("offen"):  # "offen": Durchgang ohne Türblatt
            continue
        ux, uy = (c - a) / laenge, (d - b) / laenge
        nx, ny = -uy * t.get("seite", 1), ux * t.get("seite", 1)
        ex, ey = a + nx * laenge, b + ny * laenge
        o.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{WAND}" stroke-width="3"/>')
        gross_bogen = 0
        dreh = 1 if (ux * ny - uy * nx) < 0 else 0
        o.append(f'<path d="M {ex:.1f} {ey:.1f} A {laenge:.1f} {laenge:.1f} 0 {gross_bogen} {dreh} {c:.1f} {d:.1f}" '
                 f'fill="none" stroke="#9a9a9a" stroke-width="2" stroke-dasharray="6 5"/>')
    for r in raeume:
        bx, by = P(r.get("beschriftung") or _flaeche_schwerpunkt(r["punkte"]))
        xs = [q[0] for q in r["punkte"]]
        klein = (max(xs) - min(xs)) < 1.6
        fs = schrift * (0.72 if klein else 1)
        o.append(f'<text x="{bx:.1f}" y="{by - fs * 0.15:.1f}" font-size="{fs:.1f}" font-weight="700" '
                 f'fill="{TEXT}" text-anchor="middle">{html.escape(r["name"])}</text>')
        if r.get("m2"):
            o.append(f'<text x="{bx:.1f}" y="{by + fs * 0.95:.1f}" font-size="{fs * 0.82:.1f}" fill="#555" '
                     f'text-anchor="middle">{_m2(r["m2"])}</text>')
    for t in plan.get("texte") or []:  # z. B. "Galerie" über der zweiten Ebene einer Maisonette
        tx, ty = P(t["pos"])
        o.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{schrift * 1.05:.1f}" font-weight="700" fill="#666" '
                 f'text-anchor="{t.get("ausrichtung", "start")}">{html.escape(t["text"])}</text>')
    # Fuß: Titel, Fläche, Hinweis, Maßstab
    fy = hoehe * s + 2 * rand
    # Summe nur, wenn jeder Raum eine Fläche hat (sonst wäre sie zu klein); "wohnflaeche" aus dem Plan geht vor
    innen_r = [r for r in raeume if r.get("art") != "freiflaeche"]
    innen = plan.get("wohnflaeche") or (sum(r["m2"] for r in innen_r) if all(r.get("m2") for r in innen_r) else 0)
    frei = sum(r.get("m2") or 0 for r in raeume if r.get("art") == "freiflaeche")
    zeile = plan.get("titel") or "Grundriss"
    werte = " · ".join(x for x in [f"Wohnfläche ca. {_m2(innen)}" if innen else "",
                                   f"Freifläche ca. {_m2(frei)}" if frei else ""] if x)
    hinweis = plan.get("hinweis") or "Neu gezeichnet nach den Plänen im Inserat, Maße ungefähr. Originale am Ende der Fotos."
    lx = rand + dx
    o.append(f'<text x="{lx:.1f}" y="{fy + 20:.1f}" font-size="{schrift * 1.15:.1f}" font-weight="700" fill="{TEXT}">'
             f'{html.escape(zeile)}</text>')
    if werte:
        o.append(f'<text x="{lx:.1f}" y="{fy + 20 + schrift * 1.35:.1f}" font-size="{schrift * 0.9:.1f}" fill="#444">'
                 f'{html.escape(werte)}</text>')
    o.append(f'<text x="{lx:.1f}" y="{fy + 20 + schrift * 2.6:.1f}" font-size="{schrift * 0.7:.1f}" fill="#888">'
             f'{html.escape(hinweis)}</text>')
    mx, my = lx, fy + 20 + schrift * 3.6
    o.append(f'<rect x="{mx:.1f}" y="{my - 8:.1f}" width="{s:.1f}" height="10" fill="{WAND}"/>'
             f'<rect x="{mx + s:.1f}" y="{my - 8:.1f}" width="{s:.1f}" height="10" fill="#ffffff" stroke="{WAND}" stroke-width="2"/>'
             f'<text x="{mx:.1f}" y="{my + schrift * 0.9:.1f}" font-size="{schrift * 0.65:.1f}" fill="#666">0</text>'
             f'<text x="{mx + 2 * s:.1f}" y="{my + schrift * 0.9:.1f}" font-size="{schrift * 0.65:.1f}" fill="#666" '
             f'text-anchor="end">2 m</text>')
    o.append("</svg>")
    return "\n".join(o)
