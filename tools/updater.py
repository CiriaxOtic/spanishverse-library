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
import os
import shutil
import sqlite3
import sys
import time
import urllib.error
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
_ref = {}


def _raw(path):
    """Dirección de un archivo del repositorio en su último cambio. Se pide el número del último cambio a la API de
    GitHub y se baja el archivo de ese cambio exacto: la dirección de siempre («main») queda guardada en caché unos
    minutos después de publicar, y el programa vería la versión anterior."""
    if "sha" not in _ref:
        _ref["sha"] = None
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{config.GITHUB_USER}/{config.GITHUB_REPO}/commits/{config.BRANCH}",
                headers=dict(HEADERS, Accept="application/vnd.github.sha"))
            with urllib.request.urlopen(req, timeout=15) as r:
                sha = r.read().decode("ascii", "ignore").strip()
            if len(sha) == 40 and all(ch in "0123456789abcdef" for ch in sha):
                _ref["sha"] = sha
        except Exception:
            pass  # sin la API (por ejemplo, límite de consultas): la dirección de siempre, pidiendo que no use caché
    if _ref["sha"]:
        return f"https://raw.githubusercontent.com/{config.GITHUB_USER}/{config.GITHUB_REPO}/{_ref['sha']}/{path}"
    return f"{config.raw_url(path)}?t={int(time.time())}"


def remote_info():
    """datos/version.json del repositorio, o None si no hay GitHub configurado o no hay internet."""
    if not config.GITHUB_USER:
        return None
    _ref.clear()  # cada consulta busca el último cambio publicado
    try:
        return json.loads(_get(_raw("datos/version.json"), timeout=20))
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
            data = _get(_raw(path))
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
    progress(f"  traducciones y correcciones: {got} archivo(s) nuevo(s)" if got else
             "  traducciones y correcciones: sin cambios")
    return got


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


def download(url, dest, progress, label="", tries=6):
    """Baja url a dest. Si dest ya existe a medias (un corte de internet, la ventana cerrada), sigue desde donde
    quedó en vez de empezar de cero; si se corta en el medio, reintenta solo. Devuelve True si terminó."""
    for attempt in range(1, tries + 1):
        have = dest.stat().st_size if dest.exists() else 0
        headers = dict(HEADERS, **({"Range": f"bytes={have}-"} if have else {}))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                if have and r.status != 206:  # el servidor no deja retomar: desde cero
                    have = 0
                total = have + int(r.headers.get("Content-Length") or 0)
                if have:
                    progress(f"    retomando desde {have >> 20} MB de {total >> 20} MB")
                with open(dest, "ab" if have else "wb") as out:
                    done, last = have, -1
                    while chunk := r.read(1 << 20):
                        out.write(chunk)
                        done += len(chunk)
                        pct = done * 100 // total if total else -1
                        if pct // 10 != last // 10:
                            progress(f"    {label}{pct}%" if pct >= 0 else f"    {label}{done >> 20} MB")
                            last = pct
            return True
        except urllib.error.HTTPError as e:
            if e.code == 416:  # ya estaba completo
                return True
            progress(f"    error {e.code}; reintento {attempt}/{tries}...")
        except Exception as e:  # corte de internet, tiempo de espera
            progress(f"    se cortó la descarga ({e}); reintento {attempt}/{tries}...")
        time.sleep(min(60, 5 * attempt))
    return False


def _size_mb(text):
    try:
        return float(str(text).split()[0])
    except (ValueError, IndexError):
        return 1000.0


