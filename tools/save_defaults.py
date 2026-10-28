"""Guarda el estado actual como "por defecto": las voces de todas las cartas y las traducciones propias.

- defaults/voces.json: la voz de cada carta (lo que usa el botón «Por defecto» del asistente de voces 🎙).
- defaults/traducciones.json: copia de la traducción propia de los efectos (solo de respaldo: el programa no deja
  modificarlas y «Actualizar cartas» las vuelve a generar desde el inglés).

Usarlo solo cuando el estado actual esté revisado y bien, porque reemplaza el "por defecto" anterior.
Uso por consola: py -3.13 tools/save_defaults.py
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voices  # noqa: E402

DB = voices.ROOT / "cards.db"


def main():
    voices.DEFAULTS.mkdir(parents=True, exist_ok=True)
    mapping = voices.load_mapping()
    voices.DEFAULT_MAPPING.write_text(
        json.dumps({str(k): v for k, v in mapping.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
    con = sqlite3.connect(DB)
    cards = {str(cid): tr for cid, tr in con.execute("SELECT card_id, skill_tr FROM cards WHERE skill_tr IS NOT NULL")}
    effects = {str(eid): tr for eid, tr in
               con.execute("SELECT effect_id, skill_tr FROM specific_effects WHERE skill_tr IS NOT NULL")}
    (voices.DEFAULTS / "traducciones.json").write_text(
        json.dumps({"cartas": cards, "efectos_especiales": effects}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Por defecto guardado: voces de {len(mapping)} cartas, traducciones de {len(cards)} cartas "
          f"y {len(effects)} efectos especiales.")


if __name__ == "__main__":
    main()
