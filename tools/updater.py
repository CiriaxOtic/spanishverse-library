"""Actualización completa del programa, paso por paso (lo que antes hacía «Actualizar cartas.bat»).

1. Novedades de GitHub (si el programa tiene GitHub configurado en tools/config.py): versión nueva del programa,
   traducciones propias más nuevas (traducciones/*.json), voces asociadas a mano y paquetes de imágenes.
2. Cartas oficiales (global y LATAM) e imágenes nuevas del sitio oficial; se rearma cards.db.
3. Traducción propia de los efectos, correcciones publicadas y ambientaciones/preguntas traducidas.
4. Voces: convierte los audios nuevos del juego (si está instalado en Steam) y asigna la voz a las cartas nuevas.
5. Ilustraciones sin marco: paquetes de GitHub y, lo que falte, de WBGDB; les pone la marca de Cygames.

Cada paso que falla (sin internet, sitio en mantenimiento, juego no instalado) se informa y se sigue con el resto.
run() avisa el progreso con progress(texto) y devuelve un resumen.
"""
import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from paths import ROOT, game_data  # noqa: E402

DB = ROOT / "cards.db"
TRAD = ROOT / "traducciones"
LOCAL_STATE = ROOT / "datos_descargados.json"  # qué versión de cada archivo de GitHub ya se bajó
HEADERS = {"User-Agent": "Mozilla/5.0 (Spanishverse Library)"}


class _Lines(io.TextIOBase):
    """Manda cada línea que imprimen los pasos (print) a progress()."""

    def __init__(self, progress):
        self.progress, self.buf = progress, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.progress("  " + line.strip())
        return len(s)


def _get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
        return r.read()


def _state():
    try:
        return json.loads(LOCAL_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state):
    LOCAL_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _version_tuple(v):
    return tuple(int(x) for x in str(v).split(".") if x.isdigit())


# ---------- GitHub ----------
def remote_info():
    """datos/version.json del repositorio, o None si no hay GitHub configurado o no hay internet."""
    if not config.GITHUB_USER:
        return None
    try:
        return json.loads(_get(config.raw_url("datos/version.json"), timeout=20))
    except Exception:
        return None


def new_version(info):
    """Versión nueva del programa publicada en GitHub (texto), o None."""
    if info and _version_tuple(info.get("app", "0")) > _version_tuple(config.VERSION):
        return info["app"]
    return None


def sync_files(info, progress):
    """Baja los archivos de datos publicados que cambiaron (traducciones, correcciones, voces asociadas a mano)."""
    state = _state()
    got = 0
    for path, digest in (info.get("archivos") or {}).items():
        if state.get(path) == digest and (ROOT / path).exists():
            continue
        try:
            data = _get(config.raw_url(path))
        except Exception as e:
            progress(f"  no se pudo bajar {path}: {e}")
            continue
        if hashlib.sha1(data).hexdigest() != digest:
            progress(f"  {path} llegó incompleto; queda el de antes")
            continue
        if path == "voices/mapping.json":
            _merge_mapping(json.loads(data))
        else:
            (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / path).write_bytes(data)
        state[path] = digest
        got += 1
    _save_state(state)
    progress(f"  traducciones y correcciones: {got} archivo(s) nuevo(s)")


def _merge_mapping(remote):
    """Voces asociadas a mano publicadas: se suman sin pisar las que el usuario asoció él mismo."""
    import voices
    local = voices.load_mapping()
    for k, v in remote.items():
        if v.get("auto"):
            continue
        mine = local.get(int(k))
        if mine is None or mine.get("auto") or mine.get("publicada"):
            local[int(k)] = dict(v, publicada=True)
    voices.save_mapping(local)


def sync_packs(info, progress):
    """Paquetes de imágenes (zip): se bajan si falta alguno de sus archivos."""
    for pack in info.get("paquetes") or []:
        folder = ROOT / pack["carpeta"]
        missing = [f for f in pack.get("archivos", []) if not (folder / f).exists()]
        if not missing:
            continue
        progress(f"  bajando «{pack['nombre']}» ({len(missing)} imágenes que faltan, {pack.get('tamaño', '?')})...")
        tmp = ROOT / (pack["archivo"] + ".part")
        try:
            with urllib.request.urlopen(urllib.request.Request(pack["url"], headers=HEADERS), timeout=60) as r, \
                    open(tmp, "wb") as out:
                total = int(r.headers.get("Content-Length") or 0)
                done, last = 0, -1
                while chunk := r.read(1 << 20):
                    out.write(chunk)
                    done += len(chunk)
                    pct = done * 100 // total if total else -1
                    if pct // 10 != last // 10:
                        progress(f"    {pct}%" if pct >= 0 else f"    {done >> 20} MB")
                        last = pct
            folder.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp) as z:
                for name in z.namelist():
                    if name == "marcadas.json":  # qué ilustraciones ya tienen la marca de Cygames: se suma a la lista
                        import watermark
                        done = watermark.load_list()
                        for k, v in json.loads(z.read(name)).items():
                            done.setdefault(k, v)
                        watermark.save_list(done)
                    elif name in missing or not (folder / name).exists():
                        z.extract(name, folder)
            progress(f"  «{pack['nombre']}» listo")
        except Exception as e:
            progress(f"  no se pudo bajar «{pack['nombre']}»: {e}")
        finally:
            if tmp.exists():
                tmp.unlink()


