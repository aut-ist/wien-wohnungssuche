"""Ausschlüsse nach Zustand und Nutzung (wie heizung.py: eindeutig -> automatisch, sonst Prüfung).

- unbefristet vermietet -> raus; befristet vermietet über Q3 2027 hinaus -> raus (Wunsch), bis
  dahin bleibt drin, mit Hinweis
- sanierungs-/renovierungsbedürftig, teilsaniert oder belagsfertig -> raus ("saniert", "generalsaniert",
  "schlüsselfertig" sind positiv und bleiben)
"""
import re

ZUSTAND_SCHLECHT = re.compile(r"(?i)sanierungsbed|renovierungsbed|modernisierungsbed|abbruch|needs? renovation|in need of"
                              r"|belagsfertig|rohbau")

VERMIETET_STARK = re.compile(
    r"(?i)unbefristet\w*[^.\n]{0,40}(vermietet|vermietung|miet|bestand)"
    r"|vermietet[^.\n]{0,50}unbefristet|unbefristete[snm]?\s+(haupt)?(miet|bestand)")
VERMIETET_SCHWACH = re.compile(
    r"(?i)\bvermietet\b|\bmieter(in)?\b|anlegerwohnung|vorsorgewohnung|\brendite\b|hauptmietzins|mietertrag|zinsliste")
FREI = re.compile(r"(?i)bestands?frei|unvermietet|nicht vermietet|leerstehend|sofort beziehbar|bezugsfertig|frei ab|eigennutz")

SANIERUNG_STARK = re.compile(
    r"(?i)(?<!nicht )(?<!kaum )sanierungsbed[üu]rftig|(?<!nicht )renovierungsbed[üu]rftig|modernisierungsbed[üu]rftig"
    r"|sanierungsobjekt|renovierungsobjekt|f[üu]r (handwerker|bastler)|handwerkerwohnung|abbruchreif"
    r"|rohdachboden|im rohbau|muss (komplett |vollständig |noch )?(saniert|renoviert) werden"
    r"|zu sanierende|sanierungsfall"
    # teilsaniert/teilrenoviert: Rest muss man selbst machen (Wunsch: raus); "Dachteilsanierung" zählt nicht
    r"|(?<![a-zäöüß])teil\s*-?\s*(sanier|renovier|moderni)\w*|teilweise\s+(saniert|renoviert|modernisiert)"
    # belagsfertig: Böden/Fliesen/Bad fehlen noch -> Käufer muss selbst fertigstellen
    r"|belagsfertig|belagsbereit|edelrohbau|rohbauzustand|ohne (boden)?bel[äa]ge?\b|ohne bodenbelag")
SANIERUNG_SCHWACH = re.compile(
    r"(?i)(?<!kein )(?<!keinen )(?<!ohne )(sanierungs|renovierungs|modernisierungs)bedarf"
    r"|(sanierung|renovierung)\s+(ist\s+)?(erforderlich|notwendig|n[öo]tig)"
    r"|originalzustand|altzustand|nach (ihren|eigenen) (vorstellungen|w[üu]nschen) (sanier|renovier|moderni)"
    r"|reparaturbed[üu]rftig|instandsetzungsbed[üu]rftig|sanierungskosten|veraltet")


# befristet vermietet: bis Ende September 2027 ist ok, länger nicht
MIETE_GRENZE = (2027, 9)  # bis Ende September 2027 (seit 2026-10-28, wie der Einzug)
_MONATE = {m: i + 1 for i, m in enumerate(["jän", "feb", "mär", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "dez"])}
_MONATE.update({"jan": 1, "mar": 3})
MIETE_BIS = [  # "befristet vermietet bis 30.11.2027" und "bis 30.11.2027 befristet vermietet"
    re.compile(r"(?i)(?:befrist\w*|vermietet|mietvertr\w*|mietverh[äa]ltnis\w*)[^.\n]{0,60}?\bbis\s+"
               r"(?:zum\s+|ende\s+|anfang\s+|mitte\s+|ca\.\s+|voraussichtlich\s+)?([^\n,;)]{0,25})"),
    re.compile(r"(?i)\bbis\s+(?:zum\s+|ende\s+)?([^\n,;)]{0,25}?)\s+(?:befristet|vermietet)"),
]