def sync_packs(info, progress):
    """Paquetes de imágenes (zip): se bajan si falta alguno de sus archivos. Lo bajado a medias se retoma."""
    import setup_checks
    todo = []
    for pack in info.get("paquetes") or []:
        folder = ROOT / pack["carpeta"]
        missing = [f for f in pack.get("archivos", []) if not (folder / f).exists()]
        if missing:
            todo.append((pack, folder, missing))
    if not todo:
        return
    # Espacio: el zip y lo descomprimido conviven un momento, y después vienen las voces (~1,5 GB).
    need_gb = max(_size_mb(p.get("tamaño")) for p, _, _ in todo) * 2 / 1024 + \
        sum(_size_mb(p.get("tamaño")) for p, _, _ in todo) / 1024 + 1.5
    free = setup_checks.free_gb(ROOT)
    if free is not None and free < need_gb:
        progress(f"  ¡Falta espacio en el disco! Hay {free:.1f} GB libres y hacen falta unos {need_gb:.1f} GB para las "
                 "imágenes y las voces. Liberá espacio (o mové la carpeta del programa a otro disco) y volvé a "
                 "actualizar. Las imágenes no se bajaron.")
        return
    for pack, folder, missing in todo:
        progress(f"  bajando «{pack['nombre']}» ({len(missing)} imágenes que faltan, {pack.get('tamaño', '?')})...")
        tmp = ROOT / (pack["archivo"] + ".part")
        if not download(pack["url"], tmp, progress):
            progress(f"  no se pudo terminar «{pack['nombre']}»: lo bajado queda guardado y la próxima vez sigue "
                     "desde ahí.")
            continue
        try:
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
            tmp.unlink()
        except zipfile.BadZipFile:
            progress(f"  «{pack['nombre']}» llegó dañado; se vuelve a bajar la próxima vez.")
            tmp.unlink()
        except Exception as e:
            progress(f"  no se pudo descomprimir «{pack['nombre']}»: {e}")


# ---------- versión nueva del programa ----------
INSTALL_DIR = ROOT / "_actualizacion"
# Lo que es del usuario no se pisa al instalar una versión nueva (se conserva tal cual).
KEEP_FILES = ["ajustes.json", "mapping.json", "datos_descargados.json", "errores.log"]
KEEP_DIRS = ["mazos", "images", "voices", "traducciones", "raw", "_actualizacion"]


def prepare_program_update(progress):
    """Baja la versión nueva del programa (.exe empaquetado) y prepara su instalación. Devuelve la ruta del script
    que la instala (hay que correrlo después de cerrar el programa) o None si no hay nada que instalar."""
    import os
    info = remote_info()
    version = new_version(info)
    program = (info or {}).get("programa")
    if not version or not program:
        progress("No hay una versión nueva para instalar.")
        return None
    INSTALL_DIR.mkdir(exist_ok=True)
    progress(f"Bajando la versión {version} ({program.get('tamaño', '?')})...")
    zpath = INSTALL_DIR / "programa.zip"
    if not download(program["url"], zpath, progress):
        progress("No se pudo bajar; lo bajado queda guardado y la próxima vez sigue desde ahí.")
        return None
    # Se descomprime en una carpeta temporal de nombre corto y con el prefijo de rutas largas de Windows: dentro de
    # la carpeta del programa algunas rutas internas pasarían el límite de 260 caracteres.
    import tempfile
    new = Path(tempfile.gettempdir()) / "spanishverse_nuevo"
    long = lambda p: "\\\\?\\" + str(p.resolve())
    if new.exists():
        shutil.rmtree(long(new), ignore_errors=True)
    try:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(long(new))
    except zipfile.BadZipFile:
        zpath.unlink()
        progress("La descarga llegó dañada; probá de nuevo.")
        return None
    except OSError as e:
        progress(f"No se pudo descomprimir la versión nueva ({e}). Liberá espacio en el disco y probá de nuevo.")
        return None
    src = next((p.parent for p in new.rglob("Spanishverse Library.exe")), None)
    if src is None:
        progress("La descarga no tiene el programa; probá de nuevo más tarde.")
        return None
    q = lambda s: str(s).replace("'", "''")
    exe = ROOT / "Spanishverse Library.exe"
    script = INSTALL_DIR.parent / "_instalar_version_nueva.ps1"
    script.write_text(
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"Write-Host 'Instalando Spanishverse Library {version}... (esta ventana se cierra sola)'\n"
        f"Wait-Process -Id {os.getpid()} -Timeout 120\n"
        "Start-Sleep -Seconds 1\n"
        f"robocopy '{q(src)}' '{q(ROOT)}' /E /R:10 /W:2 /XF {' '.join(KEEP_FILES)} "
        f"/XD {' '.join(KEEP_DIRS)} /NFL /NDL /NJH /NJS /NP | Out-Null\n"
        f"Start-Process -FilePath '{q(exe)}' -ArgumentList '--actualizar' -WorkingDirectory '{q(ROOT)}'\n"
        "Start-Sleep -Seconds 3\n"
        f"Remove-Item -Recurse -Force '{q(INSTALL_DIR)}'\n"
        f"Remove-Item -Recurse -Force -LiteralPath '\\\\?\\{q(new.resolve())}'\n"
        "Remove-Item -Force $PSCommandPath\n",
        encoding="utf-8-sig")
    progress(f"Versión {version} lista para instalar.")
    import paths
    paths.save_setting("instalacion_intentada", version)  # ver install_blocked()
    return script