# ---------- pasos locales ----------
def apply_corrections(progress):
    """traducciones/correcciones.json → {"efectos": {carta: texto}}: arreglos de traducción publicados a mano."""
    path = TRAD / "correcciones.json"
    if not path.exists() or not DB.exists():
        return
    fixes = json.loads(path.read_text(encoding="utf-8")).get("efectos", {})
    con = sqlite3.connect(DB)
    for cid, text in fixes.items():
        con.execute("UPDATE cards SET skill_tr=? WHERE card_id=? AND (skill_es IS NULL OR skill_es='')", (text, int(cid)))
    con.commit()
    con.close()
    if fixes:
        progress(f"  correcciones de traducción aplicadas: {len(fixes)}")


def _step(name, progress, fn, *args):
    progress(name)
    try:
        with contextlib.redirect_stdout(_Lines(progress)):
            return fn(*args)
    except SystemExit:
        progress("  (paso salteado)")
    except Exception as e:
        progress(f"  error: {e}")
    return None


def _cards():
    import fetch_cards
    try:
        fetch_cards.fetch_all()
    except fetch_cards.Maintenance as m:
        print(f"El sitio oficial está en mantenimiento ({m}). Probá más tarde.")
        return False
    return True


def _build():
    """Rearma cards.db; si algo falla, vuelve la base anterior."""
    import build_db, translate_skills, translate_lore
    backup = DB.with_suffix(".db.anterior")
    if DB.exists():
        shutil.copy2(DB, backup)
    try:
        build_db.main()
        translate_skills.main()
        translate_lore.apply()
    except Exception:
        if backup.exists():
            shutil.copy2(backup, DB)
        raise
    finally:
        if backup.exists():
            backup.unlink()


def _voices(progress):
    import voices, auto_voices
    if game_data() is None:
        print("No encontré Shadowverse: Worlds Beyond instalado en Steam: las voces nuevas se suman cuando lo esté.")
        return
    voices.build_cache(progress=lambda s: print(s))
    print(f"Voces asignadas automáticamente: {auto_voices.fill_mapping()} cartas")


def _art():
    import fetch_art, watermark
    fetch_art.main()
    put, had = watermark.process(sorted((ROOT / "images" / "arte").glob("*.png")))
    if put:
        print(f"Marca de agua puesta en {put} ilustraciones nuevas.")


def _console(text):
    """Progreso por consola (sin pasar por print: los pasos redirigen print hacia progress)."""
    out = sys.__stdout__
    if out:
        out.write(text + "\n")
        out.flush()


def run(progress=_console, with_voices=True):
    """Actualiza todo. Devuelve {"version_nueva": str|None, "cartas_antes": n, "cartas_despues": n}."""
    before = _count()
    info = None
    if config.GITHUB_USER:
        progress("Buscando novedades del programa en GitHub...")
        info = remote_info()
        if info is None:
            progress("  no se pudo consultar GitHub (¿sin internet?); sigo con el resto")
        else:
            _step("Traducciones y correcciones publicadas...", progress, sync_files, info, progress)
            _step("Imágenes publicadas...", progress, sync_packs, info, progress)
    ok = _step("Cartas del sitio oficial (puede tardar unos minutos)...", progress, _cards)
    if ok:
        _step("Armando la base de cartas y las traducciones...", progress, _build)
    _step("Correcciones de traducción...", progress, apply_corrections, progress)
    if with_voices:
        _step("Voces (la primera vez tarda bastante)...", progress, _voices, progress)
    _step("Ilustraciones sin marco...", progress, _art)
    after = _count()
    progress(f"Listo: {after} cartas" + (f" ({after - before} nuevas)." if after > before else "."))
    return {"version_nueva": new_version(info), "cartas_antes": before, "cartas_despues": after}


def _count():
    if not DB.exists():
        return 0
    con = sqlite3.connect(DB)
    try:
        return con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def official_count():
    """Cantidad de cartas que muestra hoy el sitio oficial (una consulta rápida), o None sin internet."""
    try:
        import fetch_cards
        cfg = fetch_cards.REGIONS["global"]
        url = f"{cfg['host']}/web/CardList/cardList?offset=0&{fetch_cards.QUERY}"
        req = urllib.request.Request(url, headers={**HEADERS, "lang": cfg["lang"]})
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return data["data"]["count"]
    except Exception:
        return None


def local_count():
    """Cartas de la base que no son fichas (lo que cuenta el sitio oficial)."""
    if not DB.exists():
        return 0
    con = sqlite3.connect(DB)
    try:
        return con.execute("SELECT COUNT(*) FROM cards WHERE is_token=0").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    print(run())
