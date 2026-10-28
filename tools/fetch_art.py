"""Baja las ilustraciones sin marco de las cartas desde WBGDB (base de datos de fans) a images/arte/<número>.png.

WBGDB las nombra con el número de la carta (la evolucionada es el número + 1). Son más grandes que la imagen oficial
(848x1024) y el visor del programa las usa si están; las que WBGDB no tiene siguen con la imagen oficial con marco.
En algunas cartas WBGDB tiene la normal y la evolucionada al revés: después de bajarlas se comparan con la imagen
oficial de la carta y, si están cambiadas, se dan vuelta.
Baja de a una, con una pausa, y saltea las que ya están (si se corta, sigue desde donde quedó).

Uso por consola: py -3.13 tools/fetch_art.py   (con "revisar" al final, revisa también las que ya estaban)
"""
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import watermark  # noqa: E402  (marca "© Cygames, Inc." en las ilustraciones nuevas)

from paths import ROOT  # noqa: E402
OUT = ROOT / "images" / "arte"
LIST_URL = "https://api.github.com/repos/mhmkhlrdn/WBGDB/git/trees/HEAD?recursive=1"
ART_URL = "https://mhmkhlrdn.github.io/WBGDB/Site/Art/{}.png"
HEADERS = {"User-Agent": "Spanishverse Library (uso personal)"}
PAUSE = 0.3  # segundos entre descargas, para no cargar la página
WINDOW = (67, 129, 468, 596)  # donde está la ilustración dentro de la imagen oficial (izq, arriba, der, abajo)


def available():
    """Números de las ilustraciones que tiene WBGDB."""
    req = urllib.request.Request(LIST_URL, headers=HEADERS)
    tree = json.loads(urllib.request.urlopen(req, timeout=60).read())["tree"]
    out = set()
    for item in tree:
        name = item["path"].rsplit("/", 1)[-1]
        if item["path"].startswith("Site/Art/") and name[:-4].isdigit() and name.endswith(".png"):
            out.add(int(name[:-4]))
    return out


def wanted(con):
    """Números de carta (normal y, si evoluciona, evolucionada = número + 1)."""
    ids = []
    for cid, e1, e2 in con.execute("SELECT card_id, evo_img_en, evo_img_es FROM cards"):
        ids.append(cid)
        if e1 or e2:
            ids.append(cid + 1)
    return ids


def _look(img):
    """Imagen reducida a una huella chiquita para comparar parecidos."""
    a = np.asarray(img.convert("RGB").resize((24, 28), Image.BILINEAR), dtype=float)
    a -= a.mean()
    return a.ravel() / (np.linalg.norm(a) + 1e-9)


def _official(h_en, h_es):
    for folder, h in (("eng", h_en), ("es419", h_es)):
        path = ROOT / "images" / folder / f"{h}.png"
        if h and path.exists():
            return _look(Image.open(path).crop(WINDOW))


def _art(i):
    im = Image.open(OUT / f"{i}.png")
    w, h = im.size
    tw = h * (WINDOW[2] - WINDOW[0]) / (WINDOW[3] - WINDOW[1])  # el centro, con la forma de la ventana oficial
    x = (w - tw) / 2
    return _look(im.crop((x, 0, x + tw, h)))


def fix_swapped(con, cards):
    """Da vuelta la normal y la evolucionada de estas cartas si se parecen más a la imagen oficial cambiadas."""
    fixed = []
    for cid, name, n1, n2, e1, e2 in con.execute(
            "SELECT card_id, name_en, img_en, img_es, evo_img_en, evo_img_es FROM cards"):
        if cid not in cards or not (OUT / f"{cid}.png").exists() or not (OUT / f"{cid + 1}.png").exists():
            continue
        normal, evo = _official(n1, n2), _official(e1, e2)
        if normal is None or evo is None:
            continue
        a, b = _art(cid), _art(cid + 1)
        if normal @ b + evo @ a > normal @ a + evo @ b:
            tmp = OUT / f"{cid}.swap"
            (OUT / f"{cid}.png").replace(tmp)
            (OUT / f"{cid + 1}.png").replace(OUT / f"{cid}.png")
            tmp.replace(OUT / f"{cid + 1}.png")
            watermark.swap_entries(f"{cid}.png", f"{cid + 1}.png")
            fixed.append(name)
    return fixed


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ROOT / "cards.db")
    have = available()
    todo = [i for i in wanted(con) if i in have]
    missing = [i for i in todo if not (OUT / f"{i}.png").exists()]
    print(f"WBGDB tiene {len(todo)} ilustraciones de estas cartas; faltan bajar {len(missing)}.", flush=True)
    done = failed = 0
    for n, i in enumerate(missing, 1):
        tmp = OUT / f"{i}.part"
        try:
            req = urllib.request.Request(ART_URL.format(i), headers=HEADERS)
            tmp.write_bytes(urllib.request.urlopen(req, timeout=60).read())
            tmp.replace(OUT / f"{i}.png")
            done += 1
        except Exception as e:
            failed += 1
            print(f"  no se pudo bajar {i}: {e}", flush=True)
            if tmp.exists():
                tmp.unlink()
        if n % 50 == 0 or n == len(missing):
            print(f"  {n}/{len(missing)}", flush=True)
        time.sleep(PAUSE)
    print(f"Ilustraciones: {done} bajadas, {failed} con error.", flush=True)
    for name in fix_swapped(con, {i - 1 for i in missing} | set(missing)):
        print(f"  {name}: la normal y la evolucionada venían al revés, se dieron vuelta.", flush=True)
    put, had = watermark.process([OUT / f"{i}.png" for i in missing if (OUT / f"{i}.png").exists()])
    if put or had:
        print(f"Marca de agua: puesta en {put}; {had} ya la traían.", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["revisar"]:  # revisa todas las ya bajadas, no solo las nuevas
        con = sqlite3.connect(ROOT / "cards.db")
        fixed = fix_swapped(con, {cid for (cid,) in con.execute("SELECT card_id FROM cards")})
        print(f"Invertidas corregidas: {len(fixed)}", *fixed, sep="\n  ")
    else:
        main()
