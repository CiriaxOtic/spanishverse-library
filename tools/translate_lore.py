"""Traducción propia de las ambientaciones (normal y evolucionada) y de las preguntas oficiales que todavía no tienen
texto oficial en español.

Son textos libres (no siguen moldes como los efectos), así que se tradujeron uno por uno y quedan guardados en
traducciones/lore.json: {"f:<carta>" | "e:<carta>" | "q:<carta>:<n>" | "a:<carta>:<n>": {"en": original, "es": traducción}}
(f = ambientación, e = ambientación evolucionada, q / a = pregunta y respuesta n). Cada traducción guarda el inglés del
que salió: si la página cambia el texto, esa traducción deja de usarse hasta revisarla. Estilo: el de la traducción
oficial latina (tú), con las palabras clave oficiales; los nombres de cartas quedan en inglés.

Uso por consola:
    py -3.13 tools/translate_lore.py              copia las traducciones a cards.db (lo hace «Actualizar cartas»)
    py -3.13 tools/translate_lore.py pendientes   arma work/lore/pendiente_NN.json con lo que falta traducir
    py -3.13 tools/translate_lore.py guardar      suma a lore.json lo traducido en work/lore/hecho_NN.json
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402
DB = ROOT / "cards.db"
STORE = ROOT / "traducciones" / "lore.json"
WORK = ROOT / "work" / "lore"
BATCH = 7000  # caracteres de inglés por tanda


def load():
    return json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}


def sources(con):
    """{clave: texto en inglés} de todo lo que no tiene texto oficial en español, en orden de carta."""
    out = {}
    for cid, f_en, f_es, e_en, e_es in con.execute(
            "SELECT card_id, flavour_en, flavour_es, evo_flavour_en, evo_flavour_es FROM cards ORDER BY card_id"):
        if f_en and not f_es:
            out[f"f:{cid}"] = f_en
        if e_en and not e_es:
            out[f"e:{cid}"] = e_en
    official = {cid for (cid,) in con.execute("SELECT DISTINCT card_id FROM qa WHERE lang='es'")}
    for cid, idx, q, a in con.execute("SELECT card_id, idx, question, answer FROM qa WHERE lang='en' ORDER BY card_id, idx"):
        if cid not in official:
            out[f"q:{cid}:{idx}"] = q
            out[f"a:{cid}:{idx}"] = a
    return out


def pending():
    """Arma las tandas de lo que falta traducir (las de una misma carta, juntas)."""
    store = load()
    todo = [(k, en) for k, en in sources(sqlite3.connect(DB)).items() if store.get(k, {}).get("en") != en]
    WORK.mkdir(parents=True, exist_ok=True)
    for old in WORK.glob("pendiente_*.json"):
        old.unlink()
    batches, cur, size, last_card = [], [], 0, None
    for k, en in todo:
        card = k.split(":")[1]
        if size >= BATCH and card != last_card:
            batches.append(cur)
            cur, size = [], 0
        cur.append({"k": k, "en": en})
        size += len(en)
        last_card = card
    if cur:
        batches.append(cur)
    for i, b in enumerate(batches, 1):
        (WORK / f"pendiente_{i:02d}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Faltan {len(todo)} textos en {len(batches)} tandas (work/lore/pendiente_NN.json).")


def save_done():
    """Suma a lore.json las traducciones de work/lore/hecho_NN.json ({clave: español})."""
    store, src = load(), sources(sqlite3.connect(DB))
    added = 0
    for path in sorted(WORK.glob("hecho_*.json")):
        for k, es in json.loads(path.read_text(encoding="utf-8")).items():
            # Lo que ya está guardado para el mismo inglés no se pisa: lore.json puede tener correcciones posteriores
            # (ortografía, puntuación) que los hecho_NN viejos no tienen.
            if k in src and es.strip() and store.get(k, {}).get("en") != src[k]:
                store[k] = {"en": src[k], "es": es.strip()}
                added += 1
    STORE.parent.mkdir(exist_ok=True)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{added} traducciones guardadas; lore.json tiene {len(store)}.")


def apply():
    """Copia a cards.db las traducciones que siguen correspondiendo al texto en inglés actual."""
    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(cards)")]
    for col in ("flavour_tr", "evo_flavour_tr"):
        if col not in cols:
            con.execute(f"ALTER TABLE cards ADD COLUMN {col} TEXT")
    con.execute("UPDATE cards SET flavour_tr=NULL, evo_flavour_tr=NULL")
    con.execute("DELETE FROM qa WHERE lang='tr'")
    store, src = load(), sources(con)
    ok = {k: v["es"] for k, v in store.items() if src.get(k) == v["en"]}
    for k, es in ok.items():
        kind, cid = k.split(":")[0], int(k.split(":")[1])
        if kind in ("f", "e"):
            con.execute(f"UPDATE cards SET {'flavour_tr' if kind == 'f' else 'evo_flavour_tr'}=? WHERE card_id=?", (es, cid))
    for k, es in ok.items():
        if k.startswith("q:") and ("a:" + k[2:]) in ok:
            _, cid, idx = k.split(":")
            con.execute("INSERT INTO qa (card_id, lang, idx, question, answer) VALUES (?, 'tr', ?, ?, ?)",
                        (int(cid), int(idx), es, ok["a:" + k[2:]]))
    con.commit()
    print(f"Ambientaciones y preguntas: {len(ok)} de {len(src)} textos con traducción propia.")


if __name__ == "__main__":
    {"pendientes": pending, "guardar": save_done}.get(sys.argv[1] if len(sys.argv) > 1 else "", apply)()
