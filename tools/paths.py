"""Dónde están las cosas del programa y del juego, en cualquier PC.

- ROOT: la carpeta del programa (la del .exe cuando está empaquetado con PyInstaller, o la de
  «Spanishverse Library.pyw» cuando se corre con Python). Ahí van cards.db, images/, voices/, mazos/, etc.
- game_data(): la carpeta de audios de Shadowverse: Worlds Beyond (…/ShadowverseWB_Data/Persistent/dat), buscada
  en todas las bibliotecas de Steam. Si el usuario eligió otra a mano, se guarda en ajustes.json ("carpeta_juego").
"""
import json
import re
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "ajustes.json"
GAME_SUBDIR = Path("steamapps") / "common" / "ShadowverseWB" / "ShadowverseWB_Data" / "Persistent" / "dat"


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_setting(key, value):
    data = load_settings()
    data[key] = value
    SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _steam_libraries():
    """Carpetas de las bibliotecas de Steam (la principal, según el registro de Windows, y las de libraryfolders.vdf)."""
    roots = []
    try:
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(Path(winreg.QueryValueEx(k, value)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    roots.append(Path(r"C:\Program Files (x86)\Steam"))
    libs = []
    for r in roots:
        libs.append(r)
        vdf = r / "steamapps" / "libraryfolders.vdf"
        try:
            for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                libs.append(Path(p.replace("\\\\", "\\")))
        except OSError:
            pass
    seen, out = set(), []
    for lib in libs:
        key = str(lib).lower()
        if key not in seen:
            seen.add(key)
            out.append(lib)
    return out


def find_game_in(folder):
    """Carpeta de audios (…/Persistent/dat) dentro de una carpeta elegida a mano, o None. Sirve elegir la propia
    carpeta «dat», la del juego («ShadowverseWB»), «ShadowverseWB_Data», la biblioteca de Steam o «steamapps»."""
    folder = Path(folder)
    rest = GAME_SUBDIR.parts  # steamapps / common / ShadowverseWB / ShadowverseWB_Data / Persistent / dat
    for i in range(len(rest) + 1):
        p = folder.joinpath(*rest[i:])
        try:
            if p.name == "dat" and p.is_dir() and any(p.iterdir()):
                return p
        except OSError:  # carpeta sin permiso de lectura
            return None
    return None


def game_data():
    """Carpeta de audios del juego, o None si no está instalado (o no se encontró)."""
    chosen = load_settings().get("carpeta_juego")
    if chosen and (found := find_game_in(chosen)):
        return found
    for lib in _steam_libraries():
        p = lib / GAME_SUBDIR
        if p.is_dir():
            return p
    return None
