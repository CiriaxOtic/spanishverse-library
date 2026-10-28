"""Crea los punteros del visor de imágenes (Windows no trae lupa ni mano agarrando para tkinter):
tools/cursores/lupa.cur (lupa con "+") y tools/cursores/agarrar.cur (mano cerrada, al arrastrar).

Uso por consola: py -3.13 tools/make_cursors.py
"""
import struct
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "cursores"
SIZE = 32
SCALE = 4  # se dibuja grande y se achica, para que los bordes queden suaves


def write_cur(img, path, hotspot):
    """Guarda una imagen RGBA de 32x32 como cursor de Windows (.cur, con transparencia)."""
    img = img.convert("RGBA")
    w, h = img.size
    pixels = b"".join(bytes((b, g, r, a)) for r, g, b, a in
                      (img.getpixel((x, y)) for y in range(h - 1, -1, -1) for x in range(w)))
    and_mask = b"\x00" * (((w + 31) // 32) * 4 * h)
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(pixels) + len(and_mask), 0, 0, 0, 0)
    data = header + pixels + and_mask
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, hotspot[0], hotspot[1], len(data), 6 + 16)
    path.write_bytes(struct.pack("<HHH", 0, 2, 1) + entry + data)


def magnifier():
    s = SIZE * SCALE
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = SCALE
    # mango (abajo a la derecha), con borde negro
    d.line((19 * k, 19 * k, 29 * k, 29 * k), fill=(0, 0, 0, 255), width=6 * k)
    d.line((19 * k, 19 * k, 29 * k, 29 * k), fill=(255, 255, 255, 255), width=3 * k)
    # aro
    d.ellipse((2 * k, 2 * k, 22 * k, 22 * k), fill=(0, 0, 0, 255))
    d.ellipse((4 * k, 4 * k, 20 * k, 20 * k), fill=(255, 255, 255, 255))
    d.ellipse((6 * k, 6 * k, 18 * k, 18 * k), fill=(40, 40, 48, 235))
    # "+"
    d.rectangle((11 * k, 8 * k, 13 * k - 1, 16 * k - 1), fill=(255, 255, 255, 255))
    d.rectangle((8 * k, 11 * k, 16 * k - 1, 13 * k - 1), fill=(255, 255, 255, 255))
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def grabbing_hand():
    s = SIZE * SCALE
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = SCALE
    black, white = (0, 0, 0, 255), (255, 255, 255, 255)
    # palma y dedos doblados (vista de arriba de una mano cerrada)
    for fill, grow in ((black, 1.5), (white, 0)):
        g = grow * k
        d.rounded_rectangle((7 * k - g, 12 * k - g, 26 * k + g, 28 * k + g), radius=6 * k, fill=fill)
        for i in range(4):  # nudillos
            x = 8 * k + i * 4.5 * k
            d.ellipse((x - g, 8 * k - g, x + 5 * k + g, 15 * k + g), fill=fill)
        d.ellipse((3 * k - g, 15 * k - g, 10 * k + g, 22 * k + g), fill=fill)  # pulgar
    for i in range(1, 4):  # separación entre dedos
        x = 8 * k + i * 4.5 * k
        d.line((x, 10 * k, x, 15 * k), fill=(90, 90, 90, 255), width=k)
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    write_cur(magnifier(), OUT / "lupa.cur", (12, 12))
    write_cur(grabbing_hand(), OUT / "agarrar.cur", (16, 18))
    print("Punteros creados en", OUT)


if __name__ == "__main__":
    main()
