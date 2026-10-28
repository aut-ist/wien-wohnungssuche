"""Ausschlüsse nach Zustand und Nutzung (wie heizung.py: eindeutig -> automatisch, sonst Prüfung).

- unbefristet vermietet -> raus; befristet vermietet über Q1 2027 hinaus -> raus (Wunsch), bis
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


# befristet vermietet: bis Ende März 2027 ist ok, länger nicht
MIETE_GRENZE = (2027, 3)
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
            gruende.append(f"vermietet bis {wann}, also länger als Q1 2027: {s}")
        elif monat is None and jahr == MIETE_GRENZE[0]:
            offen.append(f"vermietet bis {wann}, Monat unklar: {s}")
        else:
            hinweise.append(f"befristet vermietet bis {wann}")
    elif (s := _stelle(VERMIETET_SCHWACH, text)) and not FREI.search(text):
        offen.append(f"vermietet? {s}")
    elif re.search(r"(?i)befristet vermietet|vermietet bis|befristung bis", text):
        hinweise.append("befristet vermietet")

    return {"raus": bool(gruende), "eindeutig": not offen, "gruende": gruende, "offen": offen, "hinweise": hinweise}
