"""Ausschlüsse nach Zustand und Nutzung (wie heizung.py: eindeutig -> automatisch, sonst Prüfung).

- unbefristet vermietet -> raus (befristet vermietet bleibt drin, mit Hinweis)
- sanierungs-/renovierungsbedürftig oder belagsfertig -> raus ("saniert", "generalsaniert",
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
    # belagsfertig: Böden/Fliesen/Bad fehlen noch -> Käufer muss selbst fertigstellen
    r"|belagsfertig|belagsbereit|edelrohbau|rohbauzustand|ohne (boden)?bel[äa]ge?\b|ohne bodenbelag")
SANIERUNG_SCHWACH = re.compile(
    r"(?i)(?<!kein )(?<!keinen )(?<!ohne )(sanierungs|renovierungs|modernisierungs)bedarf"
    r"|(sanierung|renovierung)\s+(ist\s+)?(erforderlich|notwendig|n[öo]tig)"
    r"|originalzustand|altzustand|nach (ihren|eigenen) (vorstellungen|w[üu]nschen) (sanier|renovier|moderni)"
    r"|reparaturbed[üu]rftig|instandsetzungsbed[üu]rftig|sanierungskosten|veraltet")


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
        art = "nicht fertiggestellt (belagsfertig)" if re.search(r"(?i)belags|rohbau|ohne (boden)?bel", s) else "Sanierung nötig"
        gruende.append(f"{art}: {s}")
    elif s := _stelle(SANIERUNG_SCHWACH, text):
        offen.append(f"Sanierung? {s}")

    if s := _stelle(VERMIETET_STARK, text):
        gruende.append(f"unbefristet vermietet: {s}")
    elif (s := _stelle(VERMIETET_SCHWACH, text)) and not FREI.search(text):
        offen.append(f"vermietet? {s}")
    elif re.search(r"(?i)befristet vermietet|vermietet bis|befristung bis", text):
        hinweise.append("befristet vermietet")

    return {"raus": bool(gruende), "eindeutig": not offen, "gruende": gruende, "offen": offen, "hinweise": hinweise}