def miete_bis(text):
    """-> (jahr, monat oder None, Textstelle) für "befristet vermietet bis …", sonst None."""
    for rx in MIETE_BIS:
        for m in rx.finditer(text):
            if re.search(r"(?i)garage|stellpl|parkpl|keller", text[max(0, m.start() - 40): m.end()]):
                continue  # vermieteter Garagenplatz o. Ä., nicht die Wohnung
            s = m.group(1).lower()
            stelle = "…" + text[max(0, m.start() - 20): m.end() + 10].replace("\n", " ").strip() + "…"
            if d := re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s):
                return int(d.group(3)), int(d.group(2)), stelle
            if d := re.search(r"(\d{1,2})\s*/\s*(\d{4})", s):
                return int(d.group(2)), int(d.group(1)), stelle
            if d := re.search(r"q\s*([1-4])\D{0,3}(\d{4})", s):
                return int(d.group(2)), int(d.group(1)) * 3, stelle
            if d := re.search(r"([a-zä]{3})[a-zä]*\s+(\d{4})", s):
                if d.group(1) in _MONATE:
                    return int(d.group(2)), _MONATE[d.group(1)], stelle
            if d := re.search(r"\b(20\d\d)\b", s):
                ende = re.search(r"(?i)ende\s+" + d.group(1), m.group(0))
                return int(d.group(1)), 12 if ende else None, stelle
    return None


# Einzug spätestens Q3 2027 (Wunsch): Neubauten mit späterer Fertigstellung -> raus
from .config import CONFIG
EINZUG_GRENZE = tuple(int(x) for x in CONFIG["filter"]["einzug_spaetestens"].split("-"))
FERTIG = re.compile(r"(?i)\b(fertigstellung\w*|fertiggestellt|bezugsfertig\w*|bezugstermin|erstbezug|bezug|übergabe|wohnungsübergabe"
                    r"|einzug|einzugstermin|baufertigstellung|fertig\b|verfügbar ab|bezugsbereit|completion|move[- ]in)")
_NICHT_WOHNUNG = re.compile(r"(?i)\bu\d\b|u-bahn|linie|station|haltestelle|straßenbahn|schule|campus|kindergarten"
                            r"|fassade|spital|akh|krankenhaus|\bpark\b|garage|stellpl|lift|aufzug|balkon"
                            r"|energie|ausweis|gültig|hwb|befrist|miet|kredit|finanzier|förder|garantie|gewährleist")
_ZEIT = [(re.compile(r"(?i)q\s*([1-4])|([1-4])\.\s*quartal"), lambda m: int(m.group(1) or m.group(2)) * 3),
         (re.compile(r"(?i)\b(\d{1,2})\s*[./]\s*20\d\d"), lambda m: int(m.group(1))),
         (re.compile(r"(?i)frühjahr|frühling"), lambda m: 5), (re.compile(r"(?i)sommer"), lambda m: 8),
         (re.compile(r"(?i)herbst"), lambda m: 11), (re.compile(r"(?i)winter"), lambda m: 12),
         (re.compile(r"(?i)anfang"), lambda m: 3), (re.compile(r"(?i)mitte"), lambda m: 6),
         (re.compile(r"(?i)ende"), lambda m: 12),
         (re.compile(r"(?i)\b(jän|jan|feb|mär|mar|apr|mai|jun|jul|aug|sep|okt|nov|dez)[a-zä]*\.?\s+20\d\d"),
          lambda m: _MONATE[m.group(1).lower()])]


def bezug_ab(text):
    """-> (jahr, monat oder None, Textstelle) für "Fertigstellung/Bezug Ende 2028" o. Ä. (ab 2027), sonst None."""
    jahr_rx = re.compile(r"\b20(2[7-9]|3\d)\b")
    funde = []
    for m in FERTIG.finditer(text):
        # Jahr bevorzugt nach dem Stichwort ("Fertigstellung März 2029"), sonst kurz davor
        # ("Ende 2028 fertiggestellt"); so stört "Baubeginn Q3 2027" davor nicht
        if j := jahr_rx.search(text, m.end(), m.end() + 60):
            fenster = text[m.start(): j.end()]
        elif js := list(jahr_rx.finditer(text, max(0, m.start() - 40), m.start())):
            fenster = text[max(0, js[-1].start() - 25): m.end()]
            j = js[-1]
        else:
            continue
        if _NICHT_WOHNUNG.search(fenster):
            continue
        # Arbeiten im Dachgeschoß betreffen eine Altbauwohnung darunter nicht
        if re.search(r"(?i)dach", fenster) and not re.search(r"(?i)dach|\bDG\b|penthouse|maisonette", text.split("\n", 1)[0]):
            continue
        monat = None
        for rx, f in _ZEIT:
            if z := rx.search(fenster):
                monat = f(z)
                break
        funde.append((int(j.group(0)), monat, "…" + fenster.replace("\n", " ").strip() + "…"))
    # mehrere Termine (Baubeginn, Fertigstellung, Bezug): der späteste zählt
    return max(funde, key=lambda f: (f[0], f[1] or 0)) if funde else None


