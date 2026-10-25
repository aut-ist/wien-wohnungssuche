"""Vorab-Einschätzung der Heizung per Textmuster.

Ergebnis: "gas", "kein_gas" oder "unklar", plus ob das eindeutig ist. Alles,
was nicht eindeutig ist, landet in der Review-Liste für Claude.
"""
import re

GAS_STARK = re.compile(
    r"(?i)\b(erd)?gas[\s-]*(etagen|zentral|kombi|brennwert|wand)?[\s-]*(heizung|therme|kessel|heiztherme|konvektor\w*)"
    r"|\bgastherme|\bgas[\s-]*etagenheizung|heizungsart:\s*gas|energieträger:\s*gas"
    r"|heizung:\s*gas|befeuerung:\s*gas|\bgas-?brennwert")
GAS_SCHWACH = re.compile(r"(?i)\bgas\b|\btherme\b")
KEIN_GAS = re.compile(
    r"(?i)fernwärme|fernheizung|wärmepumpe|erdwärme|geothermie|tiefenbohrung|pellets?\b"
    r"|luft[\s-]*wasser|grundwasser[\s-]*wärme|gasfrei|ohne gas|kein(e|en)? gas|gasausstieg")
NEGATION = re.compile(r"(?i)gasfrei|ohne gas|kein(e|en)?\s+gas|nicht\s+mit\s+gas|gas\w*\s+wurde\s+entfernt")
ETAGEN = re.compile(r"(?i)etagenheizung|zentralheizung")


def _snippets(rx, text, n=3):
    out = []
    for m in rx.finditer(text):
        s = text[max(0, m.start() - 60): m.end() + 60].replace("\n", " ").strip()
        out.append("…" + s + "…")
        if len(out) >= n:
            break
    return out


def einschaetzen(felder, text):
    """-> dict(ergebnis, eindeutig, belege, hinweis)"""
    felder_txt = "\n".join(felder)
    gas_feld = bool(GAS_STARK.search(felder_txt)) or bool(re.search(r"(?i)\bgas\b", felder_txt))
    nicht_gas_feld = bool(KEIN_GAS.search(felder_txt))
    gas_text = bool(GAS_STARK.search(text))
    nicht_gas_text = bool(KEIN_GAS.search(text))
    negiert = bool(NEGATION.search(text + felder_txt))
    belege = list(dict.fromkeys(felder + _snippets(GAS_STARK, text) + _snippets(KEIN_GAS, text)))

    if gas_feld and not (nicht_gas_feld or nicht_gas_text or negiert):
        return {"ergebnis": "gas", "eindeutig": True, "belege": belege}
    if nicht_gas_feld and not (gas_feld or gas_text):
        return {"ergebnis": "kein_gas", "eindeutig": True, "belege": belege}
    if gas_text and not (nicht_gas_feld or nicht_gas_text or negiert):
        return {"ergebnis": "gas", "eindeutig": True, "belege": belege}
    if nicht_gas_text and not (gas_feld or gas_text) and not GAS_SCHWACH.search(text):
        return {"ergebnis": "kein_gas", "eindeutig": True, "belege": belege}
    if gas_feld or gas_text or nicht_gas_feld or nicht_gas_text or GAS_SCHWACH.search(text):
        belege += _snippets(GAS_SCHWACH, text, 2)
        return {"ergebnis": "unklar", "eindeutig": False, "belege": list(dict.fromkeys(belege))}
    hinweis = "Etagenheizung ohne Angabe des Energieträgers (in Wien meist Gas)" \
        if ETAGEN.search(felder_txt + text) and "etagen" in (felder_txt + text).lower() else None
    return {"ergebnis": "unklar", "eindeutig": True, "belege": belege, "hinweis": hinweis}
