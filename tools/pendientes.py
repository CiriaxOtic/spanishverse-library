"""Lo que falta traducir después de una actualización (solo lo usa quien mantiene el programa).

    py -3.13 tools/pendientes.py

Escribe work/pendientes.txt con las cartas cuyo efecto no tiene español oficial ni traducción propia (el traductor
de tools/translate_skills.py no supo armar alguna frase) y cuenta la ambientación y las preguntas sin traducir
(esas se arman con «translate_lore.py pendientes»)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402


def effects_missing(con):
    """[(id, nombre, texto en inglés)] de efectos sin español oficial ni traducción propia."""
    rows = con.execute("SELECT card_id, name_en, skill_en FROM cards WHERE COALESCE(skill_en, '') != '' "
                       "AND COALESCE(skill_es, '') = '' AND COALESCE(skill_tr, '') = '' ORDER BY set_id, card_id")
    return list(rows)


def lore_missing(con):
    """Cuántos textos de ambientación no tienen español oficial ni traducción propia."""
    n = 0
    for en, es, tr in (("flavour_en", "flavour_es", "flavour_tr"), ("evo_flavour_en", "evo_flavour_es", "evo_flavour_tr")):
        n += con.execute(f"SELECT COUNT(*) FROM cards WHERE COALESCE({en}, '') != '' AND COALESCE({es}, '') = '' "
                         f"AND COALESCE({tr}, '') = ''").fetchone()[0]
    return n


def main():
    con = sqlite3.connect(ROOT / "cards.db")
    effects, lore = effects_missing(con), lore_missing(con)
    con.close()
    out = ROOT / "work" / "pendientes.txt"
    out.parent.mkdir(exist_ok=True)
    lines = [f"Efectos sin traducir: {len(effects)}", f"Ambientaciones sin traducir: {lore}", ""]
    lines += [f"{cid}  {name}\n    {text}" for cid, name, text in effects]
    if lore:
        lines += ["", "Para la ambientación: py -3.13 tools/translate_lore.py pendientes"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:2]), f"\nDetalle en {out}")
    return len(effects), lore


if __name__ == "__main__":
    main()
