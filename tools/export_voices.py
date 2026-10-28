"""Exporta "Voces por carta.json": la lista completa de qué audios del juego le corresponden a cada carta, con
explicaciones, para que una persona o una IA pueda reconstruir las voces si se pierden.

Uso por consola: py -3.13 tools/export_voices.py   (usa las voces actuales del programa: voices/mapping.json)
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_voices  # noqa: E402
import voices  # noqa: E402
import wwise_pck  # noqa: E402

DB = voices.ROOT / "cards.db"
OUT = voices.ROOT / "Voces por carta.json"

EXPLANATION = {
    "que_es": "Lista de los audios (voces y sonidos) del juego Shadowverse: Worlds Beyond que le corresponden a cada "
              "carta en Spanishverse Library, en el orden en que el programa los reproduce.",
    "como_leerla": [
        "Cada carta tiene 'normal' (la carta sin evolucionar) y 'evolucionada'. Cada línea trae su 'situacion' "
        "(cuándo suena en el juego), el 'audio_id' y el archivo WAV que arma el programa.",
        "Orden de 'normal': al jugarla, sus variantes (Aumento, Skybound Art, cada Modo), los diálogos con otros "
        "personajes, su efecto, al atacar, al morir. Orden de 'evolucionada': al evolucionar, al superevolucionar, "
        "al atacar evolucionada, al morir evolucionada.",
        "Los audios están en los paquetes de sonido del juego (carpeta ShadowverseWB_Data\\Persistent\\dat). El "
        "paquete de cada carta se llama internamente 'dx_<número de carta>'; su número ('paquete_id') es el hash "
        "FNV-1 de 32 bits de ese nombre en minúsculas. Cada situación es un evento 'play_dx_<carta>_<n>' "
        "(1 jugar, 2 atacar, 3 evolucionar, 3_sp superevolucionar, 4 morir, 5 efecto, 9_<otra carta> diálogo).",
        "Si una línea dice 'paquete_id' distinto al de la carta, ese audio está en el paquete de otra carta "
        "(líneas compartidas).",
    ],
    "como_reconstruir": [
        "1) Con el juego instalado, correr 'py -3.13 tools/voices.py build' (convierte los audios a WAV en "
        "voices/cache, con nombre '<paquete_id>_<audio_id>.wav').",
        "2) Para cada carta de esta lista, el programa espera en voices/mapping.json: "
        "{\"<carta_id>\": {\"bank\": <paquete_id>, \"normal\": [<audio_id>, ...], \"evo\": [<audio_id>, ...]}}. "
        "Una línea de otro paquete se escribe [<paquete_id>, <audio_id>] en vez de solo <audio_id>.",
        "3) La misma información, ya en ese formato, está en defaults/voces.json (lo que usa el botón «Por "
        "defecto»).",
    ],
}


def situations(card_id, bank, entries, partners, names_en):
    """{audio_id: (situación, evento)} de las líneas del paquete de la carta."""
    entry = entries.get(bank)
    if not entry:
        return {}
    base = f"play_dx_{card_id}_"
    labels = {}
    for n in range(1, 30):
        labels[wwise_pck.fnv1_32(f"{base}{n}")] = f"{n}"
        for v in auto_voices.VARIANTS:
            labels[wwise_pck.fnv1_32(f"{base}{n}_{v}")] = f"{n}_{v}"
    for k in (7, 8, 9):
        for other in partners:
            for tail in ("", "2"):
                labels[wwise_pck.fnv1_32(f"{base}{k}_{other}{tail}")] = f"{k}_{other}{tail}"
    out = {}
    for eid, media in wwise_pck.read_events(os.path.join(voices.game_data(), entry["rel"])):
        label = labels.get(eid)
        for m in media:
            out[m] = (describe(label, names_en), f"play_dx_{card_id}_{label}" if label else f"(evento {eid})")
    return out


def describe(label, names_en):
    if label is None:
        return "situación no identificada"  # nombre interno sin descifrar (en combatientes, casi siempre un diálogo)
    if m := re.fullmatch(r"[789]_(\d{8})(2?)", label):
        who = names_en.get(int(m.group(1)), m.group(1))
        return f"diálogo con {who}" + (" (otra situación, misma frase)" if m.group(2) else "")
    n, _, v = label.partition("_")
    base = {"1": "al jugarla", "2": "al atacar", "3": "al evolucionar", "4": "al morir",
            "5": "al activarse su efecto", "10": "al activarse"}.get(n, f"situación {n}")
    if v == "sp":
        return "al superevolucionar"
    if v == "evo":
        return base + " (evolucionada)"
    if v.startswith("enh"):
        return base + " con Aumento" + (f" ({v[3:]})" if v[3:] else "")
    if v == "sky":
        return base + " con Skybound Art"
    if v.startswith("mode"):
        return base + f" eligiendo el Modo {v[4:]}"
    if v == "token":
        return base + " (token)"
    return base


def main():
    con = sqlite3.connect(DB)
    cards = {cid: (en, es) for cid, en, es in con.execute("SELECT card_id, name_en, name_es FROM cards")}
    names_en = {cid: en for cid, (en, _) in cards.items()}
    partners = list(cards)
    entries = {e["bank"]: e for e in json.loads(voices.INDEX_JSON.read_text(encoding="utf-8"))}
    mapping = voices.load_mapping()
    out_cards = []
    for cid in sorted(mapping):
        v = mapping[cid]
        if not (v.get("normal") or v.get("evo")):
            continue
        bank = v["bank"]
        known = situations(cid, bank, entries, partners, names_en)
        other_known = {}

        def line(item, order):
            if isinstance(item, str):  # grabación propia del usuario
                return {"orden": order, "situacion": "grabación propia", "archivo": f"voices/recorded/{item[4:]}"}
            b, sid = voices.ref(item, bank)
            if b == bank:
                sit, event = known.get(sid, ("(sin dato)", ""))
            else:
                if b not in other_known:
                    # el paquete de otra carta, o de una variante que no está en la lista (mismo número + 1..9)
                    owner = next((c + d for c in cards for d in range(10) if auto_voices.bank_of(c + d) == b), None)
                    other_known[b] = (owner, situations(owner, b, entries, partners, names_en) if owner else {})
                owner, known_other = other_known[b]
                sit, event = known_other.get(sid, ("línea compartida de otra carta", ""))
                sit += f" (del paquete dx_{owner})" if owner else ""
            return {"orden": order, "situacion": sit, "audio_id": sid, "paquete_id": b, "evento": event,
                    "wav": f"voices/cache/{b}_{sid}.wav"}

        en, es = cards.get(cid, (str(cid), None))
        entry = entries.get(bank, {})
        out_cards.append({
            "carta_id": cid, "nombre": en, "nombre_es": es,
            "paquete": f"dx_{cid}" if bank == auto_voices.bank_of(cid) else None, "paquete_id": bank,
            "archivo_del_juego": entry.get("rel"),
            "asignada": "automáticamente" if v.get("auto") else "a mano (escuchada en el juego)",
            "normal": [line(item, i) for i, item in enumerate(v.get("normal", []), 1)],
            "evolucionada": [line(item, i) for i, item in enumerate(v.get("evo", []), 1)],
        })
    OUT.write_text(json.dumps({"explicacion": EXPLANATION, "total_cartas": len(out_cards), "cartas": out_cards},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Listo: {OUT.name} con {len(out_cards)} cartas.")


if __name__ == "__main__":
    main()
