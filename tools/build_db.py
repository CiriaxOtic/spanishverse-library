"""Arma cards.db (SQLite) y viewer/data.js a partir de lo que bajó fetch_cards.py.

Uso: py -3.13 tools/build_db.py
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402
DB = ROOT / "cards.db"

# Nombres oficiales sacados de los filtros de cada sitio.
CLASSES = {
    0: ("Neutral", "Neutral"), 1: ("Forestcraft", "Forestal"),
    2: ("Swordcraft", "Imperial"), 3: ("Runecraft", "Rúnico"),
    4: ("Dragoncraft", "Dracónico"), 5: ("Abysscraft", "Abismal"),
    6: ("Havencraft", "Clerical"), 7: ("Portalcraft", "Dimensional"),
}
# En los datos: 1 combatiente, 2 amuleto, 3 amuleto con cuenta regresiva, 4 hechizo.
TYPES = {
    1: ("Follower", "Combatiente"), 2: ("Amulet", "Amuleto"),
    3: ("Amulet (Countdown)", "Amuleto (cuenta regresiva)"), 4: ("Spell", "Hechizo"),
}
RARITIES = {1: ("Bronze", "Bronce"), 2: ("Silver", "Plata"), 3: ("Gold", "Oro"), 4: ("Legendary", "Legendaria")}
# Palabras clave que la versión latina todavía no tradujo; se usan como término en español.
KEYWORDS_ES = {
    "Accelerate": "Acelerar", "Crystallize": "Cristalizar", "Faith": "Fe", "Invoke": "Convocar",
    "Rally": "Subidón", "Mjerrabaine Deck": "Mjerrabaine Deck", "Skybound Art": "Skybound Art",
    "Super Skybound Art": "Super Skybound Art", "Clue": "Pista",
}
# Tipos (tribus) que la versión latina todavía no tradujo: los mismos términos propios que usa
# tools/translate_skills.py en los efectos.
TRIBES_ES = {"Loot": "Botín", "Encroacher": "Invasor", "Clue": "Pista"}
# Conceptos del glosario que la versión latina todavía no tiene: traducción propia, con las mismas palabras que
# la traducción de los efectos (tools/translate_skills.py). Los nombres de cartas quedan en inglés.
GLOSSARY_ES = {
    "Rally": ("Subidón",
              "Tu cantidad de Subidón es la cantidad de combatientes aliados que entraron al campo durante la "
              "partida. Algunas habilidades solo se activan si tu cantidad de Subidón es igual o mayor que el número "
              "indicado."),
    "Faith": ("Fe",
              "Un tipo de carta. Al comienzo de la partida, se coloca en tu área del líder una Fe por cada Fe distinta "
              "de tu mazo. Solo puedes tener una de cada Fe en tu área del líder. Cada Fe muestra su valor abajo a la "
              "derecha de su ícono; ese valor puede potenciar a las cartas que pertenecen a esa Fe."),
    "Victory Card": ("Carta de Victoria",
                     "Si la Carta de la Muerte del fondo de tu mazo se transformó en una Carta de Victoria y tienes "
                     "que robar una carta con el mazo vacío, ganas la partida."),
    "Invoke": ("Convocar",
               "Habilidad que invoca una carta desde tu mazo si hay lugar en tu campo. Si se convocan varias cartas a "
               "la vez, el orden en que entran al campo es aleatorio. Solo se puede convocar una copia de cada carta "
               "a la vez, pero cuantas más copias tengas en el mazo, más probable es que se convoque."),
    "Skybound Art": ("Skybound Art",
                     "Habilidad que se activa cuando el medidor de Skybound Art de la carta es mayor o igual a 10. El "
                     "medidor de Skybound Art de una carta es igual al número del turno actual más la cantidad de "
                     "veces que evolucionó un combatiente aliado mientras la carta estaba en tu mano."),
    "Super Skybound Art": ("Super Skybound Art",
                           "Habilidad que se activa cuando el medidor de Skybound Art de la carta es mayor o igual a "
                           "15. El medidor de Skybound Art de una carta es igual al número del turno actual más la "
                           "cantidad de veces que evolucionó un combatiente aliado mientras la carta estaba en tu "
                           "mano."),
    "Accelerate": ("Acelerar",
                   "Habilidad que te permite jugar la carta como un hechizo por un costo menor si no tienes "
                   "suficientes PJ para jugarla normalmente. Si la carta tiene otra habilidad Acelerar o Cristalizar, "
                   "se activa la de mayor costo que puedas pagar."),
    "Crystallize": ("Cristalizar",
                    "Habilidad que te permite jugar la carta como un amuleto si no tienes suficientes PJ para jugarla "
                    "normalmente. Si la carta tiene otra habilidad Cristalizar o Acelerar, se activa la de mayor costo "
                    "que puedas pagar."),
    "Clue": ("Pista",
             "Cuando un amuleto con Pista entra al campo, su contador de pistas se fija en 1 y se muestra abajo a la "
             "derecha de la carta. Los demás amuletos aliados con Pista del campo son desterrados, y sus contadores "
             "de pistas se suman al del nuevo amuleto.\n\nLas cartas con Pista no pueden ser seleccionadas por "
             "habilidades enemigas. Se destruyen cuando su contador de pistas llega a 0."),
}
# Tipos de efecto especial, igual que en el sitio oficial (specific_effect_type).
EFFECT_KEYS = {1: "crest", 2: "crystal", 3: "accelerate", 4: "faith"}

SCHEMA = """
CREATE TABLE classes  (id INTEGER PRIMARY KEY, en TEXT, es TEXT);
CREATE TABLE types    (id INTEGER PRIMARY KEY, en TEXT, es TEXT);
CREATE TABLE rarities (id INTEGER PRIMARY KEY, en TEXT, es TEXT);
CREATE TABLE sets     (id INTEGER PRIMARY KEY, en TEXT, es TEXT);
CREATE TABLE tribes   (id INTEGER PRIMARY KEY, en TEXT, es TEXT);
CREATE TABLE keywords (id INTEGER PRIMARY KEY, en TEXT, es TEXT);
CREATE TABLE cards (
    card_id INTEGER PRIMARY KEY, base_card_id INTEGER, original_card_id INTEGER,
    class_id INTEGER, type_id INTEGER, rarity_id INTEGER, set_id INTEGER,
    cost INTEGER, atk INTEGER, life INTEGER, is_token INTEGER, deck_limit INTEGER,
    in_rotation INTEGER, illustrator TEXT, cv TEXT,
    name_en TEXT, name_es TEXT,
    skill_en TEXT, skill_es TEXT,
    flavour_en TEXT, flavour_es TEXT, evo_flavour_en TEXT, evo_flavour_es TEXT,
    img_en TEXT, img_es TEXT, evo_img_en TEXT, evo_img_es TEXT,
    has_es INTEGER
);
CREATE TABLE card_tribes (card_id INTEGER, tribe_id INTEGER);
CREATE TABLE relations (card_id INTEGER, related_id INTEGER, kind TEXT);
CREATE TABLE qa (card_id INTEGER, lang TEXT, idx INTEGER, question TEXT, answer TEXT);
CREATE TABLE specific_effects (effect_id INTEGER, lang TEXT, effect_type INTEGER, effect_key TEXT, cost INTEGER, skill_text TEXT);
CREATE TABLE glossary (idx INTEGER PRIMARY KEY, title_en TEXT, text_en TEXT, title_es TEXT, text_es TEXT);
CREATE INDEX idx_rel ON relations(card_id);
CREATE INDEX idx_rel_back ON relations(related_id);
"""


def load_region(region):
    merged = {"card_details": {}, "cards": {}, "specific_effect_card_info": {}}
    names = {"tribe_names": {}, "card_set_names": {}, "skill_names": {}, "skill_replace_text_names": {}}
    for page in sorted((ROOT / "raw" / region).glob("list_*.json")):
        data = json.loads(page.read_text(encoding="utf-8"))
        for k in merged:
            merged[k].update(data.get(k) or {})
        for k in names:
            names[k].update(data.get(k) or {})
    return merged, names


def part(detail, key):
    return detail.get(key) or {}


def main():
    glob_data, glob_names = load_region("global")
    latam_data, latam_names = load_region("latam")
    es_details = latam_data["card_details"]

    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    for table, mapping in (("classes", CLASSES), ("types", TYPES), ("rarities", RARITIES)):
        con.executemany(f"INSERT INTO {table} VALUES (?,?,?)", [(k, *v) for k, v in mapping.items()])
    for table, key in (("sets", "card_set_names"), ("tribes", "tribe_names"), ("keywords", "skill_names")):
        en, es = glob_names[key], latam_names[key]
        own = {"keywords": KEYWORDS_ES, "tribes": TRIBES_ES}.get(table, {})
        rows = [(int(k), en[k], es.get(k) or own.get(en[k])) for k in en if en[k]]
        con.executemany(f"INSERT INTO {table} VALUES (?,?,?)", rows)
    # Términos como "Spellboost" vienen en una lista aparte; se guardan junto a las palabras clave.
    en, es = glob_names["skill_replace_text_names"], latam_names["skill_replace_text_names"]
    con.executemany("INSERT OR IGNORE INTO keywords VALUES (?,?,?)",
                    [(1000 + int(k), en[k], es.get(k) or KEYWORDS_ES.get(en[k])) for k in en if en[k]])

    for cid, d in glob_data["card_details"].items():
        c, evo = part(d, "common"), part(d, "evo")
        es = es_details.get(cid) or {}
        ces, evo_es = part(es, "common"), part(es, "evo")
        con.execute(
            "INSERT INTO cards VALUES (" + ",".join("?" * 28) + ")",
            (
                int(cid), c.get("base_card_id"), c.get("original_card_id"),
                c.get("class"), c.get("type"), c.get("rarity"), c.get("card_set_id"),
                c.get("cost"), c.get("atk"), c.get("life"), int(bool(c.get("is_token"))),
                c.get("deck_enabled_num"), int(bool(c.get("is_include_rotation"))),
                c.get("illustrator"), c.get("cv"),
                c.get("name"), ces.get("name"),
                # El sitio oficial muestra un solo texto de efecto (el de la carta normal, que ya
                # incluye lo que pasa al evolucionar); el skill_text de "evo" es una copia y no se usa.
                c.get("skill_text"), ces.get("skill_text"),
                c.get("flavour_text"), ces.get("flavour_text"),
                evo.get("flavour_text"), evo_es.get("flavour_text"),
                c.get("card_image_hash"), ces.get("card_image_hash"),
                evo.get("card_image_hash"), evo_es.get("card_image_hash"),
                int(bool(ces)),
            ),
        )
        con.executemany("INSERT INTO card_tribes VALUES (?,?)",
                        [(int(cid), t) for t in (c.get("tribes") or []) if t])
        for lang, src in (("en", c), ("es", ces)):
            for i, q in enumerate(src.get("questions") or []):
                con.execute("INSERT INTO qa VALUES (?,?,?,?,?)",
                            (int(cid), lang, i, q.get("question"), q.get("answer")))

    for lang, data in (("en", glob_data), ("es", latam_data)):
        for cid, info in data["specific_effect_card_info"].items():
            kind = info.get("specific_effect_type")
            con.execute("INSERT INTO specific_effects VALUES (?,?,?,?,?,?)",
                        (int(cid), lang, kind, EFFECT_KEYS.get(kind), info.get("cost"), info.get("skill_text")))

    for cid, info in glob_data["cards"].items():
        # Se conservan las autorreferencias: son cartas que crean, invocan o agregan una copia de sí mismas.
        for rid in info.get("related_card_ids") or []:
            con.execute("INSERT INTO relations VALUES (?,?,?)", (int(cid), int(rid), "related"))
        for rid in info.get("specific_effect_card_ids") or []:
            con.execute("INSERT INTO relations VALUES (?,?,?)", (int(cid), int(rid), "specific_effect"))
    load_glossary(con)
    con.commit()

    total, with_es = con.execute("SELECT COUNT(*), SUM(has_es) FROM cards").fetchone()
    print(f"cards.db listo: {total} cartas, {with_es} con texto oficial en español")


def load_glossary(con):
    """Glosario oficial. Los dos sitios lo publican en el mismo orden (el latino solo tiene menos
    entradas al final), así que se empareja por posición y se verifica con las palabras clave oficiales."""
    paths = [ROOT / "raw" / r / "glossary.json" for r in ("global", "latam")]
    if not paths[0].exists():
        return
    en = json.loads(paths[0].read_text(encoding="utf-8"))
    es = json.loads(paths[1].read_text(encoding="utf-8")) if paths[1].exists() else []
    known = {a.lower(): b.lower() for a, b in con.execute("SELECT en, es FROM keywords WHERE es IS NOT NULL")}
    known.update({a.lower(): b.lower() for a, b in con.execute("SELECT en, es FROM types")})
    mismatches = [(e["title"], s["title"]) for e, s in zip(en, es)
                  if e["title"].lower() in known and known[e["title"].lower()] != s["title"].lower()
                  and e["title"] not in KEYWORDS_ES]  # las traducciones propias no cuentan como oficiales
    if mismatches:
        print("Aviso: el glosario no coincide por posición en:", mismatches[:5], "— se muestra solo en inglés.")
        es = []
    for i, entry in enumerate(en):
        pair = es[i] if i < len(es) else {}
        own_title, own_text = GLOSSARY_ES.get(entry["title"], (None, None))
        con.execute("INSERT INTO glossary VALUES (?,?,?,?,?)",
                    (i, entry["title"], entry["text"], pair.get("title") or own_title, pair.get("text") or own_text))




if __name__ == "__main__":
    main()
