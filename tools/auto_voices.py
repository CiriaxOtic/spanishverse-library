"""Voces automáticas: asigna a cada carta su paquete de voz sin tener que grabarla.

El juego nombra los paquetes y sus eventos con el número de la carta (los ids de Wwise son el hash FNV-1 del
nombre, así que se pueden calcular):
- paquete: "dx_<carta>"
- eventos: "play_dx_<carta>_<n>"  1 = al jugarla, 2 = al atacar, 3 = al evolucionar, 4 = al ser destruida,
  5 = cada vez que se activa un efecto condicional (lo confirmó el usuario en el juego), 10 = en amuletos,
  probablemente al activarse. Variantes "_<n>_<variante>": "_3_sp" = superevolución,
  "_<n>_evo" = esa situación ya evolucionada, "_1_enh" / "_1_enh<costo>" = Enhance, "_1_sky" = Skybound Art,
  "_1_mode<k>" = al elegir el modo k, "_4_token".
  Diálogos con otro personaje: "_9_<otra carta>", "_8_<otra carta>", "_7_<otra carta>" (a veces con un "2"
  pegado al número). Unos pocos (27 de 947) tienen nombres que no se pudieron descifrar.
Orden (el que eligió el usuario): Normal = 1, sus variantes, los diálogos (por número de la otra carta; los no
descifrados primero), 5 (efecto), 2, 4, 10...; Evolucionada = 3, 3_mode, 3_sp, 2_evo, 4_evo...
Comprobado con las 35 cartas asociadas a mano: mismo paquete y mismas líneas en las 35 (en 6 el juego tiene
además líneas que no se escucharon al grabar), en el mismo orden.

Uso por consola: py -3.13 tools/auto_voices.py   (no toca las cartas ya asociadas a mano)
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voices  # noqa: E402
import wwise_pck  # noqa: E402

DB = voices.ROOT / "cards.db"
VARIANTS = (("sp", "evo", "enh", "sky", "token") + tuple(f"mode{k}" for k in range(1, 7))
            + tuple(f"enh{k}" for k in range(1, 11)))
P, M = 16777619, 2 ** 32


def bank_of(card_id):
    return wwise_pck.fnv1_32(f"dx_{card_id}")


def _continue(h, text):
    """Sigue el hash FNV-1 de un nombre ya calculado con más caracteres."""
    for b in text.lower().encode("utf-8"):
        h = ((h * P) % M) ^ b
    return h


def _natural(text):
    """Para ordenar: los números dentro del texto se comparan como números ("enh10" después de "enh9")."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def lines_for(card_id, entries, partners=()):
    """{"bank", "normal": [ids], "evo": [ids]} de la carta, o None si no tiene paquete de voz.
    entries: {banco: entrada de voices/index.json}; partners: números de las cartas con las que puede
    tener diálogos."""
    bank = bank_of(card_id)
    entry = entries.get(bank)
    if not entry:
        return None
    base = wwise_pck.fnv1_32(f"play_dx_{card_id}_")
    names = {}
    for n in range(1, 30):
        names[_continue(base, str(n))] = (n, "")
        for v in VARIANTS:
            names[_continue(base, f"{n}_{v}")] = (n, v)
    events = wwise_pck.read_events(os.path.join(voices.game_data(), entry["rel"]))
    talks = {}
    if any(eid not in names for eid, _ in events):  # diálogos: solo se calculan si hacen falta
        for k in (7, 8, 9):
            h = _continue(base, f"{k}_")
            for other in partners:
                for tail in ("", "2"):
                    talks[_continue(h, f"{other}{tail}")] = (k, int(other), tail)
    have = {ln["stream"] for ln in entry["lines"]}
    first, middle, last, evo = [], [], [], []
    for eid, media in events:
        media = [m for m in media if m in have]
        if not media:
            continue
        if eid in talks:
            middle.append(((1, *talks[eid]), media))
        elif eid not in names:
            middle.append(((0,), media))  # sin descifrar: casi seguro diálogos, van antes que los conocidos
        else:
            n, v = names[eid]
            if n == 3 and not v:
                evo.append(((0, []), media))  # al evolucionar: primera de la evolucionada
            elif n == 3 and v.startswith("mode"):
                evo.append(((1, _natural(v)), media))
            elif v in ("sp", "evo"):
                evo.append(((2 if v == "sp" else 3, [n]), media))
            elif n == 1:
                first.append(((bool(v), _natural(v)), media))
            else:
                # el efecto condicional (5) va entre las de entrada y la de pegar
                last.append(((n != 5, n, bool(v), _natural(v)), media))
    # Muchos diálogos repiten la misma frase: la versión "2" es la común (el juego la usa en otra situación,
    # a veces codificada distinto) y algunas cartas dicen lo mismo con varios personajes. Cada frase queda una
    # sola vez, en el lugar de su primera aparición.
    kept = []
    for key, media in sorted(middle, key=lambda it: it[0]):
        twin = lambda other_key: len(key) > 3 and len(other_key) > 3 and key[1:3] == other_key[1:3]
        if not any(_same_sound(bank, media[0], other[0], twin(other_key)) for other_key, other in kept):
            kept.append((key, media))
    middle = kept
    flat = lambda items: [m for _, media in sorted(items, key=lambda it: it[0]) for m in media]
    normal = flat(first) + flat(middle) + flat(last)
    return {"bank": bank, "normal": normal, "evo": flat(evo)} if normal or evo else None


def _same_sound(bank, a, b, twins=False):
    """¿Los dos audios del paquete son la misma frase?
    twins: son el diálogo común y su versión "2" con el mismo personaje. Esas a veces vienen codificadas
    distinto (la onda no coincide aunque suenen igual): se comparan por cómo suenan y por la duración."""
    pa, pb = voices.CACHE / f"{bank}_{a}.wav", voices.CACHE / f"{bank}_{b}.wav"
    if pa.read_bytes() == pb.read_bytes():
        return True
    x, sr = voices.read_wav(pa)
    y, _ = voices.read_wav(pb)
    if abs(len(x) - len(y)) > 0.05 * max(len(x), len(y)):
        return False
    if twins and abs(len(x) - len(y)) <= 0.05 * sr:  # misma duración (±0,05 s)
        return voices._similarity(voices.features(x, sr), voices.features(y, sr)) >= 0.9
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    return float(x @ y) >= 0.9 * float(np.linalg.norm(x) * np.linalg.norm(y))


def fill_mapping():
    """Agrega al mapeo las cartas que todavía no tienen voz y rearma las agregadas automáticamente.
    Devuelve cuántas se agregaron o rearmaron."""
    entries = {e["bank"]: e for e in json.loads(voices.INDEX_JSON.read_text(encoding="utf-8"))}
    mapping = voices.load_mapping()
    cards = [c for (c,) in sqlite3.connect(DB).execute("select card_id from cards")]
    added = 0
    for card_id in cards:
        if card_id in mapping and not mapping[card_id].get("auto"):
            continue  # las asociadas a mano no se tocan
        r = lines_for(card_id, entries, cards)
        if r:
            r["auto"] = True
            mapping[card_id] = r
            added += 1
    voices.save_mapping(mapping)
    return added


if __name__ == "__main__":
    if not voices.INDEX_JSON.exists():
        sys.exit("Todavía no hay índice de voces (py -3.13 tools/voices.py build).")
    print(f"Voces automáticas al día: {fill_mapping()} cartas")
