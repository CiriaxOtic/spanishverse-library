"""Publicar una versión nueva con un solo comando (solo lo usa quien mantiene el programa).

    py -3.13 tools/publicar.py            revisa todo y arma el .exe y los zips (no sube nada)
    py -3.13 tools/publicar.py --subir    además crea la versión en GitHub y sube el repositorio

Antes de armar revisa que: todo el código compile, la versión de tools/config.py sea más nueva que la publicada,
tools/novedades.py tenga sus novedades y exista publicar/notas_v<versión>.md. Después agrega a las notas el SHA256
del zip y el enlace de VirusTotal, para que cualquiera pueda comprobar que el archivo es el original."""
import hashlib
import json
import py_compile
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from paths import ROOT  # noqa: E402

OUT = ROOT / "publicar"
NOTES = OUT / f"notas_v{config.VERSION}.md"
ZIP = OUT / "release" / f"SpanishverseLibrary-{config.VERSION}.zip"
REPO_DIR = OUT / "repositorio"
SLUG = f"{config.GITHUB_USER}/{config.GITHUB_REPO}"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def checks():
    problems = []
    for f in [ROOT / "Spanishverse Library.pyw", *sorted((ROOT / "tools").glob("*.py"))]:
        try:
            py_compile.compile(str(f), doraise=True, cfile=str(OUT / "pyinstaller" / "check.pyc"))
        except py_compile.PyCompileError as e:
            problems.append(f"No compila {f.name}: {e.msg}")
    try:
        with urllib.request.urlopen(config.raw_url("datos/version.json"), timeout=30) as r:
            published = json.loads(r.read().decode("utf-8"))["app"]
        if version_tuple(config.VERSION) <= version_tuple(published):
            problems.append(f"La versión {config.VERSION} no es más nueva que la publicada ({published}): "
                            "subila en tools/config.py")
    except Exception as e:  # sin internet: se avisa pero no se frena
        print(f"Aviso: no se pudo ver la versión publicada ({e})")
    from novedades import NOVEDADES
    if NOVEDADES[0][0] != config.VERSION:
        problems.append(f"tools/novedades.py no tiene las novedades de {config.VERSION} (va primera en la lista)")
    if not NOTES.exists():
        problems.append(f"Falta {NOTES.relative_to(ROOT)} (las notas de la versión)")
    import pendientes
    effects, _ = pendientes.main()
    if effects:
        print(f"Aviso: {effects} efectos sin traducir (ver work/pendientes.txt)")
    return problems


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def add_checksum():
    digest = sha256(ZIP)
    text = NOTES.read_text(encoding="utf-8").split("\n## Comprobar el archivo")[0].rstrip()
    text += (f"\n\n## Comprobar el archivo\n\nSHA256 de `{ZIP.name}`:\n\n`{digest}`\n\n"
             f"Análisis de VirusTotal: https://www.virustotal.com/gui/file/{digest}\n")
    NOTES.write_text(text, encoding="utf-8")
    print(f"SHA256 {digest} (agregado a {NOTES.name})")
    return digest


def run(cmd, cwd=None):
    print(">", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True, creationflags=NO_WINDOW)


def upload():
    """Primero la versión en GitHub (con el zip) y después el repositorio: así, cuando las copias del programa ven
    la versión nueva en datos/version.json, el zip ya se puede bajar."""
    tag = f"v{config.VERSION}"
    run(["gh", "release", "create", tag, str(ZIP), "-R", SLUG, "-t", f"Spanishverse Library {config.VERSION}",
         "-F", str(NOTES), "--latest"])
    run(["git", "add", "-A"], cwd=REPO_DIR)
    run(["git", "commit", "-m", f"Versión {config.VERSION}"], cwd=REPO_DIR)
    run(["git", "push"], cwd=REPO_DIR)


def main():
    problems = checks()
    if problems:
        print("\nNo se puede publicar todavía:\n" + "\n".join("• " + p for p in problems))
        sys.exit(1)
    run([sys.executable, str(ROOT / "tools" / "build_release.py"), "--paquetes-existentes"])
    add_checksum()
    if "--subir" in sys.argv:
        upload()
        print(f"Publicada la versión {config.VERSION}: {config.releases_page()}")
    else:
        print("Todo listo. Para subirlo: py -3.13 tools/publicar.py --subir")


if __name__ == "__main__":
    main()
