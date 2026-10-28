"""Marca de agua "© Cygames, Inc." abajo a la derecha de las ilustraciones sin marco (images/arte), con el mismo
estilo que las ilustraciones oficiales: letras blancas con un brillo oscuro suave alrededor.

Muchas ilustraciones ya traen la marca (las oficiales y muchas de WBGDB, en tres estilos: blanca con brillo, gris con
borde oscuro y blanca con borde negro, abajo a la derecha o a la izquierda). Esas no se tocan: se buscan comparando la
franja de abajo con los recortes de tools/marca_ref/. images/arte/marcadas.json guarda qué se hizo con cada
ilustración ("puesta" o "ya traía"), así nunca se marca dos veces la misma.

Uso por consola:
    py -3.13 tools/watermark.py               revisa todas las de images/arte que no estén en la lista
    py -3.13 tools/watermark.py <archivo.png> ...
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT  # noqa: E402
ARTE = ROOT / "images" / "arte"
LISTA = ARTE / "marcadas.json"
REFS = ROOT / "tools" / "marca_ref"
TEXT = "© Cygames, Inc."
# Century Gothic (viene con Office) tiene la misma forma de letra que la marca oficial; si no está, Arial.
FONT = next((f for f in (r"C:\Windows\Fonts\GOTHIC.TTF", r"C:\Windows\Fonts\arial.ttf") if Path(f).exists()),
            "arial.ttf")
WIDTH = 0.226   # ancho del texto / ancho de la imagen (medido en las ilustraciones oficiales)
MARGIN = 0.014  # margen derecho e inferior / ancho de la imagen
FOUND = 0.30    # correlación desde la que se considera que la imagen ya trae la marca (revisado a ojo)


# ---------- poner la marca ----------
def stamp(im):
    """Devuelve una copia de im con la marca abajo a la derecha."""
    im = im.convert("RGBA")
    W, H = im.size
    size = 10
    font = ImageFont.truetype(FONT, size)
    while font.getlength(TEXT) < W * WIDTH:
        size += 1
        font = ImageFont.truetype(FONT, size)
    l, t, r, b = font.getbbox(TEXT)
    x = W - int(W * MARGIN) - r
    y = H - int(W * MARGIN) - b
    # Brillo oscuro: el texto en negro, difuminado, debajo del texto blanco.
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((x, y), TEXT, font=font, fill=(0, 0, 0, 200),
                              stroke_width=max(1, size // 10), stroke_fill=(0, 0, 0, 200))
    glow = glow.filter(ImageFilter.GaussianBlur(max(1.5, size / 6)))
    out = Image.alpha_composite(im, glow)
    ImageDraw.Draw(out).text((x, y), TEXT, font=font, fill=(255, 255, 255, 235))
    return out


# ---------- buscar una marca que ya esté ----------
def _ncc(img, tpl):
    """Correlación normalizada de tpl en cada posición de img (por FFT)."""
    H, W = img.shape
    h, w = tpl.shape
    t = tpl - tpl.mean()
    tn = np.sqrt((t ** 2).sum())
    shape = (H + h, W + w)
    num = np.fft.irfft2(np.fft.rfft2(img, s=shape) * np.fft.rfft2(t[::-1, ::-1], s=shape), s=shape)[h - 1:H, w - 1:W]
    c1 = np.cumsum(np.cumsum(np.pad(img, ((1, 0), (1, 0))), 0), 1)
    c2 = np.cumsum(np.cumsum(np.pad(img ** 2, ((1, 0), (1, 0))), 0), 1)
    s = c1[h:, w:] - c1[:-h, w:] - c1[h:, :-w] + c1[:-h, :-w]
    s2 = c2[h:, w:] - c2[:-h, w:] - c2[h:, :-w] + c2[:-h, :-w]
    var = s2 - s ** 2 / (h * w)
    r = num / (np.sqrt(np.maximum(var, 1e-6)) * tn + 1e-6)
    r[var / (h * w) < 16] = 0  # zonas lisas: ahí no hay letras
    return r


def _highpass(im, radius):
    """La imagen menos su versión borrosa: quedan los bordes de las letras y se va el fondo."""
    a = np.asarray(im, dtype=np.float32)
    return a - np.asarray(im.filter(ImageFilter.BoxBlur(radius)), dtype=np.float32)


def mark_score(im):
    """Qué tanto se parece la franja de abajo de im a alguna de las marcas de referencia (0 a 1)."""
    im = im.convert("L")
    W, H = im.size
    strip = im.crop((0, int(H * 0.80), W, H))
    best = 0.0
    for ref in sorted(REFS.glob("*.png")):
        tpl = Image.open(ref)
        for rel in np.linspace(0.12, 0.42, 21):  # ancho de la marca relativo al ancho de la imagen
            tw = int(W * rel)
            th = max(8, int(tw * tpl.size[1] / tpl.size[0]))
            if th >= strip.size[1]:
                continue
            r = max(2, th // 3)
            best = max(best, float(_ncc(_highpass(strip, r), _highpass(tpl.resize((tw, th), Image.LANCZOS), r)).max()))
    return best


# ---------- lista y archivos ----------
def load_list():
    return json.loads(LISTA.read_text(encoding="utf-8")) if LISTA.exists() else {}


def save_list(done):
    LISTA.write_text(json.dumps(dict(sorted(done.items())), indent=0, ensure_ascii=False), encoding="utf-8")


def swap_entries(a, b):
    """Cuando fetch_art da vuelta una normal y su evolucionada, lo anotado de cada archivo también se da vuelta."""
    done = load_list()
    va, vb = done.pop(a, None), done.pop(b, None)
    if vb is not None:
        done[a] = vb
    if va is not None:
        done[b] = va
    save_list(done)


def process(paths, progress=None):
    """Marca los archivos que todavía no estén en la lista (salvo los que ya traen la marca)."""
    done = load_list()
    put = had = 0
    todo = [Path(p) for p in paths if Path(p).name not in done]
    for i, p in enumerate(todo, 1):
        im = Image.open(p)
        if mark_score(im) >= FOUND:
            done[p.name] = "ya traía"
            had += 1
        else:
            out = stamp(im)
            (out if im.mode == "RGBA" else out.convert("RGB")).save(p)
            done[p.name] = "puesta"
            put += 1
        if progress and i % 50 == 0:
            progress(f"  {i}/{len(todo)}")
            save_list(done)
    save_list(done)
    return put, had


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(ARTE.glob("*.png"))
    put, had = process(files, progress=print)
    print(f"Marca de agua: puesta en {put} ilustraciones; {had} ya la traían.")
