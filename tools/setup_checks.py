"""Controles para que instalar y usar el programa sea fácil: avisan de los errores comunes antes de que causen
problemas (abrirlo sin descomprimir, carpeta sin permiso de escritura, carpeta dentro de OneDrive, poco espacio) y
crean el acceso directo del escritorio."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def running_from_zip(root):
    """¿Se abrió el programa desde adentro del .zip? Windows (y WinRAR/7-Zip) lo copian a una carpeta temporal."""
    low = str(root).lower()
    temp = os.environ.get("TEMP", "").lower()
    in_temp = (temp and low.startswith(temp)) or "\\appdata\\local\\temp\\" in low
    return bool(in_temp and any(m in low for m in ("temp1_", ".zip", "rar$", "\\7z")))


def writable(root):
    """¿Se puede escribir en la carpeta del programa? (en «Archivos de programa» Windows no deja)."""
    test = Path(root) / ".prueba_escritura"
    try:
        test.write_bytes(b"ok")
        test.unlink()
        return True
    except OSError:
        return False


def in_onedrive(root):
    """¿La carpeta está dentro de OneDrive? (los 3 GB de imágenes se subirían a la nube)."""
    low = str(Path(root).resolve()).lower()
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(var)
        if base and low.startswith(base.lower().rstrip("\\") + "\\"):
            return True
    return "\\onedrive" in low


def free_gb(root):
    try:
        return shutil.disk_usage(root).free / 2 ** 30
    except OSError:
        return None


def desktop_dir():
    """Escritorio del usuario (puede estar movido a OneDrive o tener otro nombre según el idioma)."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout.strip()
        if out and Path(out).is_dir():
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def create_shortcut(target, name="Spanishverse Library", icon=None):
    """Acceso directo en el escritorio. Devuelve la ruta o None si no se pudo."""
    lnk = desktop_dir() / f"{name}.lnk"
    q = lambda s: str(s).replace("'", "''")
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
              f"$s.TargetPath='{q(target)}';$s.WorkingDirectory='{q(Path(target).parent)}';"
              + (f"$s.IconLocation='{q(icon)}';" if icon else "") + "$s.Save()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return lnk if lnk.exists() else None


def program_path():
    """El .exe (empaquetado) o el .pyw que se está usando."""
    return Path(sys.executable) if getattr(sys, "frozen", False) else Path(sys.argv[0]).resolve()
