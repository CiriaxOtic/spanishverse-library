"""Detecta efectos que crean cartas al azar y las condiciones de lo que pueden crear.

Se usa desde el programa para la opción "Ver creadoras": además de las cartas que nombran a otra
(relaciones oficiales), una carta puede *posiblemente* crear cualquier carta que cumpla las
condiciones de un efecto aleatorio (tipo, costo, clase, tribu).
"""
import re

TYPES = {"follower": 1, "followers": 1, "spell": 4, "spells": 4, "amulet": 2, "amulets": 2}
CLASSES = {"neutral": 0, "forestcraft": 1, "swordcraft": 2, "runecraft": 3, "dragoncraft": 4,
           "abysscraft": 5, "havencraft": 6, "portalcraft": 7}
CREATE = re.compile(r"\b(add|adds|summon|summons|put|puts)\b", re.I)
# Copias de cartas que ya están en juego, en una mano o destruidas: pueden ser cualquier carta, no son un "pool".
EXISTING = re.compile(r"\b(allied|enemy|ally|opponent'?s?|in your hand|in your deck|destroyed|this match|it|them|each)\b.*\bcop(y|ies)\b"
                      r"|\bcop(y|ies)\b.*\b(allied|enemy|opponent'?s?|destroyed|in your hand|this card|it)\b", re.I)


def strip(s):
    return re.sub(r"<[^>]+>", "", s or "")


def _common_conditions(low, cond, tribes):
    cls = [CLASSES[w] for w in re.findall(r"[a-z]+", low) if w in CLASSES]
    if cls:
        cond["classes"] = set(cls)
    tr = [tid for name, tid in tribes.items() if re.search(rf"\b{re.escape(name)}\b", low)]
    if tr:
        cond["tribes"] = set(tr)
    c = re.search(r"(?:that costs?|costing|with a (?:base )?cost of|(?:base )?cost of|costs?)\s+(\d+)(\s+or\s+(less|more))?", low)
    if c:
        cond["cost"] = (int(c.group(1)), c.group(3))  # (valor, None|'less'|'more')


def random_pools(text, tribes):
    """Lista de condiciones (dict) de cada efecto que puede traer una carta no nombrada, en `text` (inglés).
    Cada condición lleva "src": "mazo" (al azar de tu mazo) o "cementerio" (algo tuyo destruido en la partida).
    tribes: {nombre_en_minúsculas: id}."""
    pools = []
    for sentence in re.split(r"(?<=[.!])\s+|\n|<hr>", strip(text)):
        low = sentence.lower()
        # Reanimación (X): copia del combatiente aliado de mayor costo destruido en la partida, de costo X o menos.
        for n in re.findall(r"\breanimate\s*\((\d+)\)", low):
            pools.append({"type": 1, "cost": (int(n), "less"), "src": "cementerio", "tokens": True})
        # Copias de combatientes o amuletos aliados destruidos en la partida.
        if "destroyed this match" in low and "allied" in low and re.search(r"\b(summon|add)\b", low) and re.search(r"\bcop(y|ies)\b", low):
            m = re.search(r"allied\s+((?:[a-z]+\s+)?)(followers?|amulets?|cards?)\s+destroyed", low)
            if m:
                cond = {"type": TYPES.get(m.group(2)), "src": "cementerio", "tokens": True}
                _common_conditions(low, cond, tribes)
                if "with last words" in low:
                    cond["needs"] = "last words"
                pools.append(cond)
            continue
        if "random" not in low or not CREATE.search(low) or EXISTING.search(low):
            continue
        m = re.search(r"\brandom\b(.{0,80})", low)
        if not m:
            continue  # "randomly" y similares no crean cartas de un pool
        # "random" tiene que ser lo que se crea: en "banish a random enemy follower and summon a Divine Evidence"
        # lo aleatorio es lo desterrado, y lo invocado es una carta con nombre.
        verbs = re.findall(r"\b(add|adds|summon|summons|put|puts|deal|destroy|banish|give|evolve|return|transform|"
                           r"discard|select|draw|restore)\b", low[:m.start()])
        if verbs and not CREATE.fullmatch(verbs[-1]):
            continue
        tail = m.group(1)
        kind = next((TYPES[w] for w in re.findall(r"[a-z]+", tail) if w in TYPES), None)
        if kind is None and not re.search(r"\bcards?\b", tail):
            continue  # "random" referido a otra cosa (objetivo, daño, etc.)
        cond = {"type": kind, "src": "mazo" if re.search(r"from (?:your|their) deck", low) else "nueva"}
        _common_conditions(low, cond, tribes)
        pools.append(cond)
    return pools


def fits(card, cond, creator_class=0):
    """¿La carta podría salir de este efecto aleatorio?

    Estos efectos sacan cartas de tu propio mazo, y un mazo solo tiene cartas de su clase y neutrales
    (sin fichas). Así que una creadora de una clase solo puede traer cartas de esa clase o neutrales;
    una creadora neutral puede estar en cualquier mazo, así que puede traer de cualquier clase."""
    # Las fichas nunca están en un mazo, pero sí pueden volver del cementerio si fueron destruidas.
    if card["is_token"] and not cond.get("tokens"):
        return False
    if creator_class and card["class_id"] not in (creator_class, 0):
        return False
    if cond.get("needs") and cond["needs"] not in strip(card.get("skill_en")).lower():
        return False
    if cond.get("type") is not None:
        want = cond["type"]
        if want == 2 and card["type_id"] not in (2, 3):  # amuletos, con o sin cuenta regresiva
            return False
        if want != 2 and card["type_id"] != want:
            return False
    if "classes" in cond and card["class_id"] not in cond["classes"]:
        return False
    if "tribes" in cond and not set(card["tribes"]) & cond["tribes"]:
        return False
    if "cost" in cond:
        n, mode = cond["cost"]
        cost = card["cost"] or 0
        if (mode is None and cost != n) or (mode == "less" and cost > n) or (mode == "more" and cost < n):
            return False
    return True
