"""Mazos: reglas, costo en viales, códigos para el juego y mazos guardados (lo usa el armador de mazos del programa).

Formato del mazo de la página oficial ("hash"): "<formato>.<clase>.<carta>.<carta>..." con las 40 cartas;
formato 1 = Rotación, 2 = Ilimitado; cada carta es su número escrito con 4 caracteres de este alfabeto
(base 64). Con ese hash la página oficial da el código de 4 letras que se escribe en el juego
(/web/DeckCode/publish) y, al revés, devuelve el mazo de un código (/web/DeckCode/getDeck).
Los costos en viales son los que calcula la página oficial ("Create"), comprobados carta por carta:
Bronce 50, Plata 90, Oro 750, Legendaria 3500; las cartas de Basic no se crean (0).
"""
import json
import re
import urllib.request
import http.cookiejar
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402
SAVED = ROOT / "mazos"
SITE = "https://shadowverse-wb.com"
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
DECK_SIZE = 40
ROTATION, UNLIMITED = 1, 2
VIALS = {1: 50, 2: 90, 3: 750, 4: 3500}  # por rareza
BASIC_SET = 10000


def vials(card):
    """Viales para crear una copia de la carta."""
    return 0 if card["set_id"] == BASIC_SET else VIALS.get(card["rarity_id"], 0)


def deck_hash(fmt, class_id, counts):
    """Mazo en el formato de la página oficial. counts: {número de carta: copias}."""
    ids = sorted(cid for cid, n in counts.items() for _ in range(n))
    enc = lambda n: "".join(ALPHABET[(n >> (6 * (3 - i))) & 63] for i in range(4))
    return ".".join([str(fmt), str(class_id)] + [enc(cid) for cid in ids])


def official_url(fmt, class_id, counts):
    """Página del mazo en el sitio oficial (la de LATAM no tiene el armador de mazos: va la global en inglés)."""
    return f"{SITE}/en/deck/detail/?hash={deck_hash(fmt, class_id, counts)}"


def problems(cards, fmt, class_id, counts):
    """Lo que impide usar el mazo en el juego (lista vacía = mazo válido)."""
    out = []
    total = sum(counts.values())
    n = abs(DECK_SIZE - total)
    cards_text = f"{n} carta" if n == 1 else f"{n} cartas"
    if total < DECK_SIZE:
        out.append(f"{'Falta' if n == 1 else 'Faltan'} {cards_text} (un mazo tiene {DECK_SIZE}).")
    elif total > DECK_SIZE:
        out.append(f"{'Sobra' if n == 1 else 'Sobran'} {cards_text} (un mazo tiene {DECK_SIZE}).")
    if fmt == ROTATION:
        old = [cards[cid]["name_en"] for cid in counts if not cards[cid]["in_rotation"]]
        if old:
            out.append("No se pueden usar en Rotación: " + ", ".join(sorted(old)) + ".")
    other = [cards[cid]["name_en"] for cid in counts if cards[cid]["class_id"] not in (0, class_id)]
    if other:
        out.append("Son de otra clase: " + ", ".join(sorted(other)) + ".")
    return out


# ---------- página oficial (necesita internet) ----------
def _session():
    """Abre una sesión en la página oficial: devuelve (abridor con cookies, encabezados, token)."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    headers = {"User-Agent": "Mozilla/5.0 (Spanishverse Library)", "Accept": "application/json",
               "Lang": "es", "X-Requested-With": "XMLHttpRequest"}
    status = _call(opener, urllib.request.Request(f"{SITE}/web/Login/status", headers=headers))
    return opener, headers, status["data_headers"].get("csrf_token", "")


class Rejected(Exception):
    """La página respondió, pero no aceptó el pedido (código inexistente o vencido, mazo inválido)."""


def _call(opener, req):
    data = json.loads(opener.open(req, timeout=30).read())
    if (data.get("data_headers") or {}).get("result_code") != 1:
        raise Rejected("la página oficial no aceptó el pedido")
    return data


def _post(path, body):
    opener, headers, token = _session()
    req = urllib.request.Request(f"{SITE}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={**headers, "Content-Type": "application/json", "X-Csrf-Token": token})
    return _call(opener, req)["data"]


def publish_code(fmt, class_id, counts):
    """Código de 4 letras para cargar el mazo en el juego (lo da la página oficial)."""
    return _post("/web/DeckCode/publish", {"hash": deck_hash(fmt, class_id, counts)})["deck_code"]


def fetch_deck(code):
    """(formato, clase, {carta: copias}) del mazo de un código del juego."""
    data = _post("/web/DeckCode/getDeck", {"deck_code": code.strip()})
    counts = {int(cid): int(n) for cid, n in data["deck_card_num"].items()}
    return int(data["battle_format"]), int(data["class_id"]), counts


# ---------- mazos guardados (carpeta mazos/) ----------
def _file(name):
    return SAVED / (re.sub(r'[<>:"/\\|?*]', "_", name.strip()) + ".json")


def save(name, fmt, class_id, counts, path=None):
    SAVED.mkdir(exist_ok=True)
    data = {"name": name, "format": fmt, "class": class_id, "cards": {str(k): v for k, v in counts.items() if v}}
    (path or _file(name)).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path):
    """(nombre, formato, clase, {carta: copias}) de un mazo guardado."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["name"], data["format"], data["class"], {int(k): v for k, v in data["cards"].items()}


def saved_decks():
    """[(nombre, archivo)] de los mazos guardados, por nombre."""
    out = []
    for p in SAVED.glob("*.json"):
        try:
            out.append((load(p)[0], p))
        except (ValueError, KeyError):
            continue
    return sorted(out, key=lambda it: it[0].lower())


def exists(name):
    return _file(name).exists()


def delete(name):
    _file(name).unlink(missing_ok=True)
