"""Ortung per Entfernungs-/Gehzeitangaben aus Inseraten: Rastersuche gegen echte Orte (Schulen,
Kindergärten, Haltestellen, U-Bahn) aus den offenen Daten der Stadt Wien. Für die Nest-Recherche."""
import json, math, urllib.request
def wfs(t):
    u = f"https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0&typeName=ogdwien:{t}&srsName=EPSG:4326&outputFormat=json"
    return [(f['properties'], f['geometry']['coordinates'][1], f['geometry']['coordinates'][0]) for f in json.load(urllib.request.urlopen(u, timeout=120))['features']]
S = wfs('SCHULEOGD'); K = wfs('KINDERGARTENOGD')
def m(a, b, c, d): return math.hypot((a - c) * 111320, (b - d) * 74200)
def naechst(lat, lon, items):
    return min(((m(lat, lon, a, b), i) for i, (p, a, b) in enumerate(items)), key=lambda x: x[0]) if items else (9e9, None)
G = json.load(open(__import__("pathlib").Path(__file__).resolve().parent.parent / "geo" / "guertel_zeiten.json", encoding="utf-8"))
STOPS = [(s, s['lat'], s['lon']) for s in G['haltestellen'].values()]
U = [(n, z['lat'], z['lon']) for n, z in G['ziele'].items()]
VS = [x for x in S if 'Volksschule' in (x[0]['ART_TXT'] or '')]
AHS = [x for x in S if 'höhere Schule' in (x[0]['ART_TXT'] or '')]
MS = [x for x in S if 'Mittelschule' in (x[0]['ART_TXT'] or '')]
def stop(name): return [x for x in STOPS if x[0]['name'] == name]
def suche(c, radius, kosten, n=6):
    best = []
    for i in range(-60, 61):
        for j in range(-60, 61):
            lat = c[0] + i * 0.0001; lon = c[1] + j * 0.00014
            if m(lat, lon, *c) > radius: continue
            best.append((kosten(lat, lon), lat, lon))
    best.sort()
    return best[:n]
