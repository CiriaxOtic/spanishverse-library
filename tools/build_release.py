"""Arma todo lo que se publica en GitHub (solo lo usa quien publica el programa).

    py -3.13 tools/build_release.py            .exe + zips + carpeta del repositorio
    py -3.13 tools/build_release.py --sin-exe  solo zips y repositorio (el .exe ya armado)
    py -3.13 tools/build_release.py --paquetes-existentes   sin rehacer los zips de imágenes (ya subidos a
                                                            la versión config.PACKS_TAG de GitHub)

Deja en publicar/:
- release/SpanishverseLibrary-<versión>.zip   el programa listo (el .exe, la base de cartas, traducciones, voces
  asociadas). Es lo que la gente descarga.
- release/imagenes-cartas.zip, release/ilustraciones-1.zip, release/ilustraciones-2.zip   imágenes que el programa
  baja solo la primera vez (se suben como archivos de la versión en GitHub: «Releases»).
- repositorio/   lo que va en el repositorio de GitHub: el código, datos/version.json (lo que consulta cada copia del
  programa al actualizar), las traducciones y las voces asociadas, el README y el manual.

Nunca incluye datos personales: mazos/, ajustes.json, work/, raw/, voices/cache (cada usuario arma sus voces desde
su propio juego).
"""
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from paths import ROOT  # noqa: E402

OUT = ROOT / "publicar"
DIST = OUT / "dist" / "Spanishverse Library"
REL = OUT / "release"
REPO = OUT / "repositorio"
TAG = f"v{config.VERSION}"
APP_NAME = "Spanishverse Library"
RESOURCES = ["spanishverse.ico", "cursores", "marca_ref", "vgmstream"]  # tools/ que el .exe usa como archivos
DATA_FILES = ["traducciones/lore.json", "traducciones/correcciones.json", "voices/mapping.json"]
TOOLS_PY = sorted(p.name for p in (ROOT / "tools").glob("*.py"))
DOCS = ["README.md", "LICENCIA.txt", "docs/Manual de Spanishverse Library.pdf"]


def sha1(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def build_exe():
    work = OUT / "pyinstaller"
    hidden = [f"--hidden-import={p[:-3]}" for p in TOOLS_PY]
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", APP_NAME,
           "--icon", str(ROOT / "tools" / "spanishverse.ico"), "--paths", str(ROOT / "tools"),
           "--collect-data", "soundcard", "--distpath", str(OUT / "dist"), "--workpath", str(work),
           "--specpath", str(work), *hidden, str(ROOT / f"{APP_NAME}.pyw")]
    print("PyInstaller...", flush=True)
    subprocess.run(cmd, check=True)


def assemble():
    """Completa la carpeta del .exe con los archivos que el programa usa (sin datos personales)."""
    tools = DIST / "tools"
    tools.mkdir(exist_ok=True)
    for name in RESOURCES:
        src = ROOT / "tools" / name
        dst = tools / name
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
    shutil.copy2(ROOT / "cards.db", DIST / "cards.db")
    for rel in ["defaults/voces.json", "defaults/traducciones.json"] + DATA_FILES:
        if (ROOT / rel).exists():
            (DIST / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, DIST / rel)
    for rel in DOCS:
        if (ROOT / rel).exists():
            shutil.copy2(ROOT / rel, DIST / Path(rel).name)
    for d in ["mazos", "images/eng", "images/es419", "images/arte", "voices/recorded"]:
        (DIST / d).mkdir(parents=True, exist_ok=True)


def zip_dir(zpath, base, files, inner=lambda p: p):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:  # PNG ya comprimido: guardar sin recomprimir
        for f in files:
            z.write(base / f, inner(f))