def install_blocked(version):
    """¿Ya se intentó instalar sola esta versión y el programa sigue siendo el viejo? Entonces la instalación
    automática no funciona en esta PC (antivirus, permisos): no se reintenta en un ciclo sin fin."""
    import paths
    tried = paths.load_settings().get("instalacion_intentada")
    return tried == version and _version_tuple(version) > _version_tuple(config.VERSION)


def program_update(info):
    """Versión nueva del programa que se puede instalar sola (solo el .exe empaquetado), o None."""
    import paths
    version = new_version(info)
    if paths.FROZEN and version and (info or {}).get("programa") and not install_blocked(version):
        return version
    return None


def run_program_update(script):
    """Corre el script de instalación en su propia ventana (el programa tiene que cerrarse enseguida)."""
    import subprocess
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0), cwd=str(ROOT.parent))


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


WEEK = 7 * 24 * 3600  # cada cuánto se revisa entera la lista de cartas aunque no haya nuevas (cambios de balance)


def game_signature():
    """«Huella» de la carpeta de audios del juego (cantidad de archivos, tamaño total, último cambio): si no cambió
    desde la última vez, las voces ya están al día y no hace falta revisar los miles de paquetes."""
    root = game_data()
    if root is None:
        return None
    n = size = newest = 0
    for dp, _, files in os.walk(root):
        for fn in files:
            try:
                st = os.stat(os.path.join(dp, fn))
            except OSError:
                continue
            n, size, newest = n + 1, size + st.st_size, max(newest, int(st.st_mtime))
    return f"{n}:{size}:{newest}"


def _voices(progress, cards_changed):
    import voices, auto_voices
    if game_data() is None:
        print("No encontré Shadowverse: Worlds Beyond en las bibliotecas de Steam: sin el juego, todo funciona igual "
              "pero sin voces. Si lo tenés instalado en otro lugar, indicalo con «🎮 Carpeta del juego…» (en la "
              "pantalla de inicio o en el asistente de voces 🎙) y volvé a actualizar.")
        return
    state = _state()
    sig = game_signature()
    if voices.INDEX_JSON.exists() and "voces_firma" not in state:
        # Ya tenía las voces preparadas (de una versión anterior del programa): se toman como al día en vez de
        # repasar todo de nuevo. Si el juego se actualiza después, la huella cambia y se suman las nuevas.
        state["voces_firma"] = sig
        _save_state(state)
    if voices.INDEX_JSON.exists() and state.get("voces_firma") == sig:
        if cards_changed:
            print(f"El juego no cambió; voces asignadas a las cartas nuevas: {auto_voices.fill_mapping()}")
        else:
            print("Sin cambios (el juego no se actualizó desde la última vez).")
        return
    voices.build_cache(progress=lambda s: print(s))
    print(f"Voces asignadas automáticamente: {auto_voices.fill_mapping()} cartas")
    state = _state()
    state["voces_firma"] = sig
    _save_state(state)


