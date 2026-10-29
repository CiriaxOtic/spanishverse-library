"""Copias de seguridad de lo que es del usuario (mazos, favoritas, ajustes y voces asociadas a mano), en
respaldos/<fecha>/. Se hace una antes de cada actualización y antes de instalar una versión nueva; se guardan las
últimas KEEP. Se restauran desde «Ayuda → Copias de seguridad»."""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402

BACKUPS = ROOT / "respaldos"
KEEP = 5
ITEMS = ["mazos", "favoritos.json", "ajustes.json", "voices/mapping.json", "voices/recorded"]


def make(reason):
    """Copia lo del usuario a respaldos/<fecha>/ y borra las copias más viejas. Devuelve la carpeta o None."""
    import config
    present = [rel for rel in ITEMS if (ROOT / rel).exists()]
    if not present:
        return None
    dest = BACKUPS / time.strftime("%Y-%m-%d_%H%M%S")
    try:
        for rel in present:
            src, dst = ROOT / rel, dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
        decks = len(list((ROOT / "mazos").glob("*.json"))) if (ROOT / "mazos").exists() else 0
        (dest / "copia.json").write_text(json.dumps({"fecha": time.strftime("%d/%m/%Y %H:%M"), "motivo": reason,
                                                     "version": config.VERSION, "mazos": decks},
                                                    ensure_ascii=False), encoding="utf-8")
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        return None
    for old in list_backups()[KEEP:]:
        shutil.rmtree(old[0], ignore_errors=True)
    return dest


def list_backups():
    """[(carpeta, datos)] de la más nueva a la más vieja."""
    out = []
    if BACKUPS.exists():
        for d in sorted(BACKUPS.iterdir(), reverse=True):
            try:
                out.append((d, json.loads((d / "copia.json").read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
    return out


def restore(folder):
    """Vuelve a poner lo de una copia (lo que hay ahora se guarda antes en otra copia, por las dudas)."""
    make("antes de restaurar una copia")
    for rel in ITEMS:
        src, dst = Path(folder) / rel, ROOT / rel
        if not src.exists():
            continue
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.rglob("*"):
                if f.is_file():
                    (dst / f.relative_to(src)).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst / f.relative_to(src))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