def make_packs():
    """Zips de imágenes y su descripción para datos/version.json."""
    REL.mkdir(parents=True, exist_ok=True)
    packs = []
    images = ROOT / "images"
    cards = sorted(f"{d}/{p.name}" for d in ("eng", "es419") for p in (images / d).glob("*.png"))
    art = sorted(p.name for p in (images / "arte").glob("*.png"))
    half = len(art) // 2
    plan = [("imagenes-cartas.zip", "Imágenes de las cartas", "images", cards),
            ("ilustraciones-1.zip", "Ilustraciones sin marco (1 de 2)", "images/arte", art[:half] + ["marcadas.json"]),
            ("ilustraciones-2.zip", "Ilustraciones sin marco (2 de 2)", "images/arte", art[half:] + ["marcadas.json"])]
    for archivo, nombre, carpeta, files in plan:
        z = REL / archivo
        print(f"{archivo}: {len(files)} archivos...", flush=True)
        zip_dir(z, ROOT / carpeta, files)
        size = z.stat().st_size
        packs.append({"nombre": nombre, "archivo": archivo, "carpeta": carpeta,
                      "url": f"https://github.com/{config.GITHUB_USER}/{config.GITHUB_REPO}/releases/download/{config.PACKS_TAG}/{archivo}",
                      "tamaño": f"{size / 2 ** 20:.0f} MB",
                      "archivos": [f for f in files if f != "marcadas.json"]})
    return packs


def make_repo(packs):
    if REPO.exists():  # se rehace todo menos el historial de git
        for p in REPO.iterdir():
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    (REPO / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / f"{APP_NAME}.pyw", REPO / f"{APP_NAME}.pyw")
    for name in TOOLS_PY:
        shutil.copy2(ROOT / "tools" / name, REPO / "tools" / name)
    for name in RESOURCES:
        src = ROOT / "tools" / name
        shutil.copytree(src, REPO / "tools" / name) if src.is_dir() else shutil.copy2(src, REPO / "tools" / name)
    for rel in DATA_FILES + ["defaults/voces.json", "defaults/traducciones.json"] + DOCS:
        if (ROOT / rel).exists():
            (REPO / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, REPO / rel)
    shutil.copy2(ROOT / "Actualizar cartas.bat", REPO / "Actualizar cartas.bat")
    # Los archivos se suben tal cual: el programa comprueba que lleguen idénticos (sha1 en datos/version.json).
    (REPO / ".gitattributes").write_text("* -text\n", encoding="utf-8")
    (REPO / ".gitignore").write_text("cards.db\nimages/\nvoices/cache/\nvoices/index*\nvoices/profiles.npy\n"
                                     "mazos/\najustes.json\nraw/\nwork/\npublicar/\n__pycache__/\n"
                                     "datos_descargados.json\n", encoding="utf-8")
    info = {"app": config.VERSION, "descarga": config.releases_page(),
            "archivos": {rel: sha1(ROOT / rel) for rel in DATA_FILES if (ROOT / rel).exists()},
            "paquetes": packs}
    (REPO / "datos").mkdir(exist_ok=True)
    (REPO / "datos" / "version.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")


def zip_program():
    REL.mkdir(parents=True, exist_ok=True)
    z = REL / f"SpanishverseLibrary-{config.VERSION}.zip"
    files = sorted(p.relative_to(DIST) for p in DIST.rglob("*") if p.is_file())
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            zf.write(DIST / f, Path(APP_NAME) / f)
        for d in ["mazos", "images/eng", "images/es419", "images/arte", "voices/recorded"]:
            zf.writestr(f"{APP_NAME}/{d}/", "")
    print(f"{z.name}: {z.stat().st_size / 2 ** 20:.0f} MB", flush=True)


if __name__ == "__main__":
    if not config.GITHUB_USER:
        print("Aviso: falta GITHUB_USER en tools/config.py (los enlaces de descarga quedan incompletos).")
    if "--sin-exe" not in sys.argv:
        build_exe()
    assemble()
    if "--paquetes-existentes" in sys.argv:  # los zips de imágenes ya están en GitHub: solo se rehace la lista
        packs = json.loads((REPO / "datos" / "version.json").read_text(encoding="utf-8"))["paquetes"]
        for p in packs:
            p["url"] = (f"https://github.com/{config.GITHUB_USER}/{config.GITHUB_REPO}/releases/download/"
                        f"{config.PACKS_TAG}/{p['archivo']}")
    else:
        packs = make_packs()
    make_repo(packs)
    zip_program()
    print("Listo: todo en", OUT)