def _art(fetch):
    import fetch_art, watermark
    if fetch:  # WBGDB solo se consulta si hay cartas nuevas (o en la revisión semanal)
        fetch_art.main()
    put, had = watermark.process(sorted((ROOT / "images" / "arte").glob("*.png")))
    if put:
        print(f"Marca de agua puesta en {put} ilustraciones nuevas.")
    elif not fetch:
        print("Sin cambios.")


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
    files_changed = 0
    if config.GITHUB_USER:
        progress("Buscando novedades del programa en GitHub...")
        info = remote_info()
        if info is None:
            progress("  no se pudo consultar GitHub (¿sin internet?); sigo con el resto")
        else:
            files_changed = _step("Traducciones y correcciones publicadas...", progress, sync_files, info, progress)
            _step("Imágenes publicadas...", progress, sync_packs, info, progress)
    # Solo se hace lo que cambió: el programa anota en datos_descargados.json en qué estado quedó cada cosa.
    state = _state()
    progress("Cartas del sitio oficial...")
    official, local = official_count(), local_count()
    fresh = time.time() - state.get("cartas_revision", 0) < WEEK
    if "cartas_revision" not in state and DB.exists() and official == local:
        fresh = True  # ya estaba todo (por ejemplo, de una versión anterior del programa): se toma como revisado
        state["cartas_revision"] = time.time()
    cards_changed = False
    if official is None:
        progress("  no se pudo consultar el sitio oficial (sin internet o en mantenimiento); queda lo que hay")
    elif DB.exists() and official == local and fresh:
        progress(f"  sin cartas nuevas ({local} cartas)")
    else:
        why = ("primera descarga" if not DB.exists() else f"{official - local} cartas nuevas" if official > local
               else "revisión semanal de cambios en las cartas")
        if _step(f"  bajando la lista completa ({why}; puede tardar unos minutos)...", progress, _cards):
            _step("Armando la base de cartas y las traducciones...", progress, _build)
            cards_changed = True
            state = _state()
            state["cartas_revision"] = time.time()
    # Versión nueva del programa (puede traer arreglos del traductor) o traducciones nuevas: se rehacen las
    # traducciones sobre la base que ya está (unos segundos), sin volver a bajar las cartas.
    version_changed = state.get("programa_version") != config.VERSION
    if not cards_changed and DB.exists() and (version_changed or files_changed):
        import translate_lore, translate_skills
        if version_changed and (ROOT / "raw" / "global").exists():
            _step("Rearmando las traducciones con la versión nueva del programa...", progress, _build)
        else:
            _step("Aplicando las traducciones nuevas...", progress, translate_lore.apply)
    state["programa_version"] = config.VERSION
    _save_state(state)
    _step("Correcciones de traducción...", progress, apply_corrections, progress)
    if with_voices:
        _step("Voces...", progress, _voices, progress, cards_changed)
    _step("Ilustraciones sin marco...", progress, _art, cards_changed)
    after = _count()
    progress(f"Listo: {after} cartas" + (f" ({after - before} nuevas)." if after > before else "."))
    return {"version_nueva": new_version(info), "cartas_antes": before, "cartas_despues": after,
            "programa": (info or {}).get("programa")}


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


def pending():
    """Qué falta o qué hay de nuevo, para la pantalla de inicio: (lista de motivos, hay_internet).
    Sin motivos = está todo al día. Sin internet solo se ven los faltantes locales (base, imágenes, voces)."""
    reasons, online = [], False
    info = remote_info()
    if info is not None:
        online = True
        version = program_update(info)
        if version:
            reasons.append(f"Versión nueva del programa: {version}")
        state = _state()
        if any(state.get(p) != d or not (ROOT / p).exists() for p, d in (info.get("archivos") or {}).items()):
            reasons.append("Traducciones y correcciones nuevas")
        missing = sum(1 for pack in info.get("paquetes") or [] for f in pack.get("archivos", [])
                      if not (ROOT / pack["carpeta"] / f).exists())
        if missing:
            reasons.append(f"Imágenes de cartas e ilustraciones: faltan {missing}")
    official = official_count()
    if official is not None:
        online = True
        local = local_count()
        if official > local:
            reasons.append(f"Cartas nuevas: {official - local}" if local else "La base de cartas")
    if not DB.exists() and "La base de cartas" not in reasons:
        reasons.append("La base de cartas")
    if not any((ROOT / "images" / d).glob("*.png") for d in ("eng", "es419")) and not any("Imágenes" in r for r in reasons):
        reasons.append("Imágenes de las cartas")
    try:
        import voices
        if game_data() is not None and not voices.INDEX_JSON.exists():
            reasons.append("Voces del juego (se preparan desde Shadowverse instalado en Steam)")
    except Exception:
        pass
    return reasons, online


def usable_offline():
    """¿Se puede usar el programa sin internet? (ya tiene la base de cartas y las imágenes)."""
    return DB.exists() and any((ROOT / "images" / d).glob("*.png") for d in ("eng", "es419"))
