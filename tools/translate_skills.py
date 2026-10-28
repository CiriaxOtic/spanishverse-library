"""Traducción propia de los efectos de las cartas que todavía no tienen texto oficial en español.

Los efectos en inglés siguen moldes fijos ("Select an enemy follower on the field and deal it 3 damage."), así que
se traducen por piezas: objetivos ("an enemy follower on the field"), acciones ("deal it 3 damage"), condiciones
("At the end of your turn,") y mejoras ("+1/+1 and Ward"). El estilo y las palabras son los de la traducción
oficial latina (aprendidos de las cartas que sí la tienen); los nombres de cartas quedan en inglés. Dos cambios a
propósito: "instead" se traduce "en su lugar" y "Whenever" siempre "Cada vez que" (la oficial a veces los pierde).
Una frase que no encaja en ningún molde queda en inglés (con las palabras clave en español, como antes).

Uso por consola: py -3.13 tools/translate_skills.py   (guarda la traducción en cards.db, columna skill_tr)
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402
DB = ROOT / "cards.db"

N = r"(\d+|[XYZ])"  # un número o una variable
# Tipos sin traducción oficial todavía (traducción propia).
TRIBES_OWN = {"Loot": "Botín", "Encroacher": "Invasor", "Clue": "Pista"}
# Términos del juego con forma de carta que no son cartas de la lista (no son links): se traducen.
SPECIAL_CARDS = {"Victory Card": "Carta de Victoria", "Reaper Card": "Carta de la Muerte"}
# Clase como adjetivo: (masculino, femenino, plural masculino, plural femenino).
CLASSES = {
    "Forestcraft": ("Forestal", "Forestal", "Forestales", "Forestales"),
    "Swordcraft": ("Imperial", "Imperial", "Imperiales", "Imperiales"),
    "Runecraft": ("Rúnico", "Rúnica", "Rúnicos", "Rúnicas"),
    "Dragoncraft": ("Dracónico", "Dracónica", "Dracónicos", "Dracónicas"),
    "Abysscraft": ("Abismal", "Abismal", "Abismales", "Abismales"),
    "Havencraft": ("Clerical", "Clerical", "Clericales", "Clericales"),
    "Portalcraft": ("Dimensional", "Dimensional", "Dimensionales", "Dimensionales"),
    "Neutral": ("Neutral", "Neutral", "Neutrales", "Neutrales"),
}
# Plural de los tipos cuando acompañan a "combatientes" (los que no cambian quedan igual).
TRIBE_PLURAL = {"Oficial": "Oficiales", "Luminoso": "Luminosos", "Difunto": "Difuntos", "Artefacto": "Artefactos",
                "Titiritero": "Titiriteros", "Marino": "Marinos", "Anatema": "Anatemas", "Invasor": "Invasores"}
TRIBE_FORM = {"Hada": "tipo Hada"}  # como en la versión oficial: "combatiente tipo Hada"

# Sustantivos: inglés -> (singular, plural, género)
NOUNS = {
    "follower": ("combatiente", "combatientes", "m"), "card": ("carta", "cartas", "f"),
    "amulet": ("amuleto", "amuletos", "m"), "spell": ("hechizo", "hechizos", "m"),
    "leader": ("líder", "líderes", "m"), "enemy": ("enemigo", "enemigos", "m"), "ally": ("aliado", "aliados", "m"),
    "crest": ("Blasón", "Blasones", "m"),
}
# "Follower Strike" -> "Ofensiva de Combatiente" (dos palabras clave que en español van al revés)
STRIKES = {"Follower": "de Combatiente", "Leader": "de Líder"}


class Untranslatable(Exception):
    pass


# ---------- marcas dentro del texto ----------
def protect(s, kw):
    """Cambia nombres de cartas y palabras clave por marcas (⟦C0⟧, ⟦K0⟧) para traducir solo el texto.
    Devuelve (texto, piezas) donde piezas[marca] es el texto final de esa marca (ya en español)."""
    parts = {}

    def card(m):
        key = f"⟦C{len(parts)}⟧"
        # "Crest: Nombre" -> "Blasón: Nombre" (el nombre queda en inglés)
        parts[key] = m.group(0).replace("<i>Crest: ", "<i>" + kw.get("crest", "Blasón") + ": ")
        return key

    def strike(m):
        key = f"⟦K{len(parts)}⟧"
        es = kw.get("strike", "Ofensiva")
        parts[key] = (f"<b><color=Keyword>{es}</color></b> "
                      f"<b><color=Keyword>{STRIKES[m.group(1)]}</color></b>")
        parts[key + "plain"] = f"{es} {STRIKES[m.group(1)]}"
        return key

    def keyword(m):
        key = f"⟦K{len(parts)}⟧"
        name, suffix, extra = m.group(1), m.group(2) or "", m.group(3) or ""
        es = kw.get(name.lower(), name)
        parts[key] = f"<b><color=Keyword>{es}</color>{extra}</b>"
        parts[key + "plain"] = es
        if suffix == "d":  # "Fused" / "Invoked": verbo en pasado
            parts[key + "past"] = True
        return key

    s = re.sub(r"<b><color=Keyword>(Follower|Leader)</color></b> <b><color=Keyword>Strike</color></b>", strike, s)
    s = re.sub(r"<b><i>.*?</i></b>", card, s)
    # "Fused" viene partido en dos marcas: <b><b>Fuse</b><b>d</b></b>
    s = re.sub(r"<b><b><color=Keyword>([^<]+)</color></b><b><color=Keyword>(d)</color></b></b>()", keyword, s)
    s = re.sub(r"<b><color=Keyword>([^<]+)</color>(?:<color=Keyword>(s|d)</color>)?( \(\d+\))?</b>", keyword, s)
    s = re.sub(r"<color=Keyword>([^<]+)</color>()()", keyword, s)
    return s, parts


def restore(s, parts):
    for key, val in sorted(parts.items(), key=lambda kv: -len(kv[0])):
        if not key.endswith(("plain", "past")):
            s = s.replace(key, val)
    return s


def split_sentences(s):
    """Corta en frases sin cortar dentro de comillas (habilidades otorgadas con varias frases)."""
    out, cur, inside = [], "", False
    i = 0
    while i < len(s):
        ch = s[i]
        cur += ch
        if ch == '"':
            inside = not inside
        if not inside and ch in ".!?\"" and s[i + 1:i + 2] == " " and (s[i + 2:i + 3].isupper() or
                                                                         s[i + 2:i + 3] in ("⟦", '"')):
            out.append(cur.strip())
            cur = ""
            i += 1  # el espacio
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


# ---------- concordancia ----------
def agree(word, gender, plural):
    """Adjetivo en masculino singular -> concordado (aliado -> aliadas, etc.)."""
    if word.endswith("o"):
        base = word[:-1] + ("a" if gender == "f" else "o")
        return base + "s" if plural else base
    if plural:
        return word + ("es" if word[-1] not in "aeiouáéíóú" else "s")
    return word


def art(gender, plural, definite=False):
    if definite:
        return {("m", False): "el", ("f", False): "la", ("m", True): "los", ("f", True): "las"}[(gender, plural)]
    return {("m", False): "un", ("f", False): "una", ("m", True): "unos", ("f", True): "unas"}[(gender, plural)]


def cap(s):
    return s[:1].upper() + s[1:] if s else s


def lower1(s):
    return s if s.startswith(("⟦", "X ", "Y ", "Z ", "X/")) else s[:1].lower() + s[1:]


def a_el(prep, np_text):
    """'a' + 'el líder' -> 'al líder'; 'de' + 'el campo' -> 'del campo'."""
    if np_text.startswith("el "):
        return {"a": "al", "de": "del"}[prep] + np_text[2:]
    return f"{prep} {np_text}"


# ---------- objetivos (frases nominales) ----------
class NP:
    def __init__(self, text, gender="m", plural=False):
        self.text, self.gender, self.plural = text, gender, plural

    def __str__(self):
        return self.text


FIXED_NP = {
    # "this follower" es la propia carta: "esta carta" no se confunde con el otro combatiente nombrado
    "this follower": NP("esta carta", "f"), "this card": NP("esta carta", "f"), "this amulet": NP("este amuleto"),
    "this spell": NP("este hechizo"), "this crest": NP("este Blasón"), "your leader": NP("tu líder"), "the enemy leader": NP("el líder enemigo"),
    "both leaders": NP("ambos líderes", plural=True), "your opponent": NP("tu rival"),
    "all enemies": NP("todos los enemigos", plural=True), "all allies": NP("todos los aliados", plural=True),
    "all other allies": NP("los demás aliados", plural=True), "all leaders": NP("todos los líderes", plural=True),
    "the opposing follower": NP("el combatiente contrario"), "it": NP("él"), "them": NP("ellos", plural=True),
    "your hand": NP("tu mano", "f"), "your deck": NP("tu mazo"), "the selected card": NP("la carta seleccionada", "f"),
    "the selected follower": NP("el combatiente seleccionado"), "this match": NP("esta partida", "f"),
    "your opponent's hand": NP("la mano de tu rival", "f"), "each leader": NP("cada líder"),
    "yourself and your opponent": NP("tú y tu rival", plural=True), "all crests": NP("todos los Blasones", plural=True),
    "all your crests": NP("todos tus Blasones", plural=True), "the attack target": NP("el objetivo del ataque"),
    "all duplicates from your deck": NP("todas las cartas repetidas de tu mazo", "f", True),
    "it and this follower": NP("él y esta carta", plural=True),
    "them and this follower": NP("ellos y esta carta", plural=True),
}


def tribe_es(name, tribes):
    return tribes.get(name) or TRIBES_OWN.get(name)


def np(s, ctx):
    """Frase nominal inglesa -> NP en español. Lanza Untranslatable si no la reconoce."""
    s = s.strip()
    low = s.lower()
    if low in FIXED_NP:
        return FIXED_NP[low]
    if re.fullmatch(r"⟦C\d+⟧", s):  # una carta por nombre
        return NP(s)
    if m := re.fullmatch(r"your (⟦C\d+⟧)", s):
        return NP(f"tu {m.group(1)}")
    if m := re.fullmatch(r"(the|a|an) ((?:[A-Z][\w']* )*Card)( at the bottom of your deck)?", s):
        return NP(f"{'la' if m.group(1) == 'the' else 'una'} {SPECIAL_CARDS.get(m.group(2), m.group(2))}"
                  f"{' del fondo de tu mazo' if m.group(3) else ''}", "f")
    if m := re.fullmatch(r"the (⟦C\d+⟧) at the bottom of your deck", s):
        return NP(f"el {m.group(1)} del fondo de tu mazo")
    if m := re.fullmatch(r"an allied and enemy (follower|card|amulet)( on the field)?", s):
        sing, plur, g = NOUNS[m.group(1)]
        return NP(f"{art(g, False)} {sing} {agree('aliado', g, False)} y {'uno' if g == 'm' else 'una'} "
                  f"{agree('enemigo', g, False)}{' del campo' if m.group(2) else ''}", g, True)
    if m := re.fullmatch(r"the (\d+) (leftmost|rightmost) (allied |enemy )?(followers|cards|amulets)"
                         r"( on the field| in your hand)?", s):
        sing, plur, g = NOUNS[m.group(4)[:-1]]
        side = " " + agree({"allied ": "aliado", "enemy ": "enemigo"}[m.group(3)], g, True) if m.group(3) else ""
        where = {" on the field": " del campo", " in your hand": " de tu mano"}.get(m.group(5) or "", "")
        return NP(f"{art(g, True, True)} {m.group(1)} {plur}{side} de más a la "
                  f"{'izquierda' if m.group(2) == 'leftmost' else 'derecha'}{where}", g, True)
    # Listas de costos: "all 1-, 3-, and 5-cost cards", "a 1-, 3-, or 5-cost card"
    if m := re.fullmatch(r"(all |a |an )((?:\d+-,? )+(?:and |or )\d+)-cost (cards?)(.*)", s):
        costs = re.findall(r"\d+", m.group(2))
        join = " o " if " or " in m.group(2) else " y "
        plural = m.group(1) == "all "
        text = ("todas las cartas" if plural else "una carta") + f" de costo {', '.join(costs[:-1])}{join}{costs[-1]}"
        return NP(text + post_np(m.group(4), "f", plural, ctx), "f", plural)
    if m := re.fullmatch(r"an exact copy each of the (\d+) leftmost cards in your hand", s):
        return NP(f"una copia exacta de cada una de las {m.group(1)} cartas de más a la izquierda de tu mano", "f")
    if m := re.fullmatch(r"all cards not named (⟦C\d+⟧|[A-Z][\w']*(?: [A-Z][\w']*)*)", s):
        return NP(f"todas las cartas que no se llamen {m.group(1)}", "f", True)
    # Varias cosas: "A, B, and C" / "A and B" / "A or B"
    for joiner, es_join in ((" and ", " y "), (" or ", " o ")):
        if joiner in s and not re.search(r"\d+ or (less|more)", s):
            items = [it for it in re.split(r",\s*(?:and |or )?|" + joiner, s) if it.strip()]
            if len(items) > 1:
                try:
                    first = np(items[0], ctx)
                    rest = []
                    for it in items[1:]:
                        # "a ⟦C⟧ and ⟦C⟧" -> "un ⟦C⟧ y un ⟦C⟧"
                        if re.fullmatch(r"⟦C\d+⟧", it.strip()) and first.text.startswith("un "):
                            it = "a " + it.strip()
                        n = np(it, ctx).text
                        if es_join == " o " and n.startswith("el "):
                            n = "al " + n[3:]  # "o al líder enemigo"
                        rest.append(n)
                except Untranslatable:
                    continue
                text = ", ".join([first.text] + rest[:-1]) + es_join + rest[-1]
                return NP(text, first.gender, es_join == " y ")
    # "N copies of ⟦C⟧", "all allied copies of ⟦C⟧ on the field", "a copy each of ..."
    m = re.fullmatch(r"(all |all other |\d+ |[XYZ] |a |an )?(allied |enemy |other allied )?(exact )?cop(?:y|ies)"
                     r"( each)? of (.+?)((?: on the field| in your hand(?: and deck)?| in your deck|"
                     r" that have entered the field this match)*)", s, re.I)
    if m:
        det, side, exact, each, inner, post = (x or "" for x in m.groups())
        det, side = det.strip().lower(), side.strip().lower()
        inner_np = np(inner, ctx)
        word = "copia" + (" exacta" if exact else "")
        if det in ("a", "an", ""):
            text = f"una {word}" if det else word
            plural = False
        elif det.startswith("all"):
            text = ("las demás " if "other" in det else "todas las ") + word.replace("copia", "copias").replace(
                "exacta", "exactas")
            plural = True
        else:
            text = f"{det} {word.replace('copia', 'copias').replace('exacta', 'exactas')}"
            plural = True
        if side:
            text += " " + agree({"allied": "aliado", "enemy": "enemigo", "other allied": "aliado"}[side], "f", plural)
        text += f" de {'cada uno de ' if each else ''}{inner_np}"
        text += (post.replace(" on the field", " del campo").replace(" in your hand and deck", " de tu mano y tu mazo")
                 .replace(" in your hand", " de tu mano").replace(" in your deck", " de tu mazo")
                 .replace(" that have entered the field this match", " que entraron al campo en esta partida"))
        return NP(text, "f", plural)
    # "a ⟦C⟧" (carta por nombre con artículo)
    m = re.fullmatch(r"(a|an) (⟦C\d+⟧)", s, re.I)
    if m:
        return NP(f"un {m.group(2)}")
    m = re.fullmatch(N + r" (⟦C\d+⟧)", s)
    if m:
        return NP(f"{m.group(1)} {m.group(2)}", plural=True)
    return generic_np(s, ctx)


def generic_np(s, ctx):
    """[determinante] [otro] [N] [aleatorio] [sin evolucionar|evolucionado|dañado] [aliado|enemigo]
    [tipo|clase] sustantivo [complementos]."""
    tribes = ctx["tribes"]
    m = re.fullmatch(
        r"(?P<det>all other |all |another |other |the leftmost |the rightmost |the |a |an |each |every |"
        r"(?P<num>\d+|[XYZ]|two|three)(?P<numother> other)? )?"
        r"(?P<rand>random )?"
        r"(?P<diff>differently named )?"
        r"(?P<state>(?:(?:unevolved|evolved|super-evolved|damaged|undamaged|unselected),? )*)"
        r"(?P<base>\d+-base-cost |\d+-cost |X-cost )?"
        r"(?P<side>allied |enemy |opposing )?"
        r"(?P<non>non-)?"
        r"(?P<kind>(?:[A-Z][a-z]+(?: [A-Z][a-z]+)? )|⟦K\d+⟧ |(?:[A-Z][a-z]+-))?"
        r"(?P<head>followers?|cards?|amulets?|spells?|leaders?|crests?|enem(?:y|ies)|all(?:y|ies)|⟦C\d+⟧)"
        r"(?P<post>.*)",
        s)
    if not m:
        raise Untranslatable(s)
    head = m.group("head")
    if head.startswith("⟦C"):  # una carta por nombre con modificadores: "a random allied ⟦C⟧ on the field"
        sing = plur = head
        g, plural, key = "m", False, "named"
    else:
        plural = head.endswith("s") and head != "ally" or head in ("enemies", "allies")
        key = {"enemies": "enemy", "allies": "ally"}.get(head, head[:-1] if head.endswith("s") else head)
        if key not in NOUNS:
            raise Untranslatable(s)
        sing, plur, g = NOUNS[key]
    det = (m.group("det") or "").strip().lower()
    num = m.group("num")
    if num:
        num = {"two": "2", "three": "3"}.get(num, num)
        plural = num != "1"
    if det in ("all", "all other") and not plural:
        raise Untranslatable(s)
    parts = [plur if plural else sing]
    kind = (m.group("kind") or "").strip()
    if kind.endswith("-"):  # "Pixie-" en "non-Pixie-"? no: es un tipo compuesto raro
        raise Untranslatable(s)
    if kind:
        if kind in CLASSES:
            forms = CLASSES[kind]
            word = forms[(g == "f") + 2 * plural]
        elif tribe_es(kind, tribes):
            word = tribe_es(kind, tribes)
            if key == "follower":
                word = TRIBE_FORM.get(word, TRIBE_PLURAL.get(word, word) if plural else word)
            else:
                word = f"de {word}"
        elif kind.startswith("⟦K"):
            plain = ctx["plain"](kind)
            word = f"que tenga{'n' if plural else ''} la habilidad {plain}" if plain.startswith("Con ") else f"de {plain}"
        else:
            raise Untranslatable(s)
        if m.group("non"):
            word = f"que no sea{'n' if plural else ''} {word.replace('de ', '').replace('tipo ', '')}"
        parts.append(word)
    elif m.group("non"):
        raise Untranslatable(s)
    for st in [x for x in re.split(r",?\s+", (m.group("state") or "").strip()) if x]:
        parts.append({"unevolved": "sin evolucionar", "evolved": agree("evolucionado", g, plural),
                      "super-evolved": agree("superevolucionado", g, plural), "damaged": agree("dañado", g, plural),
                      "undamaged": "sin daño", "unselected": "no " + agree("seleccionado", g, plural)}[st])
    side = (m.group("side") or "").strip()
    if side and key not in ("enemy", "ally"):
        # en la oficial: "combatiente aliado sin evolucionar" (aliado antes del estado)
        word = agree({"allied": "aliado", "enemy": "enemigo", "opposing": "contrario"}[side], g, plural)
        idx = 2 if kind and len(parts) > 1 else 1
        parts.insert(idx, word)
    if m.group("rand"):
        parts.append(agree("aleatorio", g, plural))
    if m.group("diff"):
        parts.append("de nombre distinto")
    base = (m.group("base") or "").strip()
    if base:
        n = base.split("-")[0]
        parts.append(f"con costo base de {n}" if "base" in base else f"de {n} de costo")
    text = " ".join(parts)
    text += post_np(m.group("post"), g, plural, ctx)
    if det in ("the leftmost", "the rightmost"):
        text += " más a la " + ("izquierda" if "left" in det else "derecha")
        det = "the"
    # determinante
    if det == "all":
        text = ("todos los " if g == "m" else "todas las ") + text
    elif det == "all other":
        text = ("los demás " if g == "m" else "las demás ") + text
    elif det in ("another", "other"):
        text = (("otro " if g == "m" else "otra ") if not plural else ("otros " if g == "m" else "otras ")) + text
    elif det == "the":
        text = art(g, plural, True) + " " + text
    elif det in ("a", "an"):
        text = art(g, False) + " " + text
    elif det in ("each", "every"):
        text = "cada " + text
    elif num:
        text = (("otros " if g == "m" else "otras ") if m.group("numother") else "") + f"{num} {text}"
    return NP(text, g, plural)


POST = [
    (r" on the field", lambda g, p: " del campo"),
    (r" in your hand", lambda g, p: " de tu mano"),
    (r" in your deck", lambda g, p: " de tu mazo"),
    (r" from your deck", lambda g, p: " de tu mazo"),
    (r" from your hand", lambda g, p: " de tu mano"),
    (r" from the field", lambda g, p: " del campo"),
    (r" in your opponent's hand", lambda g, p: " de la mano de tu rival"),
    (r" in your opponent's deck", lambda g, p: " del mazo de tu rival"),
    (r" with the highest attack", lambda g, p: " con el ataque más alto"),
    (r" with the highest defense", lambda g, p: " con la defensa más alta"),
    (r" with the lowest defense", lambda g, p: " con la defensa más baja"),
    (r" with the highest cost", lambda g, p: " con el costo más alto"),
    (r" with the lowest cost", lambda g, p: " con el costo más bajo"),
    (r" with base costs of " + N + " or less", lambda g, p, n: f" con costo base de {n} o menos"),
    (r" with the highest base cost", lambda g, p: " con el costo base más alto"),
    (r" with " + N + " defense or less", lambda g, p, n: f" con {n} o menos de defensa"),
    (r" with " + N + " defense", lambda g, p, n: f" con {n} de defensa"),
    (r" with " + N + " attack or less", lambda g, p, n: f" con {n} o menos de ataque"),
    (r" with " + N + " attack or more", lambda g, p, n: f" con {n} o más de ataque"),
    (r" with " + N + " defense or more", lambda g, p, n: f" con {n} o más de defensa"),
    (r" that costs? " + N + " or less", lambda g, p, n: f" de {n} de costo o menos"),
    (r" that costs? " + N + " or more", lambda g, p, n: f" de {n} de costo o más"),
    (r" that costs? " + N, lambda g, p, n: f" de {n} de costo"),
    (r" with a cost of " + N + " or less", lambda g, p, n: f" de {n} de costo o menos"),
    (r" with a base cost of " + N + " or more", lambda g, p, n: f" con costo base de {n} o más"),
    (r" with a base cost of " + N + " or less", lambda g, p, n: f" con costo base de {n} o menos"),
    (r" and a base cost of " + N + " or less", lambda g, p, n: f" y costo base de {n} o menos"),
    (r" destroyed this match", lambda g, p: " " + agree("destruido", g, p) + " en esta partida"),
    (r" destroyed this turn", lambda g, p: " " + agree("destruido", g, p) + " en este turno"),
    (r" that have entered the field this match", lambda g, p: " que entraron al campo en esta partida"),
    (r" that entered the field this turn", lambda g, p: " que entraron al campo en este turno"),
    (r" that didn't attack this turn", lambda g, p: " que no atacó en este turno"),
    (r" other than the attack target", lambda g, p: " que no sea el objetivo del ataque"),
    (r" other than it", lambda g, p: " que no sea esa"),
    (r" played this match", lambda g, p: " " + agree("jugado", g, p) + " en esta partida"),
    (r" played this turn", lambda g, p: " " + agree("jugado", g, p) + " en este turno"),
    (r" with the same base cost", lambda g, p: " con el mismo costo base"),
    (r" with the same cost", lambda g, p: " con el mismo costo"),
    (r" with (⟦K\d+⟧)", lambda g, p, k: f" con {k}"),
]


def post_np(post, g, plural, ctx):
    out = ""
    post = post or ""
    while post:
        for pat, fn in POST:
            mm = re.match(pat, post)
            if mm:
                out += fn(g, plural, *mm.groups())
                post = post[mm.end():]
                break
        else:
            raise Untranslatable(post)
    return out


# ---------- mejoras ("+1/+1 and Ward") ----------
def split_outside_quotes(s, pattern):
    """Corta s por pattern, pero no dentro de comillas."""
    out, last, inside = [], 0, False
    for m in re.finditer(r'"|' + pattern, s):
        if m.group(0) == '"':
            inside = not inside
        elif not inside:
            out.append(s[last:m.start()])
            last = m.end()
    out.append(s[last:])
    return [x for x in out if x.strip()]


def buffs(s, ctx):
    """'+2/+2, Rush, and Ward' -> '+2/+2, Embestida y Guardia'."""
    out = []
    for it in split_outside_quotes(s.strip(), r",\s*(?:and\s+)?|\s+and\s+"):
        it = it.strip()
        if re.fullmatch(r"[+-]?(\d+|[XYZ])/[+-]?(\d+|[XYZ])", it) or re.fullmatch(r"⟦K\d+⟧", it):
            out.append(it)
        elif re.fullmatch(r'"[^"]+"', it):
            out.append(quoted(it, ctx))
        elif m := re.fullmatch(r"(\d+) random abilities from the following", it):
            out.append(f"{m.group(1)} habilidades aleatorias de las siguientes")
        else:
            raise Untranslatable(it)
    return join_es(out)


def join_es(items):
    if len(items) == 1:
        return items[0]
    last = items[-1]
    return ", ".join(items[:-1]) + (" e " if last[:1].lower() == "i" else " y ") + last


def quoted(q, ctx):
    """Habilidad otorgada entre comillas: se traduce adentro (puede tener 'Palabra clave:' y varias frases).
    Se traduce tal cual, desde el lado de la carta que la recibe (como en el juego)."""
    inner = q.strip().strip('"').strip()
    head = ""
    if m := re.match(r"^(⟦K\d+⟧)\s*:\s*", inner):
        head, inner = m.group(1) + ": ", inner[m.end():]
    es = " ".join(sentence(p, ctx) for p in split_sentences(inner))
    if head:
        es = head + es
    return f'"{es.rstrip(".")}"'


# ---------- acciones ----------
TAILS = [(r" until the end of the turn$", " hasta el final del turno"),
         (r" until the end of your opponent's turn$", " hasta el final del turno de tu rival"),
         (r" until the end of their turn$", " hasta el final de su turno"),
         (r" until the end of your next turn$", " hasta el final de tu próximo turno"),
         (r" without revealing it$", " sin revelarla"),
         (r" without revealing them$", " sin revelarlas"),
         (r" instead$", " en su lugar")]

PRONOUN_VERBS = {  # verbo con el pronombre pegado (lleva tilde)
    "destroy": "destrúye", "banish": "destiérra", "evolve": "evoluciónа".replace("а", "a"),
    "super-evolve": "superevoluciónа".replace("а", "a"), "discard": "descárta",
}


def pron(gender, plural):
    return {("m", False): "lo", ("f", False): "la", ("m", True): "los", ("f", True): "las"}[(gender, plural)]


def action(s, ctx, subj=None):
    """Una acción en imperativo inglés -> español. subj: NP seleccionado antes (para 'it/them')."""
    s = s.strip().rstrip(".")
    suffix = ""
    changed = True
    while changed:
        changed = False
        for pat, es in TAILS:
            mm = re.search(pat, s)
            if mm:
                s, suffix, changed = s[:mm.start()], es + suffix, True
    out = _action(lower1(s) if not s.startswith("X ") else s, ctx, subj)
    return out + suffix


def _action(s, ctx, subj):
    def g(pat):
        return re.fullmatch(pat, s, re.I)
    sg = subj.gender if subj else "m"
    sp = subj.plural if subj else False
    # --- sobre lo seleccionado ("it/them") ---
    if m := g(r"deal (it|them) " + N + " damage"):
        return f"inflíge{'les' if m.group(1) == 'them' or sp else 'le'} {m.group(2)} de daño"
    if m := g(r"(destroy|banish|evolve|super-evolve|discard) (it|them)"):
        return PRONOUN_VERBS[m.group(1).lower()] + pron(sg, m.group(2) == "them" or sp)
    if m := g(r"give (it|them) and this follower (.+)"):
        who = "él" if m.group(1).lower() == "it" else "ellos"
        if subj is not None:
            return f"otórgales {buffs(m.group(2), ctx)} a {who} y a esta carta"
        return f"⟨SUJ⟩{who} y esta carta obtienen {buffs(m.group(2), ctx)}"
    if m := g(r"give (it) (.+?) and this follower (.+)"):
        return f"obtiene {buffs(m.group(2), ctx)} y esta carta obtiene {buffs(m.group(3), ctx)}"
    if m := g(r"(evolve|super-evolve) (it|them) and this follower"):
        verb = PRONOUN_VERBS[m.group(1).lower()] + pron(sg, m.group(2).lower() == "them" or sp)
        return f"{verb} y {m.group(1).lower().replace('super-evolve', 'superevoluciona').replace('evolve', 'evoluciona')} esta carta"
    if m := g(r"give (it|them) (⟦K\d+⟧) or (⟦K\d+⟧) at random"):
        return f"otórga{'les' if m.group(1) == 'them' or sp else 'le'} al azar {m.group(2)} o {m.group(3)}"
    if m := g(r'give (it|them) ("[^"]+") and, until the end of the turn, ("[^"]+")'):
        many = m.group(1) == "them" or sp
        verb = (f"obtiene{'n' if many else ''}" if subj is None else f"otórga{'les' if many else 'le'}")
        return f"{verb} {quoted(m.group(2), ctx)} y, hasta el final del turno, {quoted(m.group(3), ctx)}"
    if m := g(r"give (it|them) (.+)"):
        many = m.group(1) == "them" or sp
        if subj is None:  # "Cuando un combatiente entra al campo, obtiene +1/+1" (como la oficial)
            return f"obtiene{'n' if many else ''} {buffs(m.group(2), ctx)}"
        return f"otórga{'les' if many else 'le'} {buffs(m.group(2), ctx)}"
    if m := g(r"give the exact copy (.+?) and this follower (.+)"):
        return f"otórgale {buffs(m.group(1), ctx)} a la copia exacta y {buffs(m.group(2), ctx)} a esta carta"
    if m := g(r"give the exact cop(?:y|ies) (.+)"):
        return f"otórgale{'s' if 'ies' in s else ''} {buffs(m.group(1), ctx)}"
    if m := g(r"return (it|them) to (?:your |its owner's )?hand"):
        return "devuélve" + pron(sg, m.group(1) == "them" or sp) + " a la mano"
    if m := g(r"return (it|them) to (?:your )?deck"):
        return "devuélve" + pron(sg, m.group(1) == "them" or sp) + " al mazo"
    if m := g(r"transform (it|them) into (.+)"):
        if subj is None:
            return f"se transforma en {np(m.group(2), ctx)}"
        return "transfórma" + pron(sg, sp) + f" en {np(m.group(2), ctx)}"
    if g(r"transform it based on the total cost of the cards fused"):
        return "se transforma según el costo total de las cartas fusionadas"
    if m := g(r"set (?:its|their) attack and defense to " + N + "/" + N):
        return f"fija su ataque y su defensa en {m.group(1)}/{m.group(2)}"
    if m := g(r"set (its|their) (defense|attack|cost|costs) to " + N):
        what = {"defense": "defensa", "attack": "ataque"}.get(m.group(2), "costo")
        return f"fija su {what} en {m.group(3)}"
    if m := g(r"(reduce|increase) (?:its|their) costs? by " + N):
        return f"{'reduce' if m.group(1).lower() == 'reduce' else 'aumenta'} su costo en {m.group(2)}"
    if m := g(r"reduce the cost of the copy by " + N):
        return f"reduce el costo de la copia en {m.group(1)}"
    if m := g(r"remove (.+) from (it|them)"):
        if m.group(1) == "all abilities":
            return "elimina todas sus habilidades"
        return f"elimina su {buffs(m.group(1), ctx)}"
    if m := g(r"remove (⟦K\d+⟧) from (.+)"):
        return f"elimina {m.group(1)} {a_el('de', np(m.group(2), ctx).text)}"
    if m := g(r"summon an exact copy of (it|each)"):
        return "invoca una copia exacta " + ("suya" if m.group(1) == "it" else "de cada uno")
    if m := g(r"add a copy of it to your hand"):
        return "agrega una copia suya a tu mano"
    if m := g(r"spellboost it(?: " + N + " times)?"):
        return "aplícale Carga Mágica" + (f" {m.group(1)} veces" if m.group(1) else "")
    if m := g(r"activate (?:its|this card's) (⟦K\d+⟧) ability"):
        return f"activa su habilidad {m.group(1)}"
    if m := g(r"do it " + N + " times?"):
        return f"hazlo {m.group(1)} {'vez' if m.group(1) == '1' else 'veces'}"
    # --- acciones con objetivo propio ---
    # --- Fe y blasones ---
    if m := g(r"reduce your faith's value by " + N + r" to give it (\".+\")"):
        return f"reduce el valor de tu Fe en {m.group(1)} para otorgarle {quoted(m.group(2), ctx)}"
    if m := g(r"reduce your faith's value by " + N + " to (.+)"):
        return f"reduce el valor de tu Fe en {m.group(1)} para {infinitive(actions(m.group(2), ctx))}"
    if m := g(r"give your faith (\".+\")"):
        return f"otórgale a tu Fe {quoted(m.group(1), ctx)}"
    if m := g(r"increase this faith's value by " + N):
        return f"aumenta en {m.group(1)} el valor de esta Fe"
    if m := g(r"advance this crest's count by " + N):
        return f"avanza {m.group(1)} el contador de este Blasón"
    if m := g(r"spend " + N + " play points to (.+)"):
        return f"gasta {m.group(1)} PJ para {infinitive(actions(m.group(2), ctx))}"
    # --- otras ---
    if m := g(r"increase the number of (⟦K\d+⟧) you can select by " + N):
        return f"aumenta en {m.group(2)} la cantidad de {m.group(1)}s que puedes seleccionar"
    if m := g(r"increase the skybound art gauges of (.+) by " + N):
        return f"aumenta en {m.group(2)} el medidor de Skybound Art {a_el('de', np(m.group(1), ctx).text)}"
    if m := g(r"reduce the enemy leader's max defense by " + N):
        return f"reduce en {m.group(1)} la defensa máxima del líder enemigo"
    if g(r"halve the enemy leader's max defense"):
        return "reduce a la mitad la defensa máxima del líder enemigo"
    if g(r"swap this follower's attack and defense"):
        return "intercambia el ataque y la defensa de esta carta"
    if m := g(r"summon any (.+) drawn"):
        target = np("all " + m.group(1), ctx)
        return f"invoca {target} {agree('robado', target.gender, True)}"
    if g(r"consume (a|an|1) clue"):
        return "consume 1 pista"
    if m := g(r"consume " + N + r" clues"):
        return f"consume {m.group(1)} pistas"
    if m := g(r"consume " + N + r" clues? to (.+)"):
        return f"consume {m.group(1)} pista{'s' if m.group(1) != '1' else ''} para {infinitive(actions(m.group(2), ctx))}"
    if m := g(r"double the attack and defense of (.+)"):
        return f"duplica el ataque y la defensa {a_el('de', np(m.group(1), ctx).text)}"
    if m := g(r"summon (an? )?(enemy )?(⟦C\d+⟧) or (⟦C\d+⟧) at random"):
        side = " enemigo" if m.group(2) else ""
        return f"invoca al azar un {m.group(3)}{side} o un {m.group(4)}{side}"
    if m := g(r"summon " + N + "( copies)?"):
        return f"invoca {m.group(1)}{' copias' if m.group(2) else ''}"
    if m := g(r"summon (.+?) from your deck"):
        return f"invoca {np(m.group(1), ctx)} de tu mazo"
    if m := g(r"summon (.+)"):
        return f"invoca {np(m.group(1), ctx)}"
    if m := g(r"add " + N + r"(?: copies)?"):
        return f"agrega {m.group(1)}{' copias' if 'copies' in s else ''}"
    if m := g(r"add (.+) to your (hand|deck)"):
        return f"agrega {np(m.group(1), ctx)} a tu {'mano' if m.group(2).lower() == 'hand' else 'mazo'}"
    if m := g(r"put (.+) into your deck"):
        return f"pon {np(m.group(1), ctx)} en tu mazo"
    if m := g(r"draw (a|an|\d+|[XYZ]) cards?"):
        n = "1" if m.group(1).lower() in ("a", "an") else m.group(1)
        return f"roba {n} carta{'s' if n != '1' else ''}"
    if m := g(r"draw " + N):
        return f"roba {m.group(1)}"
    if m := g(r"draw (.+)"):
        return f"roba {np(m.group(1), ctx)}"
    if m := g(r"your opponent draws (a|an|\d+) cards?"):
        n = "1" if m.group(1).lower() in ("a", "an") else m.group(1)
        return f"tu rival roba {n} carta{'s' if n != '1' else ''}"
    if m := g(r"deal " + N + " damage split between (.+)"):
        return f"reparte {m.group(1)} de daño entre {np(m.group(2), ctx)}"
    if m := g(r"deal " + N + r" damage to (.+?) and " + N + " damage to (.+)"):
        return (f"inflige {m.group(1)} de daño {a_el('a', np(m.group(2), ctx).text)} y {m.group(3)} de daño "
                f"{a_el('a', np(m.group(4), ctx).text)}")
    if m := g(r"deal " + N + " damage to (.+)"):
        return f"inflige {m.group(1)} de daño {a_el('a', np(m.group(2), ctx).text)}"
    if m := g(r"deal " + N + " damage"):
        return f"inflige {m.group(1)} de daño"
    if m := g(r"deal damage to (.+)"):
        return f"inflige daño {a_el('a', np(m.group(1), ctx).text)}"
    if m := g(r"restore " + N + " defense to (.+)"):
        return f"restaura {m.group(1)} de defensa {a_el('a', np(m.group(2), ctx).text)}"
    if m := g(r"restore " + N + "(?: defense)?"):
        return f"restaura {m.group(1)}{' de defensa' if 'defense' in s else ''}"
    if m := g(r"fully restore the defense of (.+)"):
        return f"restaura por completo la defensa {a_el('de', np(m.group(1), ctx).text)}"
    if g(r"restore the same amount to your leader"):
        return "restaura la misma cantidad a tu líder"
    if m := g(r"(destroy|banish) (.+?)(?: from the field)?"):
        verb = {"destroy": "destruye", "banish": "destierra"}[m.group(1).lower()]
        out = f"{verb} {np(m.group(2), ctx)}"
        return out + (" del campo" if s.lower().endswith("from the field") else "")
    if m := g(r"(evolve|super-evolve) (.+)"):
        verb = {"evolve": "evoluciona", "super-evolve": "superevoluciona"}[m.group(1).lower()]
        target = np(m.group(2), ctx).text
        # "evoluciona esta carta" (sin "a": es una carta, no un personaje)
        return f"{verb} {target if target.startswith('esta carta') else a_el('a', target)}"
    if m := g(r"give (.+?) (\"[^\"]+\".*|[+-]?\w+/[+-]?\w+.*|⟦K\d+⟧.*|\d+ random abilities.*)"):
        target = np(m.group(1), ctx)
        verb = "obtienen" if target.plural else "obtiene"
        return f"⟨SUJ⟩{cap(target.text)} {verb} {buffs(m.group(2), ctx)}"
    if m := g(r"give ([+-]\S+/[+-]\S+)"):
        return f"obtiene {m.group(1)}"
    if m := g(r"return (.+) to (?:your |its owner's )?hand"):
        return f"devuelve {np(m.group(1), ctx)} a la mano"
    if m := g(r"return (.+) to (?:your )?deck"):
        return f"devuelve {np(m.group(1), ctx)} al mazo"
    if m := g(r"discard (.+)"):
        return f"descarta {np(m.group(1), ctx)}"
    if m := g(r"transform (.+) into (.+)"):
        return f"transforma {np(m.group(1), ctx)} en {np(m.group(2), ctx)}"
    if m := g(r"(reduce|increase) the cost of (.+) by " + N):
        verb = "reduce" if m.group(1).lower() == "reduce" else "aumenta"
        return f"{verb} el costo {a_el('de', np(m.group(2), ctx).text)} en {m.group(3)}"
    if m := g(r"halve the cost of (.+)"):
        return f"reduce a la mitad el costo {a_el('de', np(m.group(1), ctx).text)}"
    if m := g(r"set the cost of (.+) to " + N):
        return f"fija el costo {a_el('de', np(m.group(1), ctx).text)} en {m.group(2)}"
    if m := g(r"set the (attack|defense) of (.+) to " + N):
        what = "el ataque" if m.group(1).lower() == "attack" else "la defensa"
        return f"fija {what} {a_el('de', np(m.group(2), ctx).text)} en {m.group(3)}"
    if m := g(r"set (your leader|the enemy leader)'s max defense to " + N):
        who = "tu líder" if m.group(1).lower() == "your leader" else "el líder enemigo"
        return f"fija en {m.group(2)} la defensa máxima {a_el('de', who)}"
    if m := g(r"recover " + r"(\d+|[XYZ]|a|an) play points?(?: and " + N + r" evolution points?)?"):
        n = "1" if m.group(1).lower() in ("a", "an") else m.group(1)
        out = f"recupera {n} PJ"
        if m.group(2):
            out += f" y {m.group(2)} punto{'s' if m.group(2) != '1' else ''} de evolución"
        return out
    if g(r"fully recover your play points"):
        return "recupera todos tus PJ"
    if m := g(r"recover (\d+|[XYZ]|a|an) (super-)?evolution points?"):
        n = "1" if m.group(1).lower() in ("a", "an") else m.group(1)
        return f"recupera {n} punto{'s' if n != '1' else ''} de {'super' if m.group(2) else ''}evolución"
    if m := g(r"gain (\d+|[XYZ]|a|an) max play points?"):
        n = "1" if m.group(1).lower() in ("a", "an") else m.group(1)
        return f"obtienes {n} PJ máximo{'s' if n != '1' else ''}"
    if m := g(r"gain " + N + " earth sigils"):
        return f"obtienes {m.group(1)} Sellos de Tierra"
    if g(r"gain an earth sigil"):
        return "obtienes un Sello de Tierra"
    if m := g(r"gain " + N + " shadows?"):
        return f"obtienes {m.group(1)} Sombra{'s' if m.group(1) != '1' else ''}"
    if m := g(r"gain (⟦[CK]\d+⟧)"):
        return f"obtienes {m.group(1)}"
    if m := g(r"give (your opponent|yourself and your opponent) (⟦[CK]\d+⟧)"):
        who = "tu rival obtiene" if m.group(1).lower() == "your opponent" else "tú y tu rival obtienen"
        return f"{who} {m.group(2)}"
    if m := g(r"spellboost your hand " + N + " times"):
        return f"aplica Carga Mágica a tu mano {m.group(1)} veces"
    if g(r"spellboost your hand"):
        return "aplica Carga Mágica a tu mano"
    if m := g(r"advance this amulet's count by " + N):
        return f"avanza {m.group(1)} el contador de este amuleto"
    if m := g(r"(advance|delay) the counts? of (.+) by " + N):
        verb = "avanza" if m.group(1).lower() == "advance" else "retrasa"
        return f"{verb} {m.group(3)} el contador {a_el('de', np(m.group(2), ctx).text)}"
    if m := g(r"replicate the effects of this card's (⟦K\d+⟧) ability"):
        return f"se repiten los efectos de la habilidad {m.group(1)} de esta carta"
    if m := g(r"select (?:a|an|1) (⟦K\d+⟧) to activate"):
        return f"selecciona un {m.group(1)} para activar"
    if m := g(r"select (\d+) (⟦K\d+⟧) to activate"):
        return f"selecciona {m.group(1)} {m.group(2)}s para activar"
    if m := g(r"select " + N):
        return f"selecciona {m.group(1)}"
    if m := g(r"increase " + N + " by " + N):
        return f"aumenta {m.group(1)} en {m.group(2)}"
    if m := g(r"increase your (⟦K\d+⟧) by " + N):
        return f"aumenta tu {m.group(1)} en {m.group(2)}"
    if m := g(r"increase the (⟦K\d+⟧) gauges of (.+) by " + N):
        return f"aumenta el medidor de {m.group(1)} {a_el('de', np(m.group(2), ctx).text)} en {m.group(3)}"
    if g(r"return your hand to deck"):
        return "devuelve tu mano al mazo"
    if g(r"discard your hand"):
        return "descarta tu mano"
    if m := g(r"replace your deck with the (⟦K\d+⟧)"):
        return f"reemplaza tu mazo con el {m.group(1)}"
    if m := g(r"do this " + N + r" times?: (\".+\")"):
        return f"haz esto {m.group(1)} {'vez' if m.group(1) == '1' else 'veces'}: {quoted(m.group(2), ctx)}"
    if g(r"activate all of them"):
        return "activa todos"
    if m := g(r"activate " + N + " random abilities from the following"):
        return f"activa {m.group(1)} habilidades aleatorias de las siguientes"
    if g(r"activate a random ability that hasn't been activated yet from the following"):
        return "activa una habilidad aleatoria de las siguientes que todavía no se haya activado"
    if g(r"activate an ability that hasn't been activated yet in sequence from the following"):
        return "activa en orden una habilidad de las siguientes que todavía no se haya activado"
    if g(r"activate an ability in sequence from the following"):
        return "activa en orden una habilidad de las siguientes"
    if m := g(r"(⟦K\d+⟧)"):
        return m.group(1)
    if m := g(r"(⟦K\d+⟧) this card"):
        return f"usa {ctx['plain'](m.group(1))} en esta carta"
    if m := g(r"(⟦K\d+⟧) and (⟦K\d+⟧)"):
        return f"{m.group(1)} y {m.group(2)}"
    raise Untranslatable(s)


INFINITIVE = {"agrega": "agregar", "invoca": "invocar", "otórgale": "otorgarle", "otórgales": "otorgarles",
              "inflige": "infligir", "roba": "robar", "restaura": "restaurar", "destruye": "destruir",
              "destierra": "desterrar", "evoluciona": "evolucionar", "aplica": "aplicar", "obtienes": "obtener",
              "reduce": "reducir", "aumenta": "aumentar", "devuelve": "devolver", "descarta": "descartar",
              "transforma": "transformar", "recupera": "recuperar", "selecciona": "seleccionar"}


def infinitive(text):
    """'agrega X a tu mano y otórgale a tu Fe "..."' -> 'agregar X a tu mano y otorgarle a tu Fe "..."'
    (después de "para"). Solo cambia el verbo del comienzo de cada acción, nunca lo que está entre comillas."""
    parts = re.split(r'("[^"]*")', text)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"(^|, | y | e )(\w+)", lambda m: m.group(1) + INFINITIVE.get(m.group(2), m.group(2)),
                          parts[i])
    return "".join(parts)


def actions(s, ctx, subj=None):
    """Una o varias acciones unidas por ', ' / ' and ' / ', then ': prueba todas las formas de cortarlas."""
    s = s.strip().rstrip(".")
    try:
        return action(s, ctx, subj)
    except Untranslatable:
        pass
    # "draw a card and, if ..., restore ..." / "give it +1/+0 and, once on each of your turns, add ..."
    if m := re.fullmatch(r"(.+?),? and, (.+?), (.+)", s):
        try:
            a = actions(m.group(1), ctx, subj)
            made = subj or (NP("") if re.match(r"(invoca|agrega|roba|evoluciona|superevoluciona) ", a) else None)
            return f"{a} y, {lower1(condition(m.group(2), ctx))}, " \
                   f"{lower1(actions(m.group(3), ctx, made).replace('⟨SUJ⟩', ''))}"
        except Untranslatable:
            pass
    seps = [m for m in re.finditer(r",? and |, then |, ", s)]
    for mm in reversed(seps):
        left, right = s[:mm.start()], s[mm.end():]
        if left.count('"') % 2:  # el corte cae dentro de comillas
            continue
        try:
            a = actions(left, ctx, subj)
            # "Summon X and give it Y": lo recién invocado o agregado es el "it" de la acción siguiente
            made = subj or (NP("", "m", bool(re.search(r"\d+ copias|copias", a)))
                            if re.match(r"(invoca|agrega|roba|evoluciona|superevoluciona|intercambia) ", a) else None)
            b = action(right, ctx, made)
        except Untranslatable:
            continue
        b = b.replace("⟨SUJ⟩", "")
        b = lower1(b)
        if "then" in mm.group(0):
            sep = ", luego "
        elif "and" in mm.group(0):
            sep = " e " if b[:1].lower() == "i" else " y "
        else:
            sep = ", "
        return a + sep + b
    raise Untranslatable(s)


# ---------- condiciones ----------
FIXED_COND = {
    "at the end of your turn": "Al final de tu turno", "at the start of your turn": "Al comienzo de tu turno",
    "at the end of your opponent's turn": "Al final del turno del rival",
    "at the start of your opponent's turn": "Al comienzo del turno del rival",
    "at the end of each turn": "Al final de cada turno", "during your turn": "Durante tu turno",
    "during your opponent's turn": "Durante el turno del rival",
    "once on each of your turns": "Una vez en cada uno de tus turnos", "then": "Luego",
    "otherwise": "De lo contrario", "this turn": "En este turno",
    "until the end of your opponent's turn": "Hasta el final del turno del rival",
}


def condition(c, ctx):
    """Condición inicial ('At the end of your turn', 'If ...', 'Whenever ...') -> español."""
    c = c.strip()
    low = c.lower()
    if low in FIXED_COND:
        return FIXED_COND[low]
    if m := re.fullmatch(r"(then, )?if (.+)", c, re.I):
        return ("Luego, si " if m.group(1) else "Si ") + clause_if(m.group(2), ctx)
    if m := re.fullmatch(r"(whenever|when) (.+)", c, re.I):
        return ("Cada vez que " if m.group(1).lower() == "whenever" else "Cuando ") + clause_event(m.group(2), ctx)
    raise Untranslatable(c)


def clause_if(s, ctx):
    def g(p):
        return re.fullmatch(p, s, re.I)
    if m := g(r"you're in (⟦K\d+⟧)"):
        return f"estás en {m.group(1)}"
    if m := g(r"there's (.+) on the field"):
        what = m.group(1)
        if not re.match(r"(a|an|another|the) ", what, re.I):
            what = "a " + what
        return f"hay {np(what, ctx)} en el campo"
    if m := g(r"there's (.+?) on the field (with .+)"):
        what = m.group(1) if re.match(r"(a|an|another|the) ", m.group(1), re.I) else "a " + m.group(1)
        return f"hay {np(what + ' ' + m.group(2), ctx)} en el campo"
    if m := g(r"there are at least (\d+|[XYZ]|two|three) (.+) on the field"):
        n = {"two": "2", "three": "3"}.get(m.group(1).lower(), m.group(1))
        what = np(m.group(2), ctx).text
        if mm := re.match(r"(otros|otras) ", what):  # "al menos otras 2 cartas", no "2 otras cartas"
            return f"hay al menos {mm.group(1)} {n} {what[mm.end():]} en el campo"
        return f"hay al menos {n} {what} en el campo"
    if m := g(r"there's (.+)"):
        return f"hay {np(m.group(1), ctx)}"
    if m := g(r"you have " + N + "( or more)? max play points"):
        return f"tienes {m.group(1)}{' o más' if m.group(2) else ''} PJ máximos"
    if m := g(r"both players have " + N + " max play points"):
        return f"ambos jugadores tienen {m.group(1)} PJ máximos"
    if m := g(r"([XYZ]) is at least " + N):
        return f"{m.group(1)} es al menos {m.group(2)}"
    if m := g(r"(this card's|its) cost (is|isn't) " + N):
        who = "el costo de esta carta" if m.group(1).lower() == "this card's" else "su costo"
        return f"{who} {'es' if m.group(2).lower() == 'is' else 'no es'} {m.group(3)}"
    if m := g(r"you have at least " + N + " (.+) in your hand"):
        return f"tienes al menos {m.group(1)} {np(m.group(2), ctx)} en tu mano"
    if m := g(r"you have (.+) in your hand"):
        return f"tienes {np(m.group(1), ctx)} en tu mano"
    if m := g(r"this follower's attack is (lower|higher) than its defense"):
        return f"el ataque de esta carta es {'menor' if m.group(1).lower() == 'lower' else 'mayor'} que su defensa"
    if m := g(r"you've (⟦K\d+⟧) (.+?) this turn"):
        return f"usaste {ctx['plain'](m.group(1))} en {np(m.group(2), ctx)} en este turno"
    if m := g(r"you selected (.+)"):
        return f"seleccionaste {np(m.group(1), ctx)}" if m.group(1).lower() != "one" else "seleccionaste uno"
    if g(r"the opposing follower is damaged"):
        return "el combatiente contrario está dañado"
    if g(r"an allied follower attacked a leader on your last turn"):
        return "un combatiente aliado atacó a un líder en tu turno anterior"
    if m := g(r"(?:this follower|it)(?:'s| is) (evolved|super-evolved|unevolved)"):
        own = s.lower().startswith("this")
        st = {"evolved": "está evolucionad", "super-evolved": "está superevolucionad",
              "unevolved": "no está evolucionad"}[m.group(1).lower()] + ("a" if own else "o")
        return ("esta carta " if own else "") + st
    if m := g(r"(your leader|this follower)'s defense is " + N + " or less"):
        who = "tu líder" if m.group(1).lower() == "your leader" else "esta carta"
        return f"la defensa de {who} es {m.group(2)} o menos"
    if g(r"your leader's defense is higher than the enemy leader's defense"):
        return "la defensa de tu líder es mayor que la del líder enemigo"
    if m := g(r"you've (⟦K\d+⟧) to this card"):
        return f"usaste {ctx['plain'](m.group(1))} en esta carta"
    if g(r"you've unlocked super-evolution"):
        return "desbloqueaste la superevolución"
    if m := g(r"at least " + N + " (.+) have entered the field this match"):
        return f"al menos {m.group(1)} {np(m.group(2), ctx)} entraron al campo en esta partida"
    if m := g(r"allied followers have evolved at least " + N + " times this match"):
        return f"los combatientes aliados evolucionaron al menos {m.group(1)} veces en esta partida"
    if g(r"attacking a follower"):
        return "ataca a un combatiente"
    if g(r"there are no duplicates in your deck"):
        return "no hay cartas repetidas en tu mazo"
    if g(r"allied followers didn't attack this turn"):
        return "los combatientes aliados no atacaron en este turno"
    if m := g(r"you've played cards with base costs of ((?:\d+, )+(?:and )?\d+) this match"):
        costs = re.findall(r"\d+", m.group(1))
        return f"jugaste cartas con costo base de {', '.join(costs[:-1])} y {costs[-1]} en esta partida"
    if m := g(r"the sum of the " + N + " highest base costs in your hand is higher than that of your opponent's"):
        return f"la suma de los {m.group(1)} costos base más altos de tu mano es mayor que la de tu rival"
    raise Untranslatable(s)


def clause_event(s, ctx):
    def g(p):
        return re.fullmatch(p, s, re.I)
    if m := g(r"(.+?) enters the field"):
        return f"{np(m.group(1), ctx)} entra al campo"
    if m := g(r"(.+?) leaves the field"):
        return f"{np(m.group(1), ctx)} abandona el campo"
    if m := g(r"(.+?) is banished from the field"):
        who = np(m.group(1), ctx)
        return f"{who} es {agree('desterrado', who.gender, who.plural)} del campo"
    if m := g(r"(.+?) is destroyed"):
        return f"{np(m.group(1), ctx)} se destruye"
    if m := g(r"(.+?) attacks (a leader|a follower)"):
        return f"{np(m.group(1), ctx)} ataca a un {'líder' if 'leader' in m.group(2).lower() else 'combatiente'}"
    if m := g(r"(.+?) (super-evolves|evolves|attacks)"):
        verb = {"evolves": "evoluciona", "super-evolves": "superevoluciona", "attacks": "ataca"}[m.group(2).lower()]
        return f"{np(m.group(1), ctx)} {verb}"
    if m := g(r"(this follower|an enemy follower|an allied follower) is given ([+-]) (attack or defense|defense|attack)"
              r" on the field"):
        what = {"attack or defense": "ataque o defensa", "defense": "defensa", "attack": "ataque"}[m.group(3).lower()]
        return f"{np(m.group(1), ctx)} obtiene {m.group(2)} de {what} en el campo"
    if m := g(r"this follower takes damage but isn't destroyed"):
        return "esta carta recibe daño sin ser destruida"
    if m := g(r"(.+?) takes damage but isn't destroyed"):
        who = np(m.group(1), ctx)
        return f"{who} recibe daño sin ser {agree('destruido', who.gender, who.plural)}"
    if m := g(r"you draw a card"):
        return "robas una carta"
    if m := g(r"you draw this card"):
        return "robas esta carta"
    if m := g(r"you draw (.+)"):
        return f"robas {np(m.group(1), ctx)}"
    if m := g(r"you select (⟦K\d+⟧)"):
        return f"seleccionas un {m.group(1)}"
    if g(r"you gain this crest"):
        return "obtienes este Blasón"
    if m := g(r"you play or (⟦K\d+⟧) (.+)"):
        return f"juegas o usas {ctx['plain'](m.group(1))} en {np(m.group(2), ctx)}"
    if m := g(r"you play a follower whose cost has been changed"):
        return "juegas un combatiente cuyo costo fue modificado"
    if m := g(r"you play (.+)"):
        return f"juegas {np(m.group(1), ctx)}"
    if m := g(r"you (⟦K\d+⟧) an amulet"):
        return f"usas {ctx['plain'](m.group(1))} en un amuleto"
    if m := g(r"you (⟦K\d+⟧) (an? .+ amulet)"):
        return f"usas {ctx['plain'](m.group(1))} en {np(m.group(2), ctx)}"
    if m := g(r"you perform (⟦K\d+⟧)"):
        return f"realizas {m.group(1)}"
    if m := g(r"you(?:'ve)? (⟦K\d+⟧)(?: both)? to this card"):
        return f"usas {ctx['plain'](m.group(1))} en esta carta"
    if m := g(r"you (⟦K\d+⟧)"):
        return f"usas {ctx['plain'](m.group(1))}"
    if m := g(r"this card is (⟦K\d+⟧)"):
        return f"se usa {ctx['plain'](m.group(1))} con esta carta"
    if g(r"this card is discarded"):
        return "se descarta esta carta"
    if g(r"your leader's defense is restored"):
        return "se restaura la defensa de tu líder"
    if m := g(r"(this card|this follower) (enters|leaves) the field"):
        who = np(m.group(1), ctx)
        return f"{who} {'entra al' if m.group(2).lower() == 'enters' else 'abandona el'} campo"
    raise Untranslatable(s)


# ---------- frases completas ----------
FIXED_SENTENCES = {
    "activates in hand": "Se activa en la mano", "activates in deck": "Se activa en el mazo",
    "can't be played": "No se puede jugar", "can't be destroyed by abilities": "No puede ser destruido por habilidades",
    "can't attack followers or leaders": "No puede atacar a combatientes ni líderes",
    "can't attack leaders": "No puede atacar a líderes", "can't attack": "No puede atacar",
    "x is this follower's attack": "X es el ataque de esta carta",
    "x is this card's cost": "X es el costo de esta carta",
    "x is the selected follower's attack": "X es el ataque del combatiente seleccionado",
    "x is the selected follower's defense": "X es la defensa del combatiente seleccionado",
    "x is the number of cards in your hand": "X es el número de cartas que tienes en la mano",
    "x is the number of earth sigils you have": "X es el número de Sellos de Tierra que tienes",
    "x is the number of crests you have": "X es el número de Blasones que tienes",
    "x is the cost of the selected card": "X es el costo de la carta seleccionada",
    "x is the cost of the card you drew": "X es el costo de la carta que robaste",
    "x is the number of cards you returned": "X es el número de cartas que devolviste",
    "x is the number of cards you banished": "X es el número de cartas que desterraste",
    "x is the number of amulets destroyed by this ability": "X es el número de amuletos destruidos por esta habilidad",
    "this faith's value starts at 0": "El valor de esta Fe inicia en 0",
    "cards": "Cartas", "amulets": "Amuletos", "activate all of them instead": "Activa todos en su lugar",
    "x and y are this follower's attack and defense": "X e Y son el ataque y la defensa de esta carta",
    "x is the number of cards you discarded": "X es el número de cartas que descartaste",
    "x is the number of clues you have": "X es el número de pistas que tienes",
    "x is the enemy leader's max defense minus its defense":
        "X es la defensa máxima del líder enemigo menos su defensa actual",
    "your opponent can't select anything other than this card for abilities":
        "Tu rival solo puede seleccionar esta carta como objetivo de sus habilidades",
    "takes 1 more damage": "Recibe 1 de daño adicional",
    "x, y, and z are determined randomly and add up to your faith's value":
        "X, Y y Z se determinan al azar y suman el valor de tu Fe",
}


def sentence(s, ctx):
    """Una frase (con marcas) -> español. Lanza Untranslatable si no encaja."""
    s = s.strip()
    end = "." if s.endswith((".", '."')) else ""
    core = s.rstrip(".").strip()
    low = core.lower()
    if low in FIXED_SENTENCES:
        return FIXED_SENTENCES[low] + end
    if re.fullmatch(r"\d+\.", s):
        return s
    if m := re.fullmatch(r"(\d+|\d+ or more): (⟦C\d+⟧)", core):
        return m.group(1).replace(" or more", " o más") + ": " + m.group(2)
    if m := re.fullmatch(r"(?:can|it can) attack " + N + " times per turn", core, re.I):
        return f"Puede atacar {m.group(1)} veces por turno" + end
    if m := re.fullmatch(r"can't take more than " + N + " damage at a time", core, re.I):
        return f"No puede recibir más de {m.group(1)} de daño a la vez" + end
    if m := re.fullmatch(r"ignores (⟦K\d+⟧)", core, re.I):
        return f"Ignora {m.group(1)}" + end
    if m := re.fullmatch(r"([XYZ]) starts at " + N, core, re.I):
        return f"{m.group(1)} inicia en {m.group(2)}" + end
    if m := re.fullmatch(r"([XYZ]) is your (⟦K\d+⟧)", core, re.I):
        return f"{m.group(1)} es tu {m.group(2)}" + end
    if m := re.fullmatch(r"([XYZ]) is the number of differently named cards (⟦K\d+⟧) to this card", core):
        return f"{m.group(1)} es el número de cartas de nombre distinto que usaste con {m.group(2)} en esta carta" + end
    if m := re.fullmatch(r"X/Y is the total base attack/defense of (.+)", core):
        return f"X/Y es el total del ataque/defensa base de los {np(m.group(1), ctx)}" + end
    if m := re.fullmatch(r"([XYZ]) is the number of (.+?)(?: minus the number of (.+))?", core):
        out = f"{m.group(1)} es el número de {np(m.group(2), ctx)}"
        if m.group(3):
            out += f" menos el número de {np(m.group(3), ctx)}"
        return out + end
    if m := re.fullmatch(r"Allied followers' (⟦K\d+⟧) and (⟦K\d+⟧) abilities don't activate", core):
        return f"Las habilidades {m.group(1)} y {m.group(2)} de los combatientes aliados no se activan" + end
    if m := re.fullmatch(r"It costs " + N + " until the end of the turn", core):
        return f"Cuesta {m.group(1)} hasta el final del turno" + end
    if m := re.fullmatch(r"(⟦K\d+⟧) - (.+)", core):  # Combo (3) - ..., Earth Rite (1) - ...
        return f"{m.group(1)}: {sentence(m.group(2) + end, ctx)}"
    if re.fullmatch(r"(⟦K\d+⟧)", core):
        return core + end
    if m := re.fullmatch(r"(⟦K\d+⟧) and (⟦K\d+⟧)", core):
        return f"{m.group(1)} y {m.group(2)}" + end
    if m := re.fullmatch(r"(⟦C\d+⟧) and (⟦C\d+⟧)", core):
        return f"{m.group(1)} y {m.group(2)}" + end
    # Listas sin verbo (tablas de Fusión): "Artifact cards", "Loot cards"
    if re.fullmatch(r"[A-Z][a-z]+ (cards|amulets|followers)", core):
        return cap(np(core, ctx).text) + end
    attempts = []
    # "Select X and deal it N damage" -> "Selecciona X para infligirle N de daño"
    if m := re.fullmatch(r"select (.+?) and deal (it|them) " + N + " damage", core, re.I):
        def sel_deal(m=m):
            target = np(m.group(1), ctx)
            many = m.group(2).lower() == "them"
            return f"Selecciona {target} para infligirle{'s' if many else ''} {m.group(3)} de daño" + end
        attempts.append(sel_deal)
    if re.match(r"select ", core, re.I):
        def sel_actions():
            # "Select X and destroy it" / "Select X, evolve it, and give it +3/+3": se prueba cada corte
            body = core[len("select "):]
            for mm in re.finditer(r",? and |, ", body):
                tgt, rest = body[:mm.start()], body[mm.end():]
                try:
                    target = np(tgt, ctx)
                    acts = actions(rest, ctx, subj=target).replace("⟨SUJ⟩", "")
                except Untranslatable:
                    continue
                joiner = ", " if mm.group(0) == ", " or " y " in acts else (" e " if acts[:1].lower() == "i" else " y ")
                return f"Selecciona {target}{joiner}{acts}" + end
            raise Untranslatable(core)
        attempts.append(sel_actions)
        attempts.append(lambda: f"Selecciona {np(core[len('select '):], ctx)}" + end)
    # condición + resto
    def cond_body():
        for mm in re.finditer(r", ", core):
            cond, rest = core[:mm.start()], core[mm.end():]
            try:
                c = condition(cond, ctx)
                body = sentence(rest + end, ctx)
            except Untranslatable:
                continue
            return f"{c}, {lower1(body)}"
        raise Untranslatable(core)
    attempts.append(cond_body)

    def plain_actions():
        out = actions(core, ctx)
        return cap(out.replace("⟨SUJ⟩", "")) + end
    attempts.append(plain_actions)
    for attempt in attempts:
        try:
            return attempt()
        except Untranslatable:
            continue
    raise Untranslatable(core)


# ---------- texto completo de una carta ----------
def make_ctx(con):
    kw = {en.lower(): es for en, es in con.execute("SELECT en, es FROM keywords") if en and es}
    kw.setdefault("crest", "Blasón")
    tribes = {en: es for en, es in con.execute("SELECT en, es FROM tribes") if en and es and en != "-"}
    return {"kw": kw, "tribes": tribes, "plain": lambda key: key}


def translate(text, ctx):
    """Texto de efecto en inglés -> (texto en español, frases traducidas, frases totales)."""
    if not text:
        return text, 0, 0
    done = total = 0
    out = []
    for line in re.split(r"(\n|<hr>)", text):
        if line in ("\n", "<hr>") or not line.strip():
            out.append(line)
            continue
        # envolturas de estado (<ev>, <sev>, <ridx=0>) se conservan tal cual
        pre = re.match(r"^((?:</?(?:ev|sev|ridx[^>]*)>)*)", line).group(1)
        post = re.search(r"((?:</?(?:ev|sev|ridx[^>]*)>)*)$", line).group(1)
        body = line[len(pre):len(line) - len(post)] if post else line[len(pre):]
        tr, d, t = translate_line(body, ctx)
        done, total = done + d, total + t
        out.append(pre + tr + post)
    return euphony("".join(out)), done, total


# "y" antes de una palabra que suena /i/ pasa a "e" ("Guardia e Ímpetu"; no "y hielo") y "o" antes de una que suena
# /o/ pasa a "u" ("uno u otro", "7 u 8"), como pide la RAE. Puede haber marcas de formato en el medio; los nombres de
# cartas (en <i>, en inglés) no se tocan porque no se sabe cómo se pronuncian.
_TAGS = r"(?:\s|<(?!/?i>)[^>]+>)+"


def euphony(s):
    s = re.sub(r"\b([yY])(" + _TAGS + r")(?=[iíIÍ]|[hH][iíIÍ](?![aeoáéó]))",
               lambda m: ("e" if m.group(1) == "y" else "E") + m.group(2), s)
    s = re.sub(r"\b([oO])(" + _TAGS + r")(?=[oóOÓ]|[hH][oóOÓ]|8|11\b)",
               lambda m: ("u" if m.group(1) == "o" else "U") + m.group(2), s)
    return s


def translate_line(line, ctx):
    s, parts = protect(line, ctx["kw"])
    ctx = dict(ctx, plain=lambda key: parts.get(key + "plain", key))
    head = ""
    if m := re.match(r"^(⟦K\d+⟧(?: (?:and|y) ⟦K\d+⟧)?)\s*:\s*", s):
        head, s = m.group(1) + ": ", s[m.end():]
    elif m := re.match(r"^(\d+)\.\s+", s):
        head, s = m.group(0), s[m.end():]
    out, done, total = [], 0, 0
    for p in split_sentences(s) if s.strip() else []:
        total += 1
        try:
            out.append(sentence(p, ctx))
            done += 1
        except (Untranslatable, KeyError):
            out.append(p)  # queda en inglés
    return restore(head + " ".join(out), parts), done, total


def main():
    con = sqlite3.connect(DB)
    for table in ("cards", "specific_effects"):
        if "skill_tr" not in [r[1] for r in con.execute(f"PRAGMA table_info({table})")]:
            con.execute(f"ALTER TABLE {table} ADD COLUMN skill_tr TEXT")
    ctx = make_ctx(con)
    done = total = cards = 0
    for cid, en, es in con.execute("SELECT card_id, skill_en, skill_es FROM cards").fetchall():
        if es or not en:
            continue  # las que tienen texto oficial no se tocan
        tr, d, t = translate(en, ctx)
        done, total, cards = done + d, total + t, cards + 1
        con.execute("UPDATE cards SET skill_tr=? WHERE card_id=?", (tr, cid))
    for eid, en in con.execute("SELECT effect_id, skill_text FROM specific_effects WHERE lang='en'").fetchall():
        has_es = con.execute("SELECT 1 FROM specific_effects WHERE effect_id=? AND lang='es' AND skill_text != ''",
                             (eid,)).fetchone()
        if has_es or not en:
            continue
        tr, d, t = translate(en, ctx)
        done, total = done + d, total + t
        con.execute("UPDATE specific_effects SET skill_tr=? WHERE effect_id=? AND lang='en'", (tr, eid))
    con.commit()
    print(f"Traducción propia: {cards} cartas, {done} de {total} frases traducidas ({done / max(total, 1):.0%}).")


if __name__ == "__main__":
    main()
