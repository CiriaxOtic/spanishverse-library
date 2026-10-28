"""Descarga la lista oficial de cartas (global en inglés y LATAM en español).

Guarda las respuestas crudas de la API en raw/<region>/ y las imágenes en
images/<carpeta_idioma>/. Va despacio a propósito para no cargar el sitio.

Uso:
    py -3.13 tools/fetch_cards.py            # datos + imágenes
    py -3.13 tools/fetch_cards.py --no-images
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402
PAGE_SIZE = 30
DELAY = 1.5  # segundos entre pedidos
QUERY = "class=0,1,2,3,4,5,6,7&cost=0,1,2,3,4,5,6,7,8,9,10"

REGIONS = {
    "global": {"host": "https://shadowverse-wb.com", "lang": "en", "img": "eng"},
    "latam": {"host": "https://latam.shadowverse-wb.com", "lang": "es", "img": "es419"},
}


class Maintenance(Exception):
    pass


def get(url, lang=None, raw=False):
    headers = {"User-Agent": "Mozilla/5.0 (personal card reference)", "Accept": "*/*"}
    if lang:
        headers["lang"] = lang
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            break
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3:
                raise
            print(f"  reintento ({e})", flush=True)
            time.sleep(5 * (attempt + 1))
    time.sleep(DELAY)
    if raw:
        return body
    data = json.loads(body)
    if "maintenance" in data:
        raise Maintenance(data["maintenance"])
    return data


def fetch_region(name, cfg):
    out = ROOT / "raw" / name
    out.mkdir(parents=True, exist_ok=True)
    offset, total = 0, None
    while total is None or offset < total:
        url = f"{cfg['host']}/web/CardList/cardList?offset={offset}&{QUERY}"
        data = get(url, cfg["lang"])["data"]
        total = data["count"]
        (out / f"list_{offset:05d}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"[{name}] {min(offset + PAGE_SIZE, total)}/{total}", flush=True)
        offset += PAGE_SIZE
    return total


def fetch_glossary(name, cfg):
    """Glosario oficial (el botón "Glossary" de la página de cada carta)."""
    data = get(f"{cfg['host']}/web/System/glossaryList", cfg["lang"])["data"]
    out = ROOT / "raw" / name / "glossary.json"
    out.write_text(json.dumps(data["glossary_list"], ensure_ascii=False), encoding="utf-8")
    print(f"[{name}] glosario: {len(data['glossary_list'])} entradas", flush=True)


def card_images(region):
    """{(card_id, "common"|"evo"): hash} de las imágenes de una región."""
    images = {}
    for page in sorted((ROOT / "raw" / region).glob("list_*.json")):
        data = json.loads(page.read_text(encoding="utf-8"))
        for cid, detail in data["card_details"].items():
            for side in ("common", "evo"):
                h = (detail.get(side) or {}).get("card_image_hash")
                if h:
                    images[(cid, side)] = h
    return images


def fetch_images(name, cfg, skip=()):
    """Baja las imágenes de una región, salvo las de `skip` (cartas que ya tienen versión en español)."""
    folder = ROOT / "images" / cfg["img"]
    folder.mkdir(parents=True, exist_ok=True)
    wanted = {h for key, h in card_images(name).items() if key not in skip}
    todo = [h for h in sorted(wanted) if not (folder / f"{h}.png").exists()]
    print(f"[{name}] imágenes nuevas: {len(todo)}", flush=True)
    for i, h in enumerate(todo, 1):
        url = f"{cfg['host']}/uploads/card_image/{cfg['img']}/card/{h}.png"
        try:
            (folder / f"{h}.png").write_bytes(get(url, raw=True))
        except urllib.error.HTTPError as e:
            print(f"  {h}: HTTP {e.code}", flush=True)
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}", flush=True)


def fetch_all(images=True, region=None):
    """Baja las listas, el glosario y (si images) las imágenes nuevas. Lanza Maintenance si el sitio está cerrado."""
    regions = {region: REGIONS[region]} if region else REGIONS
    for name, cfg in regions.items():
        fetch_region(name, cfg)
        fetch_glossary(name, cfg)
    if images:
        # Primero las imágenes en español; en inglés solo las de cartas sin versión latina.
        fetch_images("latam", REGIONS["latam"])
        fetch_images("global", REGIONS["global"], skip=set(card_images("latam")))
    print("listo")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--region", choices=list(REGIONS))
    args = ap.parse_args()
    try:
        fetch_all(not args.no_images, args.region)
    except Maintenance as m:
        print(f"El sitio está en mantenimiento ({m}). Probá más tarde.")
        sys.exit(2)


if __name__ == "__main__":
    main()
