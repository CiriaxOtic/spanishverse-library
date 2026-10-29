"""Datos de la versión publicada del programa.

GITHUB_USER / GITHUB_REPO: la página de GitHub donde se publica el programa. De ahí cada copia baja, al actualizar,
datos/version.json (versión nueva disponible, revisión de las traducciones, paquetes de imágenes) y las traducciones
y correcciones más nuevas. Si GITHUB_USER está vacío, el programa se actualiza solo desde el sitio oficial y WBGDB.
"""
VERSION = "1.1.1"
GITHUB_USER = "CiriaxOtic"  # el nombre de usuario de GitHub de quien publica el programa
GITHUB_REPO = "spanishverse-library"
BRANCH = "main"
PACKS_TAG = "v1.0.0"  # la versión de GitHub que tiene subidos los paquetes de imágenes (no se resuben en cada versión)


def raw_url(path):
    """Dirección de un archivo del repositorio (la versión más nueva)."""
    return f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{BRANCH}/{path}"


def releases_page():
    return f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