def _stelle(rx, text):
    m = rx.search(text)
    if not m:
        return None
    return "…" + text[max(0, m.start() - 60): m.end() + 60].replace("\n", " ").strip() + "…"


def einschaetzen(r):
    """-> dict(raus: bool, eindeutig: bool, gruende: [...], hinweise: [...])"""
    text = f"{r.get('titel') or ''}\n{r.get('text') or ''}"
    zustand = str(r.get("zustand") or "")
    gruende, hinweise, offen = [], [], []

    if ZUSTAND_SCHLECHT.search(zustand):
        gruende.append(f"Zustand: {zustand}")
    elif s := _stelle(SANIERUNG_STARK, text):
        art = ("nicht fertiggestellt (belagsfertig)" if re.search(r"(?i)belags|rohbau|ohne (boden)?bel", s)
               else "nur teilsaniert" if re.search(r"(?i)(?<![a-zäöüß])teil(weise)?\s*-?\s*(sanier|renovier|moderni)", s) else "Sanierung nötig")
        gruende.append(f"{art}: {s}")
    elif s := _stelle(SANIERUNG_SCHWACH, text):
        offen.append(f"Sanierung? {s}")

    if s := _stelle(VERMIETET_STARK, text):
        gruende.append(f"unbefristet vermietet: {s}")
    elif bis := miete_bis(text):
        jahr, monat, s = bis
        wann = f"{monat:02d}/{jahr}" if monat else str(jahr)
        if (jahr, monat or 0) > MIETE_GRENZE and (monat or jahr > MIETE_GRENZE[0]):
            gruende.append(f"vermietet bis {wann}, also länger als Q3 2027: {s}")
        elif monat is None and jahr == MIETE_GRENZE[0]:
            offen.append(f"vermietet bis {wann}, Monat unklar: {s}")
        else:
            hinweise.append(f"befristet vermietet bis {wann}")
    elif (s := _stelle(VERMIETET_SCHWACH, text)) and not FREI.search(text):
        offen.append(f"vermietet? {s}")
    elif re.search(r"(?i)befristet vermietet|vermietet bis|befristung bis", text):
        hinweise.append("befristet vermietet")

    if b := bezug_einschaetzen(text, r.get("baujahr")):
        {"raus": gruende, "offen": offen, "hinweis": hinweise}[b[0]].append(b[1])

    return {"raus": bool(gruende), "eindeutig": not offen, "gruende": gruende, "offen": offen, "hinweise": hinweise}


def bezug_einschaetzen(text, baujahr=None):
    """Fertigstellung/Bezug nach Q3 2027 -> ("raus", Grund); 2027 ohne Monat -> ("offen", …); sonst ("hinweis", …).
    Ohne Angabe im Text zählt das Baujahr-Feld (bei Neubauten das geplante Fertigstellungsjahr)."""
    if not (b := bezug_ab(text)):
        try:
            baujahr = int(str(baujahr)[:4])
        except ValueError:
            return None
        if not EINZUG_GRENZE[0] <= baujahr <= 2035:
            return None
        b = (baujahr, None, f"Baujahr {baujahr} laut Inserat (Neubau, noch nicht fertig)")
    jahr, monat, s = b
    wann = f"{monat:02d}/{jahr}" if monat else str(jahr)
    if jahr > EINZUG_GRENZE[0] or (jahr == EINZUG_GRENZE[0] and (monat or 0) > EINZUG_GRENZE[1]):
        return "raus", f"Einzug erst {wann}, später als Q3 2027: {s}"
    if monat is None and jahr == EINZUG_GRENZE[0]:
        return "offen", f"Fertigstellung {wann}, Monat unklar: {s}"
    return "hinweis", f"Fertigstellung/Bezug {wann}"
