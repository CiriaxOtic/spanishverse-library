"""Clasifica los efectos que traen, crean, invocan o copian cartas durante la partida.

Para cada oración del efecto (en inglés) devuelve pares (desde, cómo):
  desde: "nueva", "mazo", "mano", "cementerio", "campo", "rival"
  cómo:  "azar", "eleccion", "especifica", "condicion"
Es una lectura del texto por patrones: puede haber algún caso dudoso.
"""
import re

SOURCES = {"nueva": "Nueva", "mazo": "Del mazo", "mano": "De la mano",
           "cementerio": "Del cementerio", "campo": "Del campo", "rival": "Del rival"}
MODES = {"azar": "Al azar", "eleccion": "A elección", "especifica": "Carta específica", "condicion": "Por condición"}

CARD_WORDS = r"(?:cards?|followers?|spells?|amulets?)"
CONDITION = re.compile(r"\b(cost(s|ing)?|with|that|named|of the same|highest|lowest|differently named|"
                       r"forestcraft|swordcraft|runecraft|dragoncraft|abysscraft|havencraft|portalcraft|neutral)\b")
PLAIN_DRAW = re.compile(r"^\s*(?:then\s+)?draw (?:a|an|\d+|x|that many)\s+cards?\b(?!\s+(?:with|that|costing|of))")


def _strip(s):
    return re.sub(r"<[^>]+>", "", s or "")


def _named(raw_sentence, card_names):
    """Nombres de cartas que aparecen resaltados en la oración (marcado <color=Keyword> del juego)."""
    found = []
    for w in re.findall(r"<color=Keyword>(.*?)</color>", raw_sentence):
        w = _strip(w).strip().lower()
        if w in card_names:
            found.append(w)
    return found


def classify(text, card_names):
    """Conjunto de pares (desde, cómo) que describen cómo esta carta trae o crea cartas."""
    pairs = set()
    if not text:
        return pairs
    for raw in re.split(r"(?<=[.!])\s+|\n|<hr>", text):
        s = _strip(raw).lower().strip()
        if not s:
            continue
        named = _named(raw, card_names)
        copy = re.search(r"\bcop(y|ies)\b", s)
        summon = re.search(r"\bsummon", s)
        add_hand = re.search(r"\badd\b.*\bto (?:your|their) hand\b", s)
        into_deck = re.search(r"\b(?:put|shuffle)\b.*\binto (?:your|their) deck\b", s)
        transform = re.search(r"\btransform\b.*\binto\b", s)
        draw = re.search(r"\bdraw\b", s) and not PLAIN_DRAW.search(s)
        reanimate = re.search(r"\breanimate\b", s)
        if not (copy or summon or add_hand or into_deck or transform or draw or reanimate):
            continue
        # "draw" solo cuenta si es una búsqueda con condición ("draw a follower", "draw a card that costs...").
        if draw and not (summon or add_hand or into_deck or transform or copy or reanimate):
            if not re.search(rf"\bdraw\b[^.]*\b{CARD_WORDS}\b", s) or not (CONDITION.search(s) or re.search(r"\bdraw (?:a|an|\d+) (?:followers?|spells?|amulets?)\b", s)):
                continue

        # Desde dónde.
        if re.search(r"\b(opponent'?s?|enemy)\b", s) and (copy or add_hand or summon) and not re.search(r"\bdeal\b", s.split("summon")[0] if summon else ""):
            src = "rival" if re.search(r"opponent'?s? (hand|deck|cemetery)|enemy (follower|amulet|card)s? (on the field|destroyed)|cop(y|ies) of (?:an? |the )?(?:random )?enemy", s) else None
        else:
            src = None
        if src is None:
            if reanimate or re.search(r"destroyed this match|from your cemetery|in your cemetery", s):
                src = "cementerio"
            elif re.search(r"from (?:your|their) deck|in your deck\b", s) or (draw and not (summon or add_hand)):
                src = "mazo"
            elif re.search(r"from (?:your|their) hand|in your hand\b", s) and (summon or copy):
                src = "mano"
            elif copy and re.search(r"\b(on the field|allied|this follower|this card|it)\b", s) and not named:
                src = "campo"
            elif summon or add_hand or into_deck or transform or copy:
                src = "nueva"
            else:
                continue

        # Cómo.
        if "random" in s.split()[0:0] or re.search(r"\brandom\b", s) or reanimate:
            how = "azar"
        elif re.search(r"\b(select|choose)\b", s):
            how = "eleccion"
        elif named and src == "nueva":
            how = "especifica"
        elif CONDITION.search(s) or src in ("mazo", "cementerio"):
            how = "condicion"
        elif named:
            how = "especifica"
        else:
            how = "condicion"
        pairs.add((src, how))
    return pairs
