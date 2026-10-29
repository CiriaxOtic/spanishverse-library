"""«Lo nuevo» y el historial de cambios de balance. Antes de rearmar cards.db se saca una foto de cada carta
(costo, ataque, defensa y efecto); después se compara con la base nueva y se anota en cambios.json qué cartas
llegaron y qué cambió en las que ya estaban. cambios.json es del usuario: se conserva al actualizar."""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402

DB = ROOT / "cards.db"
FILE = ROOT / "cambios.json"
FIELDS = ["cost", "atk", "life", "skill_en", "skill_es"]


def snapshot():
    """{card_id: {campo: valor}} de la base actual (vacío si todavía no hay base)."""
    if not DB.exists():
        return {}
    con = sqlite3.connect(DB)
    try:
        rows = con.execute(f"SELECT card_id, {', '.join(FIELDS)} FROM cards").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {r[0]: dict(zip(FIELDS, r[1:])) for r in rows}


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _same(a, b):
    """Iguales salvo espacios o saltos de línea (el sitio a veces cambia solo el formato)."""
    norm = lambda v: re.sub(r"\s+", " ", str(v or "")).strip()
    return norm(a) == norm(b)


def record(before):
    """Compara la foto de antes con la base nueva y anota lo nuevo y los cambios. Devuelve (nuevas, cambiadas)."""
    after = snapshot()
    if not before or not after:  # primera descarga: todo es «nuevo», no tiene sentido anotarlo
        return 0, 0
    data = load()
    today = time.strftime("%Y-%m-%d")
    new = sorted(set(after) - set(before))
    if new:
        data["nuevas"] = {"fecha": today, "ids": new}
    history = data.setdefault("historial", {})
    changed = 0
    for cid in set(after) & set(before):
        diff = {f: [before[cid][f], after[cid][f]] for f in FIELDS if not _same(before[cid][f], after[cid][f])}
        # Si solo cambió el texto en español (traducción oficial nueva o corregida), no es un cambio de balance.
        if diff and set(diff) != {"skill_es"}:
            history.setdefault(str(cid), []).append({"fecha": today, "cambios": diff})
            changed += 1
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(new), changed
