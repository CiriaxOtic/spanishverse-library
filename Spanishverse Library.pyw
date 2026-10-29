"""Spanishverse Library: biblioteca de cartas de Shadowverse: Worlds Beyond (programa de escritorio).

Lee cards.db y la carpeta images/ que arman tools/fetch_cards.py y tools/build_db.py.
Abrir con doble clic (usa pythonw, sin consola).
"""
import queue
import re
import sqlite3
import sys
import threading
import json
import tkinter as tk
import tkinter.font as tkfont
import unicodedata
import webbrowser
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
from paths import ROOT  # noqa: E402  (la carpeta del programa, también empaquetado como .exe)
DB = ROOT / "cards.db"
IMAGES = ROOT / "images"
ICON = ROOT / "tools" / "spanishverse.ico"
CURSORS = ROOT / "tools" / "cursores"  # lupa.cur y agarrar.cur (tools/make_cursors.py)
ART = IMAGES / "arte"  # ilustraciones sin marco (tools/fetch_art.py): <número>.png, la evolucionada es número + 1


def cursor(name, fallback):
    """Puntero propio (.cur) para tkinter; si no está el archivo, uno de los de siempre."""
    path = CURSORS / f"{name}.cur"
    return ("@" + path.as_posix(),) if path.exists() else fallback
import random_creators  # noqa: E402  (detecta efectos que crean cartas al azar)
import card_generation  # noqa: E402  (clasifica efectos que traen, crean, invocan o copian cartas)
import decks  # noqa: E402  (armador de mazos: reglas, viales, códigos del juego, mazos guardados)
try:  # voces de las cartas (necesita numpy; si falta, el programa funciona igual sin bocina)
    import voices  # noqa: E402
except ImportError:
    voices = None

BG, PANEL, INK, MUTED, LINE = "#15141a", "#1f1e26", "#ecebf0", "#a09fab", "#34323e"
FIELD = "#2a2833"
ACCENT, KW, KW_BG, LINK ="#a48cf0", "#f3c565", "#3a2f17", "#8fb4ff"
FONT = ("Segoe UI", 10)
SETTINGS = ROOT / "ajustes.json"  # preferencias del usuario (por ahora, el tamaño de letra)
# Tamaños de letra que se pueden elegir: de 100 % a 135 %, más grande sin desarmar las pantallas.
FONT_SCALES = [round(1 + 0.05 * i, 2) for i in range(8)]
_fonts = {}  # (familia, tamaño, estilo) -> fuente con nombre; todas cambian juntas con set_font_scale
_font_scale = [1.0]


def F(family, size, *style):
    """Fuente de tkinter para (familia, tamaño en puntos, "bold"/"italic"), ya agrandada según el tamaño de
    letra elegido. Es una fuente con nombre: al cambiar la escala, cambia en todos los lugares donde se usa."""
    key = (family, size, style)
    if key not in _fonts:
        _fonts[key] = tkfont.Font(family=family, size=_scaled(size), weight="bold" if "bold" in style else "normal",
                                  slant="italic" if "italic" in style else "roman")
    return _fonts[key]


def _scaled(size):
    return size if size <= 1 else int(size * _font_scale[0] + 0.5)  # (la línea de 1 punto queda igual)


_tk_fonts = {}  # fuentes propias de tkinter (títulos de columnas, listas desplegables...) -> su tamaño original


def set_font_scale(scale):
    _font_scale[0] = scale
    for (family, size, style), font in _fonts.items():
        font.configure(size=_scaled(size))
    for name in ("TkDefaultFont", "TkHeadingFont", "TkTextFont", "TkMenuFont", "TkTooltipFont", "TkFixedFont"):
        font = tkfont.nametofont(name)
        size = _tk_fonts.setdefault(name, font.cget("size"))
        font.configure(size=(1 if size > 0 else -1) * _scaled(abs(size)))


def scale_columns(tree):
    """Anchos de las columnas de una lista según el tamaño de letra (los de 100 % se guardan la primera vez)."""
    if not hasattr(tree, "base_widths"):
        tree.base_widths = {c: (tree.column(c, "width"), tree.column(c, "minwidth")) for c in ("#0", *tree["columns"])}
    for c, (width, minwidth) in tree.base_widths.items():
        tree.column(c, width=round(width * _font_scale[0]), minwidth=round(minwidth * _font_scale[0]))


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**changes):
    try:
        SETTINGS.write_text(json.dumps({**load_settings(), **changes}, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass

MARKUP = re.compile(r"(<color=Keyword>|</color>|</?b>|</?i>|<hr>|<[^>]+>)")


class Data:
    def __init__(self, path):
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        self.lookup = {}
        for table in ("classes", "types", "rarities", "sets", "tribes", "keywords"):
            self.lookup[table] = {r["id"]: (r["en"], r["es"]) for r in con.execute(f"SELECT * FROM {table}")}
        self.cards = {r["card_id"]: dict(r) for r in con.execute("SELECT * FROM cards ORDER BY class_id, cost, card_id")}
        for c in self.cards.values():
            c.update(tribes=[], related=[], related_by=[], qa=[], specific=[])
        for r in con.execute("SELECT * FROM card_tribes"):
            self.cards[r["card_id"]]["tribes"].append(r["tribe_id"])
        # Efectos especiales (blasón, cristalizar, acelerar, fe), como los muestra el sitio oficial.
        effects = {}
        for r in con.execute("SELECT * FROM specific_effects"):
            e = effects.setdefault(r["effect_id"], {"key": r["effect_key"], "cost": r["cost"]})
            e[r["lang"]] = r["skill_text"]
            if r["lang"] == "en" and "skill_tr" in r.keys():
                e["tr"] = r["skill_tr"]  # traducción propia (tools/translate_skills.py)
        for r in con.execute("SELECT * FROM relations"):
            if r["card_id"] not in self.cards:
                continue
            if r["kind"] == "specific_effect":
                if r["related_id"] in effects:
                    self.cards[r["card_id"]]["specific"].append(effects[r["related_id"]])
            elif r["related_id"] in self.cards:
                self.cards[r["card_id"]]["related"].append(r["related_id"])
                self.cards[r["related_id"]]["related_by"].append(r["card_id"])
        for r in con.execute("SELECT * FROM qa ORDER BY card_id, lang, idx"):
            self.cards[r["card_id"]]["qa"].append((r["lang"], r["question"], r["answer"]))
        try:
            self.glossary = [dict(r) for r in con.execute("SELECT * FROM glossary ORDER BY idx")]
        except sqlite3.OperationalError:  # base armada antes de que existiera el glosario
            self.glossary = []
        self.gloss_by_en = {e["title_en"].lower(): e for e in self.glossary}
        con.close()

        strip = lambda s: re.sub(r"<[^>]+>", "", s or "").lower()
        for c in self.cards.values():
            c["related"] = sorted(set(c["related"]))
            c["related_by"] = sorted(set(c["related_by"]) - set(c["related"]))
            texts = [c["name_en"], c["name_es"], c["skill_en"], c["skill_es"], c.get("skill_tr")]
            texts += [e.get(lang) for e in c["specific"] for lang in ("en", "es", "tr")]
            c["haystack"] = " | ".join(strip(t) for t in texts)
        self.by_name_en = {c["name_en"].lower(): c for c in self.cards.values()}
        self.kw_es = {en.lower(): es for en, es in self.lookup["keywords"].values() if en and es}
        self.kw_es.update({en.lower(): es for en, es in self.lookup["tribes"].values() if en and es and en != "-"})
        self.kw_es.update({en.lower(): es for en, es in self.lookup["types"].values() if "(" not in en})
        # Que buscar el término en español encuentre también las cartas que solo están en inglés.
        for c in self.cards.values():
            extra = [es.lower() for en, es in self.kw_es.items() if en in c["haystack"]]
            c["haystack"] += " | " + " ".join(extra)

        # Palabras clave de cada carta (en inglés, en minúsculas), para el filtro "Palabra clave".
        self.by_name_es = {c["name_es"].lower(): c for c in self.cards.values() if c["name_es"]}
        self.kw_en_by_es = {es.lower(): en for en, es in self.kw_es.items()}
        self.tribe_ids = {en.lower(): k for k, (en, es) in self.lookup["tribes"].items() if en and en != "-"}
        self.type_ids = {en.lower(): k for k, (en, es) in self.lookup["types"].items() if "(" not in en}
        used = set()
        for c in self.cards.values():
            source = (c["skill_en"] or "") + "".join(e.get("en") or "" for e in c["specific"])
            words = {strip(w).strip() for w in re.findall(r"<color=Keyword>(.*?)</color>", source)}
            c["kw"] = {w for w in words if w in self.kw_es}
            used |= c["kw"]
        self.keyword_options = sorted(
            ((self.kw_es[en.lower()], en.lower()) for en, es in self.lookup["keywords"].values()
             if en and en.lower() in used and en.lower() in self.kw_es),
            key=lambda kv: kv[0].lower())

        # Para "Ver creadoras" / "Ver lo que trae": qué cartas crea cada una de verdad (no toda la lista de
        # relacionadas de la página, que es encadenada) y qué efectos traen cartas al azar o del cementerio.
        self.made_by = {}
        for c in self.cards.values():
            c["creates"] = self._direct_creations(c)
            for rid in c["creates"]:
                self.made_by.setdefault(rid, set()).add(c["card_id"])
        self.random_pools = {}
        names_en = set(self.by_name_en)
        not_random = set(load_corrections().get("no_crea_al_azar", []))
        for c in self.cards.values():
            text = (c["skill_en"] or "") + "\n" + "\n".join(e.get("en") or "" for e in c["specific"])
            pools = random_creators.random_pools(text, self.tribe_ids)
            if pools and c["card_id"] not in not_random:
                self.random_pools[c["card_id"]] = pools
            # Filtro "Trae o crea cartas": pares (desde dónde, cómo) del efecto y del blasón.
            c["gen"] = card_generation.classify(text, names_en)

    CREATE_VERB = re.compile(r"\b(summons?|adds?|transforms?|puts?|shuffles?|cop(?:y|ies)|replaces?|invokes?)\b")

    def _direct_creations(self, c):
        """Cartas relacionadas que esta carta crea de verdad, según su propio efecto:
        - la nombra después de una acción que crea (invocar, agregar, transformar en, poner en el mazo, copias de...);
        - "reemplaza tu mazo por" un mazo especial: crea las cartas de ese mazo (sus relacionadas);
        - "ganás N sellos de tierra": si no hay un amuleto con Sello de Tierra se invoca un Magic Sediment."""
        strip = lambda s: re.sub(r"<[^>]+>", "", s or "").lower()
        text = strip(c["skill_en"]) + "\n" + "\n".join(strip(e.get("en")) for e in c["specific"])
        sentences = re.split(r"(?<=[.!])\s+|\n", text)
        creates = set()
        # También la propia carta: algunas se crean a sí mismas aunque la página no lo liste.
        for rid in set(c["related"]) | {c["card_id"]}:
            name = self.cards[rid]["name_en"].lower()
            for s in sentences:
                pos = s.find(name)
                if pos >= 0 and any(m.start() < pos for m in self.CREATE_VERB.finditer(s)):
                    creates.add(rid)
                    break
        # Tablas tipo "1: Carta A / 2: Carta B" presentadas por un renglón con "transform/summon/add":
        # cada carta de la tabla es un posible resultado del efecto.
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if not re.match(r"^\s*-?\s*\d+(\s*or more)?\s*:", line):
                continue
            j = i - 1
            while j >= 0 and re.match(r"^\s*-?\s*\d+(\s*or more)?\s*:", lines[j]):
                j -= 1
            if j >= 0 and self.CREATE_VERB.search(lines[j]):
                creates |= {rid for rid in c["related"] if self.cards[rid]["name_en"].lower() in line}
        if re.search(r"\breplace your deck with\b", text):
            creates |= set(c["related"]) - {c["card_id"]}
        if re.search(r"\bgain \w+ earth sigils?\b", text):
            creates |= {rid for rid in c["related"] if self.cards[rid]["name_en"] == "Magic Sediment"}
        return creates

    def creators_of(self, card_id):
        """(seguras, posibles): cartas que nombran a esta carta, y cartas cuyo efecto aleatorio podría crearla."""
        target = self.cards[card_id]
        sure = set(self.made_by.get(card_id, ()))  # incluye a la propia carta si se crea a sí misma
        possible = {}  # {creadora: "mazo" | "cementerio" | "nueva"}
        for cid, pools in self.random_pools.items():
            if cid in sure:
                continue  # (una carta sí puede traerse a sí misma, ej. Reanimar una copia suya destruida)
            srcs = [p.get("src", "mazo") for p in pools if random_creators.fits(target, p, self.cards[cid]["class_id"])]
            if srcs:
                possible[cid] = srcs[0]
        return sure, possible

    def creations_of(self, card_id):
        """(nombradas, posibles): lo que esta carta puede traer. Nombradas = cartas que su efecto menciona;
        posibles = todas las cartas que cumplen las condiciones de sus efectos al azar o de cementerio,
        de su clase o neutrales (incluida ella misma si cumple)."""
        card = self.cards[card_id]
        sure = set(card["creates"])  # solo lo que su efecto crea (incluida ella misma si se crea a sí misma)
        possible = {}
        for pool in self.random_pools.get(card_id, ()):
            for target in self.cards.values():
                tid = target["card_id"]
                if tid not in sure and tid not in possible and random_creators.fits(target, pool, card["class_id"]):
                    possible[tid] = pool.get("src", "mazo")
        return sure, possible

    def effect_title(self, key):
        """Título de un efecto especial con el nombre de su palabra clave en español."""
        en = {"crest": "Crest", "crystal": "Crystallize", "accelerate": "Accelerate", "faith": "Faith"}.get(key, "")
        es = next((s for e, s in self.lookup["keywords"].values() if e == en and s), en or "Efecto especial")
        return es.upper()

    GLOSS_ALIASES = {"on spellboost": "spellboost"}  # palabra clave -> concepto del glosario que la explica

    def definition(self, en_key):
        """Significado de una palabra clave según el glosario: (título, texto), o None si no está."""
        e = self.gloss_by_en.get(self.GLOSS_ALIASES.get(en_key, en_key))
        if not e:
            return None
        title = e["title_es"] or self.kw_es.get(e["title_en"].lower()) or e["title_en"]
        return title, re.sub(r"\s*\n\s*", " ", (e["text_es"] or e["text_en"]).strip())

    def label(self, table, key):
        en, es = self.lookup[table].get(key, ("—", None))
        return es or en


class TriCheck(tk.Frame):
    """Casilla de tres estados: 0 vacía (no filtra), 1 visto (solo eso), 2 cruz (todo menos eso)."""
    MARKS = {0: ("☐", MUTED), 1: ("☑", "#5cc98a"), 2: ("☒", "#e06c6c")}

    def __init__(self, parent, text, command, bg=BG, states=3):
        """states=2: casilla común (vacía / visto), sin la cruz de "todo menos esto"."""
        super().__init__(parent, bg=bg, cursor="hand2")
        self.states = states
        self.var = tk.IntVar(value=0)
        self.box = tk.Label(self, bg=bg, font=F("Segoe UI Symbol", 11), width=2, cursor="hand2")
        self.box.pack(side="left")
        self.label = tk.Label(self, text=text, bg=bg, fg=INK, font=F(*FONT), cursor="hand2")
        self.label.pack(side="left")
        self.command = command
        for w in (self, self.box, self.label):
            w.bind("<Button-1>", self._cycle)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _cycle(self, _=None):
        self.var.set((self.var.get() + 1) % self.states)
        self.command()

    def _draw(self):
        mark, color = self.MARKS[self.var.get()]
        self.box.config(text=mark, fg=color)


class Flow(tk.Frame):
    """Contenedor que acomoda sus elementos de izquierda a derecha y pasa al renglón siguiente
    cuando no entran, así los filtros se ven completos con cualquier ancho de ventana."""

    def __init__(self, parent, padx=8, pady=8):
        super().__init__(parent, bg=BG, height=1)
        self.units, self.padx, self.pady = [], padx, pady
        self.bind("<Configure>", lambda e: self._layout(e.width))

    def add(self, widget):
        self.units.append(widget)

    def _rows(self, width):
        rows, row, x = [], [], 0
        for widget in self.units:
            w = widget.winfo_reqwidth()
            if row and x + w > width:
                rows.append(row)
                row, x = [], 0
            row.append(widget)
            x += w + self.padx
        if row:
            rows.append(row)
        return rows

    def height_for(self, width):
        """Alto que ocuparían los recuadros con este ancho (aunque estén ocultos)."""
        rows = self._rows(width)
        return sum(max(w.winfo_reqheight() for w in row) for row in rows) + self.pady * max(0, len(rows) - 1)

    def _layout(self, width):
        # Ubica cada recuadro con el alto del más alto de su renglón.
        y = 0
        for row in self._rows(width):
            row_h = max(widget.winfo_reqheight() for widget in row)
            x = 0
            for widget in row:
                widget.place(x=x, y=y, height=row_h)
                x += widget.winfo_reqwidth() + self.padx
            y += row_h + self.pady
        height = max(1, y - self.pady)
        if int(self.cget("height")) != height:
            self.configure(height=height)


class Switch(tk.Frame):
    """Interruptor de dos posiciones: "texto_off ⬤━ texto_on". Un clic (en el interruptor o en un texto)
    lo cambia; var guarda texto_off o texto_on."""

    def __init__(self, parent, off, on, command, bg=BG):
        super().__init__(parent, bg=bg)
        self.off, self.on, self.command = off, on, command
        self.var = tk.StringVar(value=off)
        self.left = tk.Label(self, text=off, bg=bg, font=F(*FONT), cursor="hand2")
        self.canvas = tk.Canvas(self, width=40, height=20, bg=bg, highlightthickness=0, cursor="hand2")
        self.right = tk.Label(self, text=on, bg=bg, font=F(*FONT), cursor="hand2")
        self.left.pack(side="left")
        self.canvas.pack(side="left", padx=6)
        self.right.pack(side="left")
        self.left.bind("<Button-1>", lambda _: self.set(off))
        self.right.bind("<Button-1>", lambda _: self.set(on))
        self.canvas.bind("<Button-1>", lambda _: self.set(on if self.var.get() == off else off))
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def set(self, value):
        if self.var.get() != value:
            self.var.set(value)
            self.command()

    def _draw(self):
        is_on = self.var.get() == self.on
        c = self.canvas
        c.delete("all")
        track = ACCENT if is_on else FIELD
        c.create_oval(1, 1, 19, 19, fill=track, outline=LINE)
        c.create_oval(21, 1, 39, 19, fill=track, outline=LINE)
        c.create_rectangle(10, 1, 30, 19, fill=track, outline="")
        c.create_line(10, 1, 30, 1, fill=LINE)
        c.create_line(10, 19, 30, 19, fill=LINE)
        x = 22 if is_on else 3
        c.create_oval(x, 3, x + 15, 17, fill="#ffffff" if is_on else MUTED, outline="")
        self.left.config(fg=MUTED if is_on else INK)
        self.right.config(fg=INK if is_on else MUTED)


class SizeSlider(tk.Frame):
    """Tamaño de letra: "A ━━●━━ A" (la A chica y la grande no cambian de tamaño). Se hace clic o se arrastra
    sobre la barra; cada marca es uno de los tamaños de FONT_SCALES. command() al cambiar de marca;
    on_release() al soltar."""

    W, H, PAD = 104, 20, 8

    def __init__(self, parent, var, command, on_release, bg=BG):
        super().__init__(parent, bg=bg)
        self.var, self.command, self.on_release = var, command, on_release
        tk.Label(self, text="A", bg=bg, fg=MUTED, font=("Segoe UI", 8)).pack(side="left", anchor="s")
        self.canvas = tk.Canvas(self, width=self.W, height=self.H, bg=bg, highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="left", padx=6)
        tk.Label(self, text="A", bg=bg, fg=MUTED, font=("Segoe UI", 13)).pack(side="left", anchor="s")
        self.canvas.bind("<Button-1>", self._pick)
        self.canvas.bind("<B1-Motion>", self._pick)
        self.canvas.bind("<ButtonRelease-1>", lambda _: self.on_release())
        var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _x(self, i):
        return self.PAD + i * (self.W - 2 * self.PAD) / (len(FONT_SCALES) - 1)

    def _pick(self, event):
        i = min(range(len(FONT_SCALES)), key=lambda k: abs(self._x(k) - event.x))
        if FONT_SCALES[i] != self.var.get():
            self.var.set(FONT_SCALES[i])
            self.command()

    def _draw(self):
        c, y = self.canvas, self.H / 2
        i = FONT_SCALES.index(self.var.get())
        c.delete("all")
        c.create_line(self._x(0), y, self._x(len(FONT_SCALES) - 1), y, fill=FIELD, width=4, capstyle="round")
        c.create_line(self._x(0), y, self._x(i), y, fill=ACCENT, width=4, capstyle="round")
        for k in range(len(FONT_SCALES)):
            x = self._x(k)
            c.create_oval(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill=INK if k <= i else MUTED, outline="")
        x = self._x(i)
        c.create_oval(x - 7, y - 7, x + 7, y + 7, fill="#ffffff", outline=ACCENT, width=2)


# Por debajo de esta coincidencia, lo grabado no está entre los audios del juego (los aciertos dan 0,77 o más).
LOW_MATCH = 0.72


class VoiceAssistant(tk.Toplevel):
    """Asistente para asociar la voz de una carta: graba lo que suena en la PC mientras el usuario reproduce
    las líneas en el juego, y lo reconoce entre las voces del juego ya convertidas (voices/)."""
    SR = 48000

    def __init__(self, app, card_id):
        super().__init__(app)
        self.app, self.card_id = app, card_id
        self.recs = {"normal": None, "evo": None}
        self.recording, self.chunks, self.result = None, [], None
        self.check_frame = self.alt_frame = None
        card = app.data.cards[card_id]
        self.title("Asociar voz")
        self.configure(bg=PANEL, padx=16, pady=14)
        self.transient(app)
        self.resizable(False, False)
        tk.Label(self, text=f"Asociar voz: {card['name_en']}", bg=PANEL, fg=INK,
                 font=F("Segoe UI Semibold", 12)).pack(anchor="w")
        steps = ("1. En el juego: voz en japonés, y música y efectos en 0 (dejá solo las voces).\n"
                 "2. Abrí esta carta en la biblioteca de cartas del juego.\n"
                 "3. Apretá «Grabar normal», reproducí en el juego TODAS sus líneas normales en orden,\n"
                 "    y apretá «Detener».\n"
                 "4. Si tiene versión evolucionada: «Grabar evolucionada», sus líneas, y «Detener».\n"
                 "5. Apretá «Identificar» y, si el resultado está bien, «Guardar».\n"
                 "    (O «Usar mis grabaciones» para guardar tal cual lo que grabaste.)")
        tk.Label(self, text=steps, bg=PANEL, fg=MUTED, font=F(*FONT), justify="left").pack(anchor="w", pady=(8, 10))
        row = tk.Frame(self, bg=PANEL)
        row.pack(anchor="w")
        self.btn_normal = ttk.Button(row, text="● Grabar normal", command=lambda: self.toggle("normal"))
        self.btn_evo = ttk.Button(row, text="● Grabar evolucionada", command=lambda: self.toggle("evo"))
        self.btn_id = ttk.Button(row, text="Identificar", command=self.identify)
        # Alternativa a «Identificar»: usar directamente lo grabado (se habilita al grabar las normales).
        self.btn_own = ttk.Button(row, text="Usar mis grabaciones", command=self.use_own, state="disabled")
        self.btn_save = ttk.Button(row, text="Guardar", command=self.save, state="disabled")
        for b in (self.btn_normal, self.btn_evo, self.btn_id, self.btn_own, self.btn_save):
            b.pack(side="left", padx=(0, 6))
        self.status = tk.Label(self, text="", bg=PANEL, fg=INK, font=F(*FONT), justify="left", wraplength=560)
        self.status.pack(anchor="w", pady=(10, 0))
        bottom = tk.Frame(self, bg=PANEL)
        bottom.pack(fill="x", pady=(12, 0))
        entry = app.voice_map.get(card_id) or {}
        if entry.get("normal") or entry.get("evo"):
            ttk.Button(bottom, text="Quitar la voz asociada", command=self.remove).pack(side="left", padx=(0, 6))
        # «Por defecto»: vuelve la voz de esta carta (solo esta) a la original, por si se cambió por error.
        try:
            self.default = voices.default_voice(card_id)
        except Exception:
            self.default = None
        changed = self._as_text(app.voice_map.get(card_id)) != self._as_text(self.default)
        ttk.Button(bottom, text="Por defecto", command=self.restore_default,
                   state="normal" if changed else "disabled").pack(side="left")
        ttk.Button(bottom, text="Cerrar", command=self.close).pack(side="right")
        # Si el juego no está en una biblioteca de Steam que el programa encuentre solo, acá se indica dónde está.
        ttk.Button(bottom, text="🎮 Carpeta del juego…", command=lambda: choose_game_folder(self)).pack(
            side="right", padx=(0, 6))
        self.protocol("WM_DELETE_WINDOW", self.close)

    # --- grabación del audio de la PC ---
    def toggle(self, phase):
        if self.recording == phase:
            self.recording = None  # el hilo termina y guarda la grabación
            return
        if self.recording:
            return
        self.recording, self.chunks = phase, []
        btn = self.btn_normal if phase == "normal" else self.btn_evo
        btn.config(text="■ Detener")
        self.status.config(text="Grabando… reproducí las líneas en el juego y después apretá «Detener».", fg=KW)
        threading.Thread(target=self._record, args=(phase,), daemon=True).start()

    def _record(self, phase):
        import ctypes
        import warnings
        import numpy as np
        import soundcard as sc
        warnings.filterwarnings("ignore")
        error = None
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0)
            speaker = sc.default_speaker()
            mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
            with mic.recorder(samplerate=self.SR) as rec:
                while self.recording == phase:
                    chunk = rec.record(numframes=self.SR // 10)
                    self.chunks.append(chunk.mean(axis=1) if chunk.ndim > 1 else chunk)
            self.recs[phase] = np.concatenate(self.chunks) if self.chunks else None
        except Exception as e:  # sin salida de audio, etc.
            error = str(e)
        self.after(0, lambda: self._recorded(phase, error))

    def _recorded(self, phase, error):
        btn = self.btn_normal if phase == "normal" else self.btn_evo
        btn.config(text="● Grabar normal" if phase == "normal" else "● Grabar evolucionada")
        if error:
            self.status.config(text=f"No se pudo grabar el audio de la PC: {error}", fg="#e06c6c")
            return
        secs = 0 if self.recs[phase] is None else len(self.recs[phase]) / self.SR
        self.btn_own.config(state="normal" if self.recs["normal"] is not None else "disabled")
        self.status.config(text=f"Grabación {'normal' if phase == 'normal' else 'evolucionada'} lista ({secs:.0f} s).", fg=INK)

    # --- reconocimiento ---
    def identify(self, force_bank=None):
        if not voices.INDEX_JSON.exists():
            self.status.config(text="Las voces del juego todavía se están preparando. Probá de nuevo en un rato.",
                               fg="#e06c6c")
            return
        if self.recs["normal"] is None:
            self.status.config(text="Primero grabá las líneas normales.", fg="#e06c6c")
            return
        self.status.config(text="Identificando…", fg=INK)
        self.update_idletasks()
        if getattr(self.app, "voice_index", None) is None:
            self.app.voice_index = voices.Index()
        r = self.app.voice_index.identify({k: v for k, v in self.recs.items() if v is not None}, self.SR,
                                          force_bank=force_bank)
        if r is not None:
            if force_bank:  # al elegir otro candidato, los demás empatados siguen a mano para comparar
                prev = self.result or {}
                r["alternatives"] = [b for b in [prev.get("bank")] + prev.get("alternatives", [])
                                     if b and b != force_bank]
        self._save_debug(r)
        if not r or not r["normal"]:
            self.status.config(text="No reconocí ninguna línea. Revisá que la música y los efectos del juego estén "
                                    "en 0 y volvé a grabar.\nSi esta carta solo hace ruidos, puede que sus sonidos "
                                    "no estén como archivo en el juego: en ese caso usá «Usar mis grabaciones».",
                               fg="#e06c6c")
            return
        # Todo el paquete es del mismo personaje: las líneas que no se escucharon se agregan igual al final
        # de "Normal", marcadas, para que el usuario solo tenga que ubicarlas (◀, ⇄) o quitar alguna (✕).
        heard = {s for s in r["normal"] + r["evo"] if not isinstance(s, list)}  # del paquete principal
        r["auto"] = [ln["stream"] for ln in self.app.voice_index.lines_of(r["bank"]) if ln["stream"] not in heard]
        heard = r["normal"] + r["evo"]
        r["normal"].extend(r["auto"])
        self.result = r
        found = len(heard)
        msg = (f"Reconocida en la grabación: {len(r['normal']) - len(r['auto'])} línea(s) normal(es) y "
               f"{len(r['evo'])} de evolucionada (el personaje tiene {r['total_lines']} en total). "
               f"Coincidencia: {r['confidence']:.0%}.")
        low = r["confidence"] < LOW_MATCH
        if low:
            # Típico de criaturas y máquinas cuyos sonidos el juego arma mezclando varios efectos: no existen
            # como un archivo de audio, así que no hay nada con qué compararlos.
            msg = (f"⚠ No encontré estos sonidos entre los audios del juego (coincidencia: {r['confidence']:.0%}). "
                   "El resultado de abajo probablemente está mal: escuchalo con ▶.\n"
                   "Si no coincide, apretá «Usar mis grabaciones»: guarda lo que grabaste como la voz de esta "
                   "carta, cortado en cada sonido.")
        elif r["auto"]:
            msg += (f"\nSe agregaron automáticamente {len(r['auto'])} línea(s) del personaje que no se escucharon "
                    "(resaltadas en amarillo, al final de Normal). Ubicalas con ◀ y ⇄, o quitá con ✕ la que sobre.")
        if low:
            r["alternatives"] = []  # con una coincidencia tan baja, los "casi empatados" tampoco son confiables
        elif r.get("ties", 0) > 3 and not force_bank:
            # Sonidos genéricos compartidos por muchas cartas: mostrar una lista larga no ayuda.
            r["alternatives"] = []
            msg += ("\n⚠ Este personaje usa sonidos que comparten muchas cartas (típico de máquinas y criaturas), "
                    "así que con lo grabado no se puede saber cuál es. Grabá también la EVOLUCIONADA "
                    "(«● Grabar evolucionada») y volvé a identificar: sus sonidos suelen ser únicos.")
            self.status.config(fg=KW)
        elif r.get("alternatives"):
            msg += ("\nOjo: hay otro personaje con sonidos casi idénticos (típico de criaturas y máquinas). "
                    "Escuchá los candidatos de abajo y elegí con «Usar este», o grabá también la evolucionada "
                    "para desempatar.")
        self.status.config(text=msg, fg=KW if low else INK)
        self.btn_save.config(state="normal")
        self._show_check_buttons(r)
        self._show_alternatives(r)

    def use_own(self):
        """Guarda las grabaciones del usuario (cortadas en cada sonido) como las líneas de la carta."""
        if self.recs["normal"] is None:
            self.status.config(text="Primero grabá las líneas normales.", fg="#e06c6c")
            return
        own = voices.save_recording_lines(self.card_id, self.recs, self.SR)
        if not own["normal"]:
            self.status.config(text="No encontré sonidos en la grabación. Volvé a grabar.", fg="#e06c6c")
            return
        r = {"bank": None, "normal": own["normal"], "evo": own["evo"], "auto": [], "alternatives": []}
        self.result = r
        self.status.config(text=f"Se usarán tus grabaciones: {len(r['normal'])} sonido(s) normal(es) y "
                                f"{len(r['evo'])} de evolucionada (●). Escuchalos, ordenalos si hace falta "
                                "y apretá «Guardar».", fg=INK)
        self.btn_save.config(state="normal")
        self._show_check_buttons(r)
        self._show_alternatives(r)

    def _show_alternatives(self, r):
        """Candidatos casi empatados: ▶ escucha sus sonidos de a uno, «Usar este» rehace el resultado con él."""
        if getattr(self, "alt_frame", None) is not None:
            self.alt_frame.destroy()
            self.alt_frame = None
        if not r.get("alternatives"):
            return
        self.alt_frame = tk.Frame(self, bg=PANEL)
        self.alt_frame.pack(anchor="w", pady=(10, 0), after=self.check_frame)
        tk.Label(self.alt_frame, text="Otros personajes con sonidos casi idénticos:", bg=PANEL, fg=MUTED,
                 font=F(*FONT)).pack(anchor="w")
        for i, bank in enumerate(r["alternatives"], 1):
            lines = self.app.voice_index.lines_of(bank)
            row = tk.Frame(self.alt_frame, bg=FIELD, padx=6, pady=3)
            row.pack(anchor="w", pady=2)
            tk.Label(row, text=f"Candidato {i} ({len(lines)} sonidos)", bg=FIELD, fg=INK, font=F(*FONT)).pack(side="left", padx=(0, 8))
            pos = {"i": 0}
            btn = ttk.Button(row, text=f"▶ 0/{len(lines)}", width=9)

            def play_next(ls=lines, p=pos, b=btn):
                if ls:
                    i = p["i"] % len(ls)
                    p["i"] = i + 1
                    voices.play(voices.CACHE / ls[i]["wav"])
                    b.config(text=f"▶ {i + 1}/{len(ls)}")
            btn.config(command=play_next)
            btn.pack(side="left")
            ttk.Button(row, text="Usar este", command=lambda b=bank: self.identify(force_bank=b)).pack(side="left", padx=(6, 0))

    def _save_debug(self, r):
        """Guarda la última grabación y el análisis en voices/debug/, para revisar problemas de reconocimiento."""
        try:
            import json
            debug = voices.VOICES / "debug"
            debug.mkdir(parents=True, exist_ok=True)
            for phase, x in self.recs.items():
                path = debug / f"ultima_{phase}.wav"
                if x is not None:
                    voices.write_wav(path, voices.resample(x, self.SR, voices.SR), voices.SR)
                elif path.exists():
                    path.unlink()  # que no quede la grabación de un intento anterior mezclada con este
            info = dict(getattr(self.app.voice_index, "last_debug", {}) or {})
            info["card_id"] = self.card_id
            info["card"] = self.app.data.cards[self.card_id]["name_en"]
            info["result"] = r
            (debug / "ultimo_analisis.json").write_text(json.dumps(info, indent=1, default=str), encoding="utf-8")
        except Exception:
            pass  # el diagnóstico nunca debe impedir usar el asistente

    def _show_check_buttons(self, r):
        """Editor del resultado: ▶ para escuchar cada línea en el orden detectado, ◀ para moverla antes,
        ✕ para quitarla, y las demás líneas del personaje con "+ Normal" / "+ Evolucionada" por si faltan."""
        if getattr(self, "check_frame", None) is not None:
            self.check_frame.destroy()
        self.check_frame = tk.Frame(self, bg=PANEL)
        self.check_frame.pack(anchor="w", pady=(8, 0), after=self.status)

        def play(item):
            path = voices.line_path(item, r["bank"])  # puede ser de otro paquete o una grabación propia
            voices.play(path)

        def edit(action, phase, sid):
            lst = r[phase]
            if action == "remove":
                lst.remove(sid)
            elif action == "left":
                i = lst.index(sid)
                lst[i - 1], lst[i] = lst[i], lst[i - 1]
            elif action == "add":
                lst.append(sid)
            elif action == "swap":  # pasa la línea de Normal a Evolucionada o al revés (al final de la otra lista)
                lst.remove(sid)
                r["evo" if phase == "normal" else "normal"].append(sid)
            self.btn_save.config(state="normal" if r["normal"] else "disabled")
            self._show_check_buttons(r)

        small = {"width": 3}
        for phase, label in (("normal", "Normal"), ("evo", "Evolucionada")):
            row = tk.Frame(self.check_frame, bg=PANEL)
            row.pack(anchor="w", pady=3)
            tk.Label(row, text=f"{label} ({len(r[phase])}):", bg=PANEL, fg=MUTED, font=F(*FONT), width=16,
                     anchor="w").grid(row=0, column=0, sticky="nw")
            for i, sid in enumerate(r[phase]):
                # Las líneas agregadas automáticamente (no se escucharon) se resaltan para revisarlas.
                # (en celeste, las que vienen de otro paquete: líneas compartidas con otra carta o con un líder)
                bg = KW if sid in r.get("auto", ()) else (LINK if isinstance(sid, list) else FIELD)
                cell = tk.Frame(row, bg=bg, padx=3, pady=2)
                cell.grid(row=i // 4, column=1 + i % 4, padx=(0, 6), pady=2, sticky="w")
                mark = "●" if isinstance(sid, str) else "▶"  # ● = grabación propia
                ttk.Button(cell, text=f"{mark} {i + 1}", width=5, command=lambda s=sid: play(s)).pack(side="left")
                if i > 0:
                    ttk.Button(cell, text="◀", command=lambda p=phase, s=sid: edit("left", p, s), **small).pack(side="left")
                ttk.Button(cell, text="⇄", command=lambda p=phase, s=sid: edit("swap", p, s), **small).pack(side="left")
                ttk.Button(cell, text="✕", command=lambda p=phase, s=sid: edit("remove", p, s), **small).pack(side="left")
        others = [] if r["bank"] is None else [ln["stream"] for ln in self.app.voice_index.lines_of(r["bank"])
                  if ln["stream"] not in r["normal"] and ln["stream"] not in r["evo"]]
        if others:
            row = tk.Frame(self.check_frame, bg=PANEL)
            row.pack(anchor="w", pady=(8, 0))
            tk.Label(row, text="Otras líneas de este personaje (agregalas si faltan):", bg=PANEL, fg=MUTED,
                     font=F(*FONT)).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 3))
            for i, sid in enumerate(others):
                cell = tk.Frame(row, bg=FIELD, padx=3, pady=2)
                cell.grid(row=1 + i // 3, column=i % 3, padx=(0, 6), pady=2, sticky="w")
                ttk.Button(cell, text="▶", command=lambda s=sid: play(s), **small).pack(side="left")
                ttk.Button(cell, text="+ Normal", command=lambda s=sid: edit("add", "normal", s)).pack(side="left", padx=(2, 0))
                ttk.Button(cell, text="+ Evolucionada", command=lambda s=sid: edit("add", "evo", s)).pack(side="left", padx=(2, 0))

    def save(self):
        r = self.result
        self.app.voice_map[self.card_id] = {"bank": r["bank"], "normal": r["normal"], "evo": r["evo"]}
        voices.save_mapping(self.app.voice_map)
        self.app.voice_pos.pop((self.card_id, False), None)
        self.app.voice_pos.pop((self.card_id, True), None)
        self.app._update_voice_button()
        self.close()

    def remove(self):
        # Queda guardada como "sin voz" (y no se borra del mapeo): así «Actualizar cartas» no se la vuelve a
        # poner sola; solo «Por defecto» la recupera.
        self.app.voice_map[self.card_id] = {"bank": None, "normal": [], "evo": []}
        voices.save_mapping(self.app.voice_map)
        self.app._update_voice_button()
        self.close()

    @staticmethod
    def _as_text(entry):
        import json
        return json.dumps(entry, sort_keys=True)

    def restore_default(self):
        """Vuelve la voz de esta carta a la original (defaults/voces.json). Las demás cartas no se tocan."""
        import json
        from tkinter import messagebox
        name = self.app.data.cards[self.card_id]["name_en"]
        if not messagebox.askyesno("Por defecto", f"¿Volver la voz de {name} a la original?\n"
                                   "Se pierden los cambios que hiciste en la voz de esta carta.", parent=self):
            return
        if self.default:
            self.app.voice_map[self.card_id] = json.loads(json.dumps(self.default))
        else:
            self.app.voice_map.pop(self.card_id, None)
        voices.save_mapping(self.app.voice_map)
        self.app.voice_pos.pop((self.card_id, False), None)
        self.app.voice_pos.pop((self.card_id, True), None)
        self.app._update_voice_button()
        self.close()

    def close(self):
        self.recording = None
        self.destroy()


def load_corrections():
    """traducciones/correcciones.json: arreglos publicados a mano (se bajan de GitHub al actualizar)."""
    try:
        return json.loads((ROOT / "traducciones" / "correcciones.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def choose_game_folder(parent):
    """Elegir a mano la carpeta del juego (si no está en una biblioteca de Steam que el programa encuentre solo)."""
    from tkinter import filedialog
    import paths
    now = paths.game_data()
    folder = filedialog.askdirectory(
        parent=parent, title="Elegí la carpeta donde está instalado Shadowverse: Worlds Beyond",
        initialdir=str(now) if now else None, mustexist=True)
    if not folder:
        return False
    found = paths.find_game_in(folder)
    if found is None:
        messagebox.showwarning(
            "Carpeta del juego",
            "En esa carpeta no encontré los audios de Shadowverse: Worlds Beyond.\n\nElegí la carpeta del juego "
            "(«ShadowverseWB», la que tiene «ShadowverseWB.exe») o la biblioteca de Steam donde está instalado. "
            "Si está en otra PC o en una carpeta con contraseña, primero tiene que poder abrirse desde el Explorador "
            "de Windows.", parent=parent)
        return False
    paths.save_setting("carpeta_juego", str(found))
    messagebox.showinfo("Carpeta del juego", f"Listo: el programa va a usar el juego de\n{found}\n\nLas voces se "
                        "preparan al actualizar.", parent=parent)
    return True


def restart_program(window):
    """Cierra el programa y lo vuelve a abrir (para cargar las cartas recién actualizadas)."""
    import subprocess
    import paths
    args = [sys.executable] if paths.FROZEN else [sys.executable, str(Path(__file__).resolve())]
    subprocess.Popen(args, cwd=str(ROOT))
    window.destroy()


class UpdateWindow(tk.Toplevel):
    """Ventana de «Actualizar»: corre tools/updater.py en segundo plano y muestra lo que va haciendo."""

    def __init__(self, master, first_time=False, on_close=None, program_only=False):
        super().__init__(master)
        self.title("Actualizar Spanishverse Library")
        self.program_only = program_only
        self.configure(bg=PANEL, padx=16, pady=14)
        self.geometry("720x480")
        self.minsize(520, 340)
        self.on_close = on_close
        self.protocol("WM_DELETE_WINDOW", self.close)
        intro = ("Se baja la versión nueva del programa y se instala sola: el programa se cierra y se vuelve a abrir. "
                 "Tus mazos, voces, imágenes y ajustes se conservan." if program_only else
                 "Primera vez: se bajan las imágenes de las cartas y las ilustraciones, y se preparan las voces del "
                 "juego. Puede tardar un buen rato; podés dejarlo trabajando." if first_time else
                 "Se bajan las cartas nuevas con sus imágenes, traducciones, voces e ilustraciones.")
        tk.Label(self, text="Actualizando", bg=PANEL, fg=INK, font=F("Segoe UI Semibold", 13)).pack(anchor="w")
        tk.Label(self, text=intro, bg=PANEL, fg=MUTED, font=F(*FONT), wraplength=660, justify="left").pack(
            anchor="w", pady=(2, 8))
        self.bar = ttk.Progressbar(self, mode="indeterminate")
        self.bar.pack(fill="x")
        self.bar.start(12)
        # Los botones se ubican abajo antes que el registro: así el registro no los empuja fuera de la ventana.
        self.buttons = tk.Frame(self, bg=PANEL)
        self.buttons.pack(side="bottom", fill="x")
        frame = tk.Frame(self, bg=PANEL)
        frame.pack(fill="both", expand=True, pady=8)
        self.log = tk.Text(frame, bg=FIELD, fg=INK, relief="flat", font=F("Consolas", 9), wrap="word",
                           state="disabled", padx=8, pady=6)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.close_btn = ttk.Button(self.buttons, text="Cerrar", command=self.close, state="disabled")
        self.close_btn.pack(side="right")
        self.running = True
        # El trabajo va en otro hilo y deja sus mensajes en una cola; la ventana los lee desde su propio hilo
        # (tkinter no se puede tocar desde otro hilo).
        self.messages = queue.Queue()
        threading.Thread(target=self._work, daemon=True).start()
        self._poll_id = self.after(100, self._poll)

    def destroy(self):
        """Al cerrar, se cancela la lectura periódica de mensajes (si no, Tcl avisa de un comando inexistente)."""
        try:
            self.after_cancel(self._poll_id)
        except (AttributeError, tk.TclError, ValueError):
            pass
        super().destroy()

    def write(self, text):
        self.messages.put(("texto", text))

    def _poll(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:  # la ventana (o el programa) ya se cerró
            return
        lines = []
        while not self.messages.empty():
            kind, value = self.messages.get()
            if kind == "fin":
                self._append("\n".join(lines)) if lines else None
                self._done(value)
                return
            if kind == "instalar":
                self._append("\n".join(lines)) if lines else None
                self._install(value)
                return
            lines.append(value)
        if lines:
            self._append("\n".join(lines))
        self._poll_id = self.after(100, self._poll)

    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _work(self):
        if self.program_only:
            return self._work_program()
        try:
            import updater
            info = updater.remote_info()
            version = updater.program_update(info)
            if version:  # versión nueva del programa: se instala primero y el programa nuevo sigue con el resto
                self.write(f"Hay una versión nueva del programa ({version}): se instala primero y después sigue la "
                           "actualización de las cartas.")
                script = updater.prepare_program_update(self.write)
                if script:
                    self.messages.put(("instalar", script))
                    return
            elif updater.new_version(info) and updater.install_blocked(updater.new_version(info)):
                self.write(f"La versión {updater.new_version(info)} no se pudo instalar sola en esta PC (puede ser el "
                           "antivirus). Bajala a mano desde la página de GitHub; mientras tanto sigue la actualización.")
            result = updater.run(progress=self.write)
        except Exception as e:  # no debería pasar: cada paso maneja sus errores
            self.write(f"Error inesperado: {e}")
            result = {}
        self.messages.put(("fin", result))

    def _work_program(self):
        try:
            import updater
            script = updater.prepare_program_update(self.write)
        except Exception as e:
            self.write(f"Error inesperado: {e}")
            script = None
        self.messages.put(("instalar", script))

    def _install(self, script):
        """La versión nueva ya está bajada: se cierra el programa y un script la copia y lo vuelve a abrir."""
        self.running = False
        self.bar.stop()
        if not script:
            self.close_btn.configure(state="normal")
            return
        import updater
        self._append("\nEl programa se cierra, instala la versión nueva y se vuelve a abrir solo para terminar de "
                     "actualizar. Tus mazos, voces, imágenes y ajustes se conservan.")
        self.update()
        updater.run_program_update(script)
        self.after(300, self.master.destroy)

    def install_new_version(self):
        if not messagebox.askyesno("Instalar la versión nueva",
                                   "Se va a bajar e instalar la versión nueva. El programa se cierra y se vuelve a abrir "
                                   "solo. Tus mazos, voces, imágenes y ajustes se conservan.\n\n¿Seguir?", parent=self):
            return
        self.program_only = self.running = True
        self.close_btn.configure(state="disabled")
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)
        threading.Thread(target=self._work_program, daemon=True).start()
        self._poll_id = self.after(100, self._poll)

    def _done(self, result):
        self.running = False
        self.bar.stop()
        self.bar.configure(mode="determinate", value=100)
        self.close_btn.configure(state="normal")
        if hasattr(self.master, "_mark_update_button"):  # el botón «Actualizar» deja de estar marcado
            self.master.pending = ([f"Versión nueva del programa: {result['version_nueva']}"]
                                   if result.get("version_nueva") else [])
            self.master._mark_update_button()
        if result.get("version_nueva"):
            import config
            import paths
            if paths.FROZEN and result.get("programa"):
                self._append(f"\nHay una versión nueva del programa ({result['version_nueva']}). Apretá «Instalar la "
                             "versión nueva»: se instala sola y conserva tus mazos, voces e imágenes.")
                ttk.Button(self.buttons, text="⬇ Instalar la versión nueva", style="Active.TButton",
                           command=self.install_new_version).pack(side="left", padx=(8, 0))
            else:
                self._append(f"\nHay una versión nueva del programa ({result['version_nueva']}). Bajala desde la "
                             "página de GitHub para tener las últimas mejoras.")
                ttk.Button(self.buttons, text="Ir a la descarga",
                           command=lambda: webbrowser.open(config.releases_page())).pack(side="left", padx=(8, 0))
        ttk.Button(self.buttons, text="Reiniciar el programa", style="Active.TButton",
                   command=lambda: restart_program(self.master)).pack(side="right", padx=(0, 8))
        self._append("\nPara ver lo nuevo, reiniciá el programa.")

    def close(self):
        if self.running and not messagebox.askyesno(
                "Actualizar", "La actualización sigue trabajando. Si cerrás, queda a medias y se retoma la próxima "
                "vez. ¿Cerrar igual?", parent=self):
            return
        self.destroy()
        if self.on_close:
            self.on_close()


class ImageZoom:
    """La imagen de una carta en grande, como en el juego: el fondo se oscurece; clic en la imagen la rota
    (vertical <-> horizontal); mantener y arrastrar la mueve; la ruedita hace zoom; si queda casi toda afuera,
    vuelve al centro; Esc o clic en el fondo cierran. Abre ajustada a la ventana y el zoom llega como mucho a su
    tamaño real: agrandarla más la pixelaría."""

    def __init__(self, app, path):
        from PIL import Image, ImageEnhance, ImageGrab, ImageTk
        self.app, self.Image, self.ImageTk = app, Image, ImageTk
        app.update_idletasks()
        x, y, w, h = app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()
        self.w, self.h = w, h
        try:  # el fondo: la ventana del programa, oscurecida
            shot = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).resize((w, h))
            back = ImageEnhance.Brightness(shot.convert("RGB")).enhance(0.25)
        except Exception:
            back = Image.new("RGB", (w, h), (11, 11, 15))
        self.canvas = tk.Canvas(app, highlightthickness=0, bd=0, bg="#0b0b0f")
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Misc.tkraise(self.canvas)  # (en un Canvas, tkraise sería el de sus dibujos)
        self.back = ImageTk.PhotoImage(back)
        self.canvas.create_image(0, 0, anchor="nw", image=self.back)
        self.canvas.create_text(w - 24, h - 20, anchor="se", fill="#c9c6d6", font=F("Segoe UI", 10),
                                text="Clic: rotar    ·    Mantener y arrastrar: mover    ·    Rueda: zoom    ·    "
                                     "Esc o clic afuera: cerrar")
        self.source = Image.open(path).convert("RGBA")
        self.rotated, self.cx, self.cy = False, w / 2, h / 2
        self.zoom = self._fit()
        self.photo = self.item = None
        self.press = None
        self._render()
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Escape>", lambda _: self.close())
        self.canvas.focus_set()

    def _fit(self):
        """Escala para que entre entera en la ventana (nunca más grande que el tamaño real)."""
        iw, ih = (self.source.height, self.source.width) if self.rotated else self.source.size
        return min(1.0, 0.94 * self.w / iw, 0.94 * self.h / ih)

    def _on_wheel(self, e):
        """Zoom hacia donde apunta el mouse: desde la mitad del ajuste a la ventana hasta el tamaño real."""
        new = min(1.0, max(self._fit() * 0.5, self.zoom * (1.15 if e.delta > 0 else 1 / 1.15)))
        if abs(new - self.zoom) < 1e-4:
            return
        k = new / self.zoom
        self.cx, self.cy = e.x + (self.cx - e.x) * k, e.y + (self.cy - e.y) * k
        self.zoom = new
        self._render()

    def _render(self):
        img = self.source.transpose(self.Image.Transpose.ROTATE_90) if self.rotated else self.source
        if self.zoom < 1.0:  # nunca se agranda por encima del tamaño real: perdería calidad
            img = img.resize((round(img.width * self.zoom), round(img.height * self.zoom)), self.Image.LANCZOS)
        self.photo = self.ImageTk.PhotoImage(img)
        if self.item is None:
            self.item = self.canvas.create_image(self.cx, self.cy, image=self.photo)
        else:
            self.canvas.itemconfigure(self.item, image=self.photo)
            self.canvas.coords(self.item, self.cx, self.cy)

    def _on_image(self, x, y):
        x0, y0, x1, y1 = self.canvas.bbox(self.item)
        return x0 <= x <= x1 and y0 <= y <= y1

    def _on_press(self, e):
        self.press = {"x": e.x, "y": e.y, "cx": self.cx, "cy": self.cy, "on_image": self._on_image(e.x, e.y),
                      "dragging": False}

    def _on_drag(self, e):
        p = self.press
        if not p or not p["on_image"]:
            return
        if not p["dragging"] and abs(e.x - p["x"]) + abs(e.y - p["y"]) > 5:
            p["dragging"] = True
            self.canvas.config(cursor=cursor("agarrar", "fleur"))
        if p["dragging"]:
            self.cx, self.cy = p["cx"] + e.x - p["x"], p["cy"] + e.y - p["y"]
            self.canvas.coords(self.item, self.cx, self.cy)

    def _on_release(self, e):
        p, self.press = self.press, None
        if not p:
            return
        if p["dragging"]:
            self.canvas.config(cursor="")
            self._maybe_recenter()
        elif p["on_image"]:
            self.rotated = not self.rotated
            self._render()
        else:
            self.close()  # clic en el fondo oscuro

    def _maybe_recenter(self):
        """Si la imagen quedó casi toda afuera de la ventana, vuelve al centro (salvo que igual ocupe gran
        parte de la ventana, como pasa con una imagen muy grande)."""
        x0, y0, x1, y1 = self.canvas.bbox(self.item)
        vis_w = max(0, min(x1, self.w) - max(x0, 0))
        vis_h = max(0, min(y1, self.h) - max(y0, 0))
        visible = vis_w * vis_h
        if visible >= 0.5 * (x1 - x0) * (y1 - y0) or visible >= 0.5 * self.w * self.h:
            return
        start, end, steps = (self.cx, self.cy), (self.w / 2, self.h / 2), 12

        def step(i=1):
            t = 1 - (1 - i / steps) ** 3  # frena al llegar
            self.cx = start[0] + (end[0] - start[0]) * t
            self.cy = start[1] + (end[1] - start[1]) * t
            self.canvas.coords(self.item, self.cx, self.cy)
            if i < steps:
                self.canvas.after(16, step, i + 1)
        step()

    def close(self):
        self.canvas.destroy()


class Tooltip:
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.label = tk.Label(self.win, bg="#2a2833", fg=INK, font=F(*FONT), padx=8, pady=4, justify="left",
                              highlightthickness=1, highlightbackground=LINE)
        self.label.pack()

    def show(self, text, x, y, wrap=0):
        """wrap: ancho máximo en píxeles (0 = sin cortar). Nunca se sale de la pantalla."""
        self.label.config(text=text, wraplength=wrap)
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = min(x + 14, sw - w - 8)
        y = y + 16 if y + 16 + h < sh - 40 else y - h - 8  # si no entra abajo, va arriba del mouse
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.win.deiconify()
        self.win.lift()

    def hide(self):
        self.win.withdraw()


def draw_curve(cv, buckets, labels):
    """Curva de costos: una barra por costo, con la cantidad arriba y el costo abajo."""
    cv.delete("all")
    w, h = cv.winfo_width(), cv.winfo_height()
    if w < 50:
        return
    top = max(buckets + [1])
    slot = w / len(labels)
    # Con letra más grande, los números ocupan más alto: las barras se achican para que entren.
    extra = round(F(*FONT).metrics("linespace") * (1 - 1 / _font_scale[0]))
    for i, n in enumerate(buckets):
        x0, x1 = i * slot + slot * 0.22, (i + 1) * slot - slot * 0.22
        bar = (h - 40 - 2 * extra) * n / top
        base = h - 20 - extra
        cv.create_rectangle(x0, base - bar, x1, base, fill=ACCENT if n else LINE, outline="")
        cv.create_text((x0 + x1) / 2, base - 6 - bar, text=str(n), fill=INK if n else MUTED, font=F(*FONT), anchor="s")
        cv.create_text((x0 + x1) / 2, h - 10 - extra / 2, text=labels[i], fill=MUTED, font=F(*FONT))


class DeckBuilder(tk.Frame):
    """Armador de mazos, como el de la página oficial: formato y clase, cartas de esa clase y neutrales
    (hasta 3 copias, 40 en total), curva de costos, tipos, cuántos viales cuesta crearlo y el código para
    cargarlo en el juego. Elegir una carta la muestra en el detalle de la ventana principal."""
    CURVE = ("≤1", "2", "3", "4", "5", "6", "7", "8+")
    BAD = "#e06c6c"

    def __init__(self, app):
        # Va en la ventana principal, en el lugar de la lista de cartas (App.open_deck_builder lo intercambia).
        super().__init__(app.pane, bg=PANEL)
        self.app, self.data = app, app.data
        self.counts = {}
        self.class_id = None
        self.related = None  # (tipo, carta): en la lista de la izquierda, las creadoras o lo que trae esa carta
        self.job = None  # pedido a la página oficial en curso: (hilo, resultado, qué hacer al terminar)
        self.classes = {self.data.label("classes", k): k for k in sorted(self.data.lookup["classes"]) if k}

        head = tk.Frame(self, bg=PANEL, padx=12, pady=10)
        head.pack(fill="x")
        # A la izquierda formato, clase y nombre; a la derecha los botones. Si no entran en un renglón
        # (columna angosta o letra grande), los botones pasan abajo, alineados a la derecha.
        fields, buttons = tk.Frame(head, bg=PANEL), tk.Frame(head, bg=PANEL)
        self.format_switch = Switch(fields, "Ilimitado", "Rotación", self._changed_format, bg=PANEL)
        self.format_switch.pack(side="left", padx=(0, 16))
        tk.Label(fields, text="Clase", bg=PANEL, fg=MUTED, font=F(*FONT)).pack(side="left", padx=(0, 6))
        self.class_var = tk.StringVar()
        self.class_box = ttk.Combobox(fields, textvariable=self.class_var, values=list(self.classes),
                                      state="readonly", width=13)
        self.class_box.pack(side="left", padx=(0, 16))
        self.class_box.bind("<<ComboboxSelected>>", lambda _: self._changed_class())
        tk.Label(fields, text="Nombre", bg=PANEL, fg=MUTED, font=F(*FONT)).pack(side="left", padx=(0, 6))
        self.name = tk.StringVar(value="Mazo nuevo")
        name_entry = ttk.Entry(fields, textvariable=self.name, width=24)
        name_entry.pack(side="left")
        app.entry_menu(name_entry)
        # «✕ Cerrar» vuelve a la lista de cartas de siempre (el mazo queda como estaba para la próxima vez).
        ttk.Button(buttons, text="✕ Cerrar", command=app.close_deck_builder).pack(side="right")
        ttk.Button(buttons, text="Guardar", command=self.save).pack(side="right", padx=(0, 6))
        self.saved_btn = ttk.Button(buttons, text="Mis mazos ▾", command=self._saved_menu)
        self.saved_btn.pack(side="right", padx=(0, 6))
        ttk.Button(buttons, text="Nuevo", command=self.new).pack(side="right", padx=(0, 6))
        ttk.Button(buttons, text="Vaciar mazo", command=self.clear).pack(side="right", padx=(0, 6))

        def fit_head(_=None):
            one_row = head.winfo_width() - 24 >= fields.winfo_reqwidth() + buttons.winfo_reqwidth() + 16
            if one_row != getattr(head, "one_row", None):
                head.one_row = one_row
                fields.pack_forget(), buttons.pack_forget()
                fields.pack(side="left" if one_row else "top", anchor="w")
                buttons.pack(side="right" if one_row else "top", anchor="e", pady=0 if one_row else (8, 0))
        head.bind("<Configure>", fit_head)
        fit_head()

        self.inner = ttk.PanedWindow(self, orient="horizontal")
        self.inner.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.inner.add(self._pool_side(self.inner), weight=3)
        self.inner.add(self._deck_side(self.inner), weight=2)

        # El mazo vive mientras el programa está abierto: lo que no se guarda en «Mis mazos» se pierde al cerrarlo.
        self._fill_pool()
        self._update()

    # ---------- armado de la ventana ----------
    def _tree(self, parent, cols):
        tree = ttk.Treeview(parent, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, width, stretch in cols:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=width if not stretch else 120, stretch=stretch,
                        anchor="w" if stretch else "center")
        scale_columns(tree)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        tree.bind("<<TreeviewSelect>>", lambda _: self._show_selected(tree))
        return tree

    def _pool_side(self, pane):
        side = ttk.Frame(pane, style="Panel.TFrame")
        top = self.search_row = tk.Frame(side, bg=PANEL)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        # En su lugar, con «Ver creadoras» / «Ver lo que trae»: de qué carta es la lista y cómo volver.
        rel = self.related_row = tk.Frame(side, bg=FIELD, padx=8, pady=6)
        ttk.Button(rel, text="← Volver a todas las cartas", command=lambda: self.show_related(None)).pack(side="right")
        self.related_label = tk.Label(rel, text="", bg=FIELD, fg=INK, font=F("Segoe UI Semibold", 10), anchor="w",
                                      justify="left")
        self.related_label.pack(side="left", fill="x", expand=True)
        rel.bind("<Configure>", lambda e: self.related_label.config(wraplength=max(150, e.width - 230)))
        tk.Label(top, text="Buscar", bg=PANEL, fg=MUTED, font=F(*FONT)).pack(side="left", padx=(0, 6))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_pool())
        entry = ttk.Entry(top, textvariable=self.search)
        entry.pack(side="left", fill="x", expand=True)
        self.app.entry_menu(entry)
        self.pool_count = tk.Label(top, text="", bg=PANEL, fg=MUTED, font=F(*FONT))
        self.pool_count.pack(side="left", padx=(10, 0))
        self.pool = self._tree(side, (("cost", "Costo", 50, False), ("name", "Nombre", 200, True),
                                      ("name_es", "Nombre en español", 170, True), ("type", "Tipo", 100, False),
                                      ("rarity", "Rareza", 85, False), ("have", "En el mazo", 80, False)))
        self.pool.tag_configure("full", foreground=MUTED)
        self.pool.tag_configure("no", foreground=MUTED)  # en la lista de relacionadas: no puede ir al mazo
        self.pool.bind("<Double-1>", lambda e: self._on_row(self.pool, e, 1))
        self.pool.bind("<Return>", lambda _: self._selected_change(self.pool, 1))
        self.pool.bind("<Button-3>", lambda e: self._on_row(self.pool, e, -1))
        tk.Label(side, text="Doble clic o Enter: agregar una copia · Clic derecho: sacar una",
                 bg=PANEL, fg=MUTED, font=F("Segoe UI", 9)).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        return side

    def _deck_side(self, pane):
        side = ttk.Frame(pane, style="Panel.TFrame", padding=(10, 0, 0, 0))
        top = tk.Frame(side, bg=PANEL)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        # El mazo de forma visual, como en el juego (se puede usar en cuanto hay alguna carta).
        self.view_btn = ttk.Button(top, text="🂠 Ver mazo", command=self.open_view, state="disabled")
        self.view_btn.pack(side="right", anchor="n")
        self.total_label = tk.Label(top, text="", bg=PANEL, fg=INK, font=F("Segoe UI Semibold", 13), anchor="w",
                                    justify="left")
        self.total_label.pack(side="left")
        # Si no entra al lado del botón, el total sigue en un segundo renglón.
        top.bind("<Configure>", lambda e: self.total_label.config(
            wraplength=max(120, e.width - self.view_btn.winfo_reqwidth() - 12)))
        self.deck = self._tree(side, (("cost", "Costo", 50, False), ("name", "Nombre", 200, True),
                                      ("n", "Copias", 60, False)))
        self.deck.tag_configure("bad", foreground=self.BAD)
        self.deck.bind("<Double-1>", lambda e: self._on_row(self.deck, e, -1))
        self.deck.bind("<Delete>", lambda _: self._selected_change(self.deck, -1))
        self.deck.bind("<Button-3>", lambda e: self._on_row(self.deck, e, 1))
        info = tk.Frame(side, bg=PANEL)
        info.grid(row=2, column=0, columnspan=2, sticky="ew")
        tk.Label(info, text="Doble clic o Supr: sacar una · Clic derecho: agregar otra",
                 bg=PANEL, fg=MUTED, font=F("Segoe UI", 9)).pack(anchor="w", pady=(4, 8))
        tk.Label(info, text="CURVA DE COSTOS", bg=PANEL, fg=MUTED, font=F("Segoe UI Semibold", 8)).pack(anchor="w")
        self.curve = tk.Canvas(info, bg=PANEL, height=120, highlightthickness=0)
        self.curve.pack(fill="x", pady=(2, 8))
        self.curve.bind("<Configure>", lambda _: self._draw_curve())
        self.types_label = tk.Label(info, text="", bg=PANEL, fg=INK, font=F(*FONT), anchor="w", justify="left")
        self.types_label.pack(fill="x")
        self.vials_label = tk.Label(info, text="", bg=PANEL, fg=INK, font=F("Segoe UI Semibold", 11), anchor="w")
        self.vials_label.pack(fill="x", pady=(8, 0))
        self.rarity_label = tk.Label(info, text="", bg=PANEL, fg=MUTED, font=F(*FONT), anchor="w", justify="left",
                                     wraplength=300)
        self.rarity_label.pack(fill="x")
        self.problems_label = tk.Label(info, text="", bg=PANEL, fg=self.BAD, font=F(*FONT), anchor="w", justify="left",
                                       wraplength=300)
        self.problems_label.pack(fill="x", pady=(8, 0))
        info.bind("<Configure>", lambda e: [lbl.config(wraplength=max(200, e.width - 10))
                                            for lbl in (self.problems_label, self.rarity_label)])

        tk.Label(info, text="CÓDIGO PARA EL JUEGO", bg=PANEL, fg=MUTED,
                 font=F("Segoe UI Semibold", 8)).pack(anchor="w", pady=(12, 2))
        row = tk.Frame(info, bg=PANEL)
        row.pack(fill="x")
        self.code_btn = ttk.Button(row, text="Generar código", command=self.make_code)
        self.code_btn.pack(side="left")
        self.code = tk.StringVar()
        code_entry = tk.Entry(row, textvariable=self.code, state="readonly", width=8, relief="flat",
                              readonlybackground=FIELD, fg=KW, font=F("Consolas", 16, "bold"), justify="center")
        code_entry.pack(side="left", padx=8, ipady=2)
        ttk.Button(row, text="Copiar", command=self.copy_code).pack(side="left")
        row2 = tk.Frame(info, bg=PANEL)
        row2.pack(fill="x", pady=(6, 0))
        self.import_btn = ttk.Button(row2, text="Cargar un código", command=self.import_code)
        self.import_btn.pack(side="left")
        ttk.Button(row2, text="Ver en la página oficial", command=self.open_official).pack(side="left", padx=(6, 0))
        self.status = tk.Label(info, text="", bg=PANEL, fg=MUTED, font=F(*FONT), anchor="w", justify="left", wraplength=300)
        self.status.pack(fill="x", pady=(6, 0))
        info.bind("<Configure>", lambda e: self.status.config(wraplength=max(200, e.width - 10)), add="+")
        return side

    # ---------- cartas disponibles y mazo ----------
    def _format(self):
        return decks.ROTATION if self.format_switch.var.get() == "Rotación" else decks.UNLIMITED

    def _row(self, c):
        d = self.data
        return [c["cost"], c["name_en"], c["name_es"] or "", d.label("types", c["type_id"]),
                d.label("rarities", c["rarity_id"])]

    def show_related(self, kind, card_id=None):
        """La lista de la izquierda pasa a mostrar las creadoras ("creators") o lo que trae ("creations") de una
        carta; con kind=None vuelve a todas las cartas."""
        self.related = (kind, card_id) if kind else None
        base = self.pool.base_widths["have"][0]
        self.pool.column("have", width=round((base * 2.2 if self.related else base) * _font_scale[0]))
        if self.related:
            c = self.data.cards[card_id]
            what = "Cartas que pueden crear o traer a" if kind == "creators" else "Cartas que crea o puede traer"
            self.related_label.config(text=f"{what} {c['name_en']}")
            self.search_row.grid_remove()
            self.related_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        else:
            self.related_row.grid_remove()
            self.search_row.grid()
            if self.app.creators_mode:
                self.app.creators_mode = None
                self.app._sync_mode_buttons()
        self._fill_pool()

    def _fill_related(self):
        kind, card_id = self.related
        d = self.data
        sure, possible = (d.creators_of if kind == "creators" else d.creations_of)(card_id)
        where = {"mazo": "de tu mazo", "cementerio": "de tu cementerio"}
        by_cost = lambda i: (d.cards[i]["cost"] or 0, d.cards[i]["class_id"] == 0, d.cards[i]["name_en"].lower())
        n = 0
        for cid in sorted(sure, key=by_cost) + sorted(possible, key=by_cost):
            c = d.cards[cid]
            why = self.cannot_add(cid)
            note = "posible" + (f" ({where[possible[cid]]})" if possible.get(cid) in where else "") \
                if cid in possible else ""
            self.pool.insert("", "end", iid=str(cid), values=self._row(c) + [""], tags=("no",) if why else ())
            self.pool.set(str(cid), "have", why or note)
            n += 1
        self.pool_count.config(text=f"{n} cartas")
        self.related_label.config(text=self.related_label.cget("text").split("  (")[0] + f"  ({n})")
        self._mark_pool()

    def _fill_pool(self):
        """Cartas que se pueden poner: de la clase elegida y neutrales, sin fichas (y en Rotación, solo las de la
        rotación), ordenadas por costo como en el juego."""
        self.pool.delete(*self.pool.get_children())
        if self.related:
            return self._fill_related()
        if self.class_id is None:
            self.pool_count.config(text="Elegí una clase para empezar")
            return
        words = self.search.get().lower().split()
        rotation = self._format() == decks.ROTATION
        shown = {}
        for c in self.data.cards.values():
            if (not c["is_token"] and c["class_id"] in (self.class_id, 0) and (c["in_rotation"] or not rotation)
                    and all(w in c["haystack"] for w in words)):
                # Reimpresiones (ej. Stormy Blast en Chronicle of Destiny): una sola fila, la original si se puede.
                base = c["base_card_id"] or c["card_id"]
                if base not in shown or c["card_id"] == base:
                    shown[base] = c
        shown = list(shown.values())
        shown.sort(key=lambda c: (c["cost"], c["class_id"] == 0, c["name_en"].lower()))
        for c in shown:
            self.pool.insert("", "end", iid=str(c["card_id"]), values=self._row(c) + [""])
        self.pool_count.config(text=f"{len(shown)} cartas")
        self._mark_pool()

    def _copies(self, card_id):
        """Copias en el mazo de esta carta, contando sus reimpresiones (el límite es entre todas)."""
        base = lambda cid: self.data.cards[cid]["base_card_id"] or cid
        return sum(n for cid, n in self.counts.items() if base(cid) == base(card_id))

    def _mark_pool(self):
        for iid in self.pool.get_children():
            cid = int(iid)
            have = self._copies(cid)
            limit = self.data.cards[cid]["deck_limit"] or 3
            if self.related:
                why = self.cannot_add(cid)
                if not why:
                    old = self.pool.set(iid, "have")
                    note = old if old.startswith("posible") else ""
                    self.pool.set(iid, "have", f"{have} / {limit}" if have else note)
                self.pool.item(iid, tags=("no",) if why else ("full",) if have >= limit else ())
                continue
            self.pool.set(iid, "have", f"{have} / {limit}" if have else "")
            self.pool.item(iid, tags=("full",) if have >= limit else ())

    def cannot_add(self, card_id):
        """Por qué esta carta no puede ir a este mazo (texto corto), o None si puede."""
        c = self.data.cards[card_id]
        if c["is_token"]:
            return "ficha"
        if self.class_id is None:
            return "elegí una clase"
        if c["class_id"] not in (0, self.class_id):
            return "otra clase"
        if self._format() == decks.ROTATION and not c["in_rotation"]:
            return "fuera de Rotación"
        return None

    def change(self, card_id, delta):
        c = self.data.cards[card_id]
        if delta > 0:
            why = self.cannot_add(card_id)
            if why:
                reasons = {"ficha": "es una ficha: se crea durante la partida y no va en el mazo",
                           "elegí una clase": "primero elegí la clase del mazo",
                           "otra clase": "es de otra clase",
                           "fuera de Rotación": "no está en Rotación (cambiá el formato a Ilimitado)"}
                return self._say(f"{c['name_en']} no se puede agregar: {reasons[why]}.", self.BAD)
            limit = c["deck_limit"] or 3
            if self._copies(card_id) >= limit:
                return self._say(f"Ya tenés {limit} copias de {c['name_en']} (es el máximo).")
            if sum(self.counts.values()) >= decks.DECK_SIZE:
                return self._say(f"El mazo ya tiene {decks.DECK_SIZE} cartas.")
        n = self.counts.get(card_id, 0) + delta
        if n <= 0:
            self.counts.pop(card_id, None)
        else:
            self.counts[card_id] = n
        self._say("")
        self._update()

    def _on_row(self, tree, event, delta):
        iid = tree.identify_row(event.y)
        if iid:
            tree.selection_set(iid)
            self.change(int(iid), delta)
        return "break"

    def _selected_change(self, tree, delta):
        sel = tree.selection()
        if sel:
            self.change(int(sel[0]), delta)

    def _show_selected(self, tree):
        sel = tree.selection()
        if sel and int(sel[0]) != self.app.current:
            self.app.show(int(sel[0]))

    def _update(self):
        """Redibuja el mazo y sus datos."""
        d, fmt = self.data, self._format()
        selected = self.deck.selection()
        self.deck.delete(*self.deck.get_children())
        bad = {cid for cid in self.counts if (fmt == decks.ROTATION and not d.cards[cid]["in_rotation"])
               or d.cards[cid]["class_id"] not in (0, self.class_id)}
        for cid in sorted(self.counts, key=lambda k: (d.cards[k]["cost"], d.cards[k]["name_en"].lower())):
            c = d.cards[cid]
            self.deck.insert("", "end", iid=str(cid), values=(c["cost"], c["name_en"], f"×{self.counts[cid]}"),
                             tags=("bad",) if cid in bad else ())
        if selected and self.deck.exists(selected[0]):
            self.deck.selection_set(selected[0])
        self._mark_pool()
        total = sum(self.counts.values())
        cls = d.label("classes", self.class_id) if self.class_id is not None else "sin clase"
        self.total_label.config(text=f"{total} / {decks.DECK_SIZE} cartas  ·  {cls}  ·  {self.format_switch.var.get()}",
                                fg=INK if total == decks.DECK_SIZE else MUTED)
        self.types_label.config(text="   ".join(f"{k}: {n}" for k, n in self.type_counts().items()))
        self.vials_label.config(text=f"Costo para crearlo: {self.vials_text()}")
        self.view_btn.config(state="normal" if self.counts else "disabled")
        by_rarity = {}
        for cid, n in self.counts.items():
            by_rarity[d.cards[cid]["rarity_id"]] = by_rarity.get(d.cards[cid]["rarity_id"], 0) + n
        text = "   ".join(f"{d.label('rarities', r)}: {by_rarity[r]}" for r in sorted(by_rarity))
        basic = sum(n for cid, n in self.counts.items() if d.cards[cid]["set_id"] == decks.BASIC_SET)
        if self.counts:
            text += ("\nCada copia: Bronce 50 · Plata 90 · Oro 750 · Legendaria 3.500 viales"
                     + (f" (las {basic} de Basic no se crean: ya las tenés)" if basic else ""))
        self.rarity_label.config(text=text)
        issues = decks.problems(d.cards, fmt, self.class_id, self.counts) if self.class_id is not None else []
        self.problems_label.config(text="\n".join("• " + p for p in issues))
        self.code.set("")
        self._draw_curve()

    def curve_counts(self):
        """Copias por costo: ≤1, 2, ..., 7, 8+ (como la curva del juego)."""
        buckets = [0] * len(self.CURVE)
        for cid, n in self.counts.items():
            buckets[min(max((self.data.cards[cid]["cost"] or 0) - 1, 0), len(self.CURVE) - 1)] += n
        return buckets

    def type_counts(self):
        by_type = {"Combatientes": 0, "Hechizos": 0, "Amuletos": 0}
        for cid, n in self.counts.items():
            by_type[{1: "Combatientes", 4: "Hechizos"}.get(self.data.cards[cid]["type_id"], "Amuletos")] += n
        return by_type

    def vials_text(self):
        vials = sum(decks.vials(self.data.cards[cid]) * n for cid, n in self.counts.items())
        return f"{vials:,} viales".replace(",", ".")

    def _draw_curve(self):
        draw_curve(self.curve, self.curve_counts(), self.CURVE)

    def open_view(self):
        if self.counts:
            DeckView(self.app, self)

    def _say(self, text, color=MUTED):
        self.status.config(text=text, fg=color)

    # ---------- formato, clase y mazos guardados ----------
    def _changed_format(self):
        self._fill_pool()
        self._update()

    def _changed_class(self):
        new = self.classes[self.class_var.get()]
        if new == self.class_id:
            return
        others = {cid for cid in self.counts if self.data.cards[cid]["class_id"] not in (0, new)}
        if others and not messagebox.askyesno(
                "Cambiar de clase", "Al cambiar de clase se sacan del mazo las cartas de la clase anterior "
                "(las neutrales quedan). ¿Seguir?", parent=self):
            self.class_var.set(self.data.label("classes", self.class_id))
            return
        for cid in others:
            del self.counts[cid]
        self.class_id = new
        self._fill_pool()
        self._update()

    def _load(self, name, fmt, class_id, counts):
        unknown = [cid for cid in counts if cid not in self.data.cards]
        self.counts = {cid: n for cid, n in counts.items() if cid in self.data.cards}
        self.name.set(name)
        self.format_switch.var.set("Rotación" if fmt == decks.ROTATION else "Ilimitado")
        self.class_id = class_id
        self.class_var.set(self.data.label("classes", class_id))
        return unknown

    def new(self):
        if self.counts and not messagebox.askyesno(
                "Mazo nuevo", "¿Empezar un mazo nuevo? Lo que no guardaste de este mazo se pierde.", parent=self):
            return
        self.counts = {}
        self.name.set("Mazo nuevo")
        self._say("")
        self._update()

    def clear(self):
        """Saca todas las cartas (quedan el nombre, la clase y el formato)."""
        if not self.counts:
            return self._say("El mazo ya está vacío.")
        if messagebox.askyesno("Vaciar mazo", "¿Sacar todas las cartas del mazo?", parent=self):
            self.counts = {}
            self._update()
            self._say("Se sacaron todas las cartas del mazo.")

    def save(self):
        if self.class_id is None:
            return self._say("Elegí una clase antes de guardar.", self.BAD)
        name = self.name.get().strip() or "Mazo sin nombre"
        self.name.set(name)
        if decks.exists(name) and not messagebox.askyesno(
                "Guardar", f"Ya hay un mazo guardado con el nombre «{name}». ¿Reemplazarlo?", parent=self):
            return
        decks.save(name, self._format(), self.class_id, self.counts)
        self._say(f"Guardado en «Mis mazos» como «{name}».")

    def _saved_menu(self):
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=INK, activebackground=ACCENT, activeforeground="#ffffff", font=F(*FONT))
        saved = decks.saved_decks()
        for name, path in saved:
            menu.add_command(label=name, command=lambda p=path: self.open_saved(p))
        if not saved:
            menu.add_command(label="(todavía no guardaste ninguno)", state="disabled")
        current = self.name.get().strip()
        if decks.exists(current):
            menu.add_separator()
            menu.add_command(label=f"Borrar «{current}» de Mis mazos", command=lambda: self.delete_saved(current))
        b = self.saved_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def open_saved(self, path):
        name = decks.load(path)[0]
        if self.counts and name != self.name.get().strip() and not messagebox.askyesno(
                "Mis mazos", f"¿Abrir «{name}»? Lo que no guardaste de este mazo se pierde.", parent=self):
            return
        self._load(*decks.load(path))
        self._fill_pool()
        self._say("")
        self._update()

    def delete_saved(self, name):
        if messagebox.askyesno("Borrar", f"¿Borrar el mazo «{name}» de Mis mazos?", parent=self):
            decks.delete(name)
            self._say(f"«{name}» se borró de Mis mazos.")

    # ---------- página oficial: códigos ----------
    def _run(self, work, done):
        """Hace el pedido a la página oficial sin congelar la ventana; done(resultado, error) al terminar."""
        if self.job:
            return
        box = {}

        def target():
            try:
                box["ok"] = work()
            except Exception as e:  # sin internet, página en mantenimiento, código vencido...
                box["err"] = e
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self.job = (thread, box, done)
        self._poll()

    def _poll(self):
        thread, box, done = self.job
        if thread.is_alive():
            self.after(100, self._poll)
            return
        self.job = None
        if self.winfo_exists():
            done(box.get("ok"), box.get("err"))

    def make_code(self):
        if self.class_id is None:
            return self._say("Elegí una clase y armá el mazo primero.", self.BAD)
        issues = decks.problems(self.data.cards, self._format(), self.class_id, self.counts)
        if issues:
            self._say("Para sacar el código el mazo tiene que estar completo y ser válido.", self.BAD)
            return messagebox.showwarning("No se generó el código", "Para sacar el código el mazo tiene que "
                                          "estar completo y ser válido:\n\n" + "\n".join("• " + p for p in issues),
                                          parent=self)
        fmt, cls, counts = self._format(), self.class_id, dict(self.counts)
        self._say("Pidiendo el código a la página oficial...")

        def done(code, err):
            if err:
                self._say("No se generó el código.", self.BAD)
                return messagebox.showerror("No se generó el código", self._why(err), parent=self)
            self.code.set(code)
            self._say("En el juego, cargá un mazo con código y escribí este código. Si el juego dice que no "
                      "sirve, generá uno nuevo.")
        self._run(lambda: decks.publish_code(fmt, cls, counts), done)

    def copy_code(self):
        if self.code.get():
            self.clipboard_clear()
            self.clipboard_append(self.code.get())
            self._say(f"Código {self.code.get()} copiado.")

    def import_code(self):
        code = simpledialog.askstring("Cargar un código", "Código del mazo (el de 4 letras que da el juego):",
                                      parent=self)
        if code is None:
            return  # canceló
        if not code.strip():
            return messagebox.showwarning("No se cargó el mazo", "No escribiste ningún código.", parent=self)
        if self.counts and not messagebox.askyesno(
                "Cargar un código", "El mazo de ese código reemplaza al que estás armando. ¿Seguir?", parent=self):
            return
        self._say("Buscando el mazo en la página oficial...")

        def done(result, err):
            if err:
                self._say("No se cargó el mazo.", self.BAD)
                return messagebox.showerror("No se cargó el mazo", self._why(err, code.strip()), parent=self)
            fmt, cls, counts = result
            unknown = self._load(f"Mazo {code.strip()}", fmt, cls, counts)
            self._fill_pool()
            self._update()
            summary = (f"{self.data.label('classes', cls)} · {self.format_switch.var.get()} · "
                       f"{sum(self.counts.values())} cartas")
            if unknown:
                missing = sum(counts[c] for c in unknown)
                self._say(f"Mazo cargado a medias: faltan {missing} cartas.", self.BAD)
                messagebox.showwarning("Mazo cargado a medias", f"Se cargó el mazo «{code.strip()}» ({summary}), "
                                       f"pero faltan {missing} cartas que todavía no están en el programa.\n\n"
                                       "Usá «⟳ Actualizar» y volvé a cargar el código.", parent=self)
            else:
                self._say(f"Mazo «{code.strip()}» cargado.")
                messagebox.showinfo("Mazo cargado", f"Se cargó el mazo «{code.strip()}».\n\n{summary}", parent=self)
        self._run(lambda: decks.fetch_deck(code), done)

    @staticmethod
    def _why(err, code=None):
        """Explicación para el usuario de por qué falló el pedido a la página oficial."""
        if isinstance(err, decks.Rejected):
            if code:
                return (f"El código «{code}» no existe o ya venció (los códigos duran poco).\n\n"
                        "Pedí uno nuevo en el juego y probá otra vez.")
            return "La página oficial no aceptó el mazo. Probá de nuevo en un rato."
        return ("No se pudo conectar con la página oficial de Shadowverse.\n\n"
                "Revisá que haya internet y probá de nuevo (la página también puede estar en mantenimiento).")

    def open_official(self):
        if self.class_id is None or not self.counts:
            return self._say("Armá el mazo primero.", self.BAD)
        webbrowser.open(decks.official_url(self._format(), self.class_id, self.counts))


class DeckView(tk.Frame):
    """El mazo de forma visual, como en el juego: arriba sus datos (curva, tipos, cartas, viales) y debajo las
    cartas con sus copias. Un clic en una carta abre al costado su detalle, con sus voces (normales y
    evolucionadas) y los botones «Ver creadoras» / «Ver lo que crea»: muestran esas cartas en el lugar del mazo,
    con − y + para sacarlas o agregarlas («← Volver al mazo» o Esc vuelven). Cubre toda la ventana; «✕ Cerrar» o
    Esc vuelven al armador."""
    TILE = 3  # las imágenes de las cartas, a un tercio (177 x 229)

    def __init__(self, app, builder):
        super().__init__(app, bg=BG)
        self.app, self.data, self.builder = app, app.data, builder
        self.card, self.evo, self.history = None, False, []
        self.voice_pos, self.voice_btns = {}, {}
        self.related = None  # (tipo, carta): en el lugar del mazo, las creadoras o lo que crea esa carta
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        self._header()
        body = self.body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._grid(body)
        self._detail(body)
        self.bind("<Escape>", lambda _: self.show_related(None) if self.related else self.close())
        self.focus_set()

    # ---------- arriba: los datos del mazo ----------
    def _header(self):
        b, d = self.builder, self.data
        head = self.head = tk.Frame(self, bg=PANEL, padx=18, pady=12)
        head.pack(fill="x", padx=12, pady=12, **({"before": self.body} if hasattr(self, "body") else {}))
        left = tk.Frame(head, bg=PANEL)
        left.pack(side="left", fill="y")
        tk.Label(left, text=b.name.get().strip() or "Mazo sin nombre", bg=PANEL, fg=INK,
                 font=F("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(left, text=f"{d.label('classes', b.class_id)} · {b.format_switch.var.get()}", bg=PANEL, fg=MUTED,
                 font=F("Segoe UI", 11)).pack(anchor="w")
        total = sum(b.counts.values())
        tk.Label(left, text=f"{total} / {decks.DECK_SIZE} cartas", bg=PANEL, fg=INK,
                 font=F("Segoe UI Semibold", 15)).pack(anchor="w", pady=(8, 0))
        issues = decks.problems(d.cards, b._format(), b.class_id, b.counts)
        if issues:
            tk.Label(left, text=issues[0], bg=PANEL, fg=DeckBuilder.BAD, font=F(*FONT), wraplength=420,
                     justify="left").pack(anchor="w")
        ttk.Button(head, text="✕ Cerrar", command=self.close).pack(side="right", anchor="n")
        info = tk.Frame(head, bg=PANEL)
        info.pack(side="right", padx=(0, 40))
        for i, (kind, n) in enumerate(b.type_counts().items()):
            tk.Label(info, text=kind, bg=PANEL, fg=ACCENT, font=F("Segoe UI Semibold", 13)).grid(row=i, column=0, sticky="w")
            tk.Label(info, text=str(n), bg=PANEL, fg=INK, font=F("Segoe UI Semibold", 13)).grid(row=i, column=1, sticky="e", padx=(24, 0))
        tk.Label(info, text=f"Costo para crearlo: {b.vials_text()}", bg=PANEL, fg=MUTED,
                 font=F(*FONT)).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        curve = tk.Canvas(head, bg=PANEL, width=440, height=120, highlightthickness=0)
        curve.pack(side="right", padx=(0, 40))
        curve.bind("<Configure>", lambda _: draw_curve(curve, b.curve_counts(), b.CURVE))

    # ---------- las cartas ----------
    # Las cartas se dibujan directo sobre un lienzo (imágenes, textos y botones − / + pintados), no como piezas
    # sueltas: así la grilla se acomoda al ancho desde el primer momento y se desplaza fluida, sin franjas ni
    # cartas que desaparecen, aunque sean muchas.
    IMG_W, IMG_H = 177, 229  # las imágenes a un tercio (TILE)
    PAD = 10

    def _grid(self, body):
        self.wrap = tk.Frame(body, bg=BG)
        self.wrap.pack(side="left", fill="both", expand=True)
        # Barra de la lista de creadoras / lo que crea (arriba de las cartas, solo mientras se ve esa lista).
        self.related_bar = tk.Frame(self.wrap, bg=FIELD, padx=10, pady=8)
        ttk.Button(self.related_bar, text="← Volver al mazo", command=lambda: self.show_related(None)).pack(side="right")
        self.related_label = tk.Label(self.related_bar, text="", bg=FIELD, fg=INK, font=F("Segoe UI Semibold", 11),
                                      anchor="w", justify="left")
        self.related_label.pack(side="left", fill="x", expand=True)
        self.related_bar.bind("<Configure>", lambda e: self.related_label.config(wraplength=max(200, e.width - 180)))
        self.canvas = tk.Canvas(self.wrap, bg=BG, highlightthickness=0, yscrollincrement=24)
        scroll = ttk.Scrollbar(self.wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._redraw_later())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.items = []  # cartas que se muestran: [(carta, nota, motivo_si_no_puede_ir_al_mazo)]
        self._pending_draw = None
        self._loading = None  # carga de imágenes en curso (de a poco, para no congelar la ventana)
        self._deck_tiles()

    def _deck_tiles(self):
        """Las cartas del mazo, con sus copias."""
        d = self.data
        counts = self.builder.counts
        self.items = [(cid, "", None) for cid in
                      sorted(counts, key=lambda k: (d.cards[k]["cost"], d.cards[k]["name_en"].lower()))]
        self.canvas.yview_moveto(0)
        self._draw()

    # ---------- en el lugar del mazo: creadoras o lo que crea una carta ----------
    def show_related(self, kind, card_id=None):
        d = self.data
        self.related = (kind, card_id) if kind else None
        if not self.related:
            self.related_bar.pack_forget()
            self._deck_tiles()
        else:
            sure, possible = (d.creators_of if kind == "creators" else d.creations_of)(card_id)
            what = "Cartas que pueden crear o traer a" if kind == "creators" else "Cartas que crea o puede traer"
            self.related_label.config(text=f"{what} {d.cards[card_id]['name_en']}  ({len(sure) + len(possible)})")
            if not self.related_bar.winfo_manager():
                self.related_bar.pack(fill="x", pady=(0, 8), before=self.wrap.pack_slaves()[0])
            self._related_tiles(sure, possible)
        if self.card is not None:
            self._render()  # los botones del detalle quedan apretados o no

    WHY = {"ficha": "Ficha: no va en el mazo", "otra clase": "Otra clase", "fuera de Rotación": "Fuera de Rotación",
           "elegí una clase": "Elegí la clase del mazo"}

    def _related_tiles(self, sure, possible):
        d, b = self.data, self.builder
        where = {"mazo": "de tu mazo", "cementerio": "de tu cementerio"}
        by_cost = lambda i: (d.cards[i]["cost"] or 0, d.cards[i]["class_id"] == 0, d.cards[i]["name_en"].lower())
        self.items = []
        for cid in sorted(sure, key=by_cost) + sorted(possible, key=by_cost):
            note = ("posible" + (f" · {where[possible[cid]]}" if possible.get(cid) in where else "")
                    if cid in possible else "")
            self.items.append((cid, note, b.cannot_add(cid)))
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(0)
        self._draw()

    def _redraw_later(self):
        """Al cambiar el tamaño, se redibuja una sola vez cuando termina de cambiar."""
        if self._pending_draw:
            self.after_cancel(self._pending_draw)
        self._pending_draw = self.after(40, self._draw)

    def _draw(self):
        """Dibuja la grilla: tantas columnas como entren en el ancho disponible."""
        self._pending_draw = None
        c, d, b = self.canvas, self.data, self.builder
        top = c.yview()[0]
        c.delete("all")
        width = max(c.winfo_width(), self.IMG_W + 2 * self.PAD)
        line = F(*FONT).metrics("linespace")
        small = F("Segoe UI", 9).metrics("linespace")
        related = self.related is not None
        tile_w = self.IMG_W + 2 * self.PAD
        head_h = 0 if related else line + 6
        foot_h = (small + line + 22) if related else 6
        tile_h = head_h + self.IMG_H + foot_h + 2 * self.PAD
        cols = max(1, (width - 8) // tile_w)
        left = 4 + ((width - 8) - cols * tile_w) // 2  # la grilla centrada
        full_deck = sum(b.counts.values()) >= decks.DECK_SIZE
        to_load = []
        for i, (cid, note, why) in enumerate(self.items):
            card = d.cards[cid]
            x0, y0 = left + (i % cols) * tile_w, 4 + (i // cols) * tile_h
            have = b._copies(cid)
            outline = (INK if cid == self.card else ACCENT if have else BG) if related else \
                (ACCENT if cid == self.card else BG)
            c.create_rectangle(x0 + 2, y0 + 2, x0 + tile_w - 2, y0 + tile_h - 2, outline=outline, width=3,
                               tags=("box", f"box{cid}"))
            y = y0 + self.PAD
            if not related:
                c.create_text(x0 + tile_w - self.PAD, y, anchor="ne", text=f"× {b.counts.get(cid, 0)}", fill=INK,
                              font=F("Segoe UI Semibold", 13))
                y += head_h
            tag = f"card{cid}"
            img = self._tile_image(card, load=False)
            if img:
                c.create_image(x0 + self.PAD, y, anchor="nw", image=img, tags=(tag,))
            else:  # imagen que todavía no se cargó (aparece enseguida) o que no está descargada
                c.create_rectangle(x0 + self.PAD, y, x0 + self.PAD + self.IMG_W, y + self.IMG_H, fill=FIELD,
                                   outline=LINE, tags=(tag, f"ph{cid}"))
                c.create_text(x0 + tile_w / 2, y + self.IMG_H / 2, text=card["name_en"], fill=INK, font=F(*FONT),
                              width=self.IMG_W - 16, justify="center", tags=(tag, f"ph{cid}"))
                to_load.append((cid, x0 + self.PAD, y))
            c.tag_bind(tag, "<Button-1>", lambda _, k=cid: self.open_card(k))
            c.tag_bind(tag, "<Enter>", lambda _: c.config(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda _: c.config(cursor=""))
            if not related:
                continue
            y += self.IMG_H + 4
            c.create_text(x0 + tile_w / 2, y, anchor="n", text=note, fill=MUTED, font=F("Segoe UI", 9))
            y += small + 6
            cy = y + (line + 10) / 2
            if why:  # no puede ir al mazo: se dice por qué
                c.create_text(x0 + tile_w / 2, cy, text=self.WHY[why], fill=DeckBuilder.BAD,
                              font=F("Segoe UI Semibold", 10))
                continue
            limit = card["deck_limit"] or 3
            bw, bh = 34, line + 10
            for sign, bx, enabled, delta in (("−", x0 + self.PAD, bool(b.counts.get(cid)), -1),
                                             ("+", x0 + tile_w - self.PAD - bw, have < limit and not full_deck, 1)):
                btag = f"b{delta}_{cid}"
                c.create_rectangle(bx, cy - bh / 2, bx + bw, cy + bh / 2, fill=FIELD if enabled else BG,
                                   outline=LINE, tags=(btag,))
                c.create_text(bx + bw / 2, cy, text=sign, fill=INK if enabled else LINE,
                              font=F("Segoe UI Semibold", 13), tags=(btag,))
                if enabled:
                    c.tag_bind(btag, "<Button-1>", lambda _, k=cid, dl=delta: self._change(k, dl))
                    c.tag_bind(btag, "<Enter>", lambda _: c.config(cursor="hand2"))
                    c.tag_bind(btag, "<Leave>", lambda _: c.config(cursor=""))
            c.create_text(x0 + tile_w / 2, cy, text=f"{have} / {limit}", fill=INK, font=F("Segoe UI Semibold", 11))
        rows = (len(self.items) + cols - 1) // cols
        c.configure(scrollregion=(0, 0, width, max(rows * tile_h + 8, c.winfo_height())))
        c.yview_moveto(top)
        if self._loading:
            self.after_cancel(self._loading)
            self._loading = None
        if to_load:
            self._loading = self.after(1, self._load_images, to_load)

    def _load_images(self, todo):
        """Carga unas pocas imágenes por vez y reemplaza su recuadro: la grilla se ve al instante."""
        self._loading = None
        c = self.canvas
        for cid, x, y in todo[:6]:
            img = self._tile_image(self.data.cards[cid])
            if img and c.find_withtag(f"ph{cid}"):
                c.delete(f"ph{cid}")
                tag = f"card{cid}"
                c.create_image(x, y, anchor="nw", image=img, tags=(tag,))
        if todo[6:]:
            self._loading = self.after(1, self._load_images, todo[6:])

    def _change(self, cid, delta):
        """− / + en la lista de creadoras / lo que crea: saca o agrega una copia al mazo."""
        self.builder.change(cid, delta)
        self._draw()
        self.head.destroy()
        self._header()

    def _tile_image(self, card, load=True):
        """Imagen chica de la carta. Con load=False solo la devuelve si ya está cargada."""
        for lang, folder in (("es", "es419"), ("en", "eng")):
            h = card[f"img_{lang}"]
            path = IMAGES / folder / f"{h}.png" if h else None
            if path is not None and path.exists():
                key = (path, self.TILE)
                if key not in self.app.images and not load:
                    return None
                if key not in self.app.images:
                    try:
                        self.app.images[key] = tk.PhotoImage(file=str(path)).subsample(self.TILE)
                    except tk.TclError:
                        continue
                return self.app.images[key]
        return None

    def _wheel(self, event):
        first, last = self.canvas.yview()
        if (first, last) != (0.0, 1.0):
            self.canvas.yview_scroll(int(-event.delta / 120) * 3, "units")

    # ---------- al costado: el detalle de la carta ----------
    def _detail(self, body):
        self.panel = tk.Frame(body, bg=PANEL, width=580, highlightthickness=1, highlightbackground=LINE)
        self.panel.pack_propagate(False)
        nav = tk.Frame(self.panel, bg=PANEL, padx=10, pady=8)
        nav.pack(fill="x")
        self.back_btn = ttk.Button(nav, text="← Volver", command=self.go_back, state="disabled")
        self.back_btn.pack(side="left")
        tk.Label(nav, text="Detalle de la carta", bg=PANEL, fg=MUTED, font=F("Segoe UI Semibold", 11)).pack(side="left", padx=12)
        ttk.Button(nav, text="✕", width=3, command=self.close_card).pack(side="right")
        t = self.text = tk.Text(self.panel, bg=PANEL, fg=INK, font=F(*FONT), wrap="word", relief="flat", padx=10,
                                highlightthickness=0, cursor="xterm", insertwidth=0, selectbackground=ACCENT,
                                selectforeground="#ffffff", inactiveselectbackground=ACCENT)
        scroll = ttk.Scrollbar(self.panel, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        t.pack(fill="both", expand=True)
        # Mismo formato que el detalle de la ventana principal.
        for tag in ("imgline", "title", "sub", "chip", "h", "b", "i", "bi", "kw", "tip", "link", "note"):
            opts = {k: v[4] for k, v in self.app.text.tag_configure(tag).items() if v[4] not in ("", None)}
            t.tag_configure(tag, **opts)
        t.bind("<Key>", lambda e: self.app._readonly_key(e, t))
        t.bind("<<Paste>>", lambda _: "break")
        t.bind("<<Cut>>", lambda _: "break")

    def open_card(self, card_id, remember=True):
        if remember and self.card is not None and self.card != card_id:
            self.history.append(self.card)
        self.card, self.evo = card_id, False
        self.voice_pos.clear()  # como en la lista: al abrir una carta (otra o la misma de nuevo) las voces arrancan de la 1
        self.back_btn.config(state="normal" if self.history else "disabled")
        if not self.panel.winfo_ismapped():
            self.panel.pack(side="right", fill="y", padx=(12, 0), before=self.wrap)
        self._render()
        self._redraw_later()  # el marco de la carta elegida (y la grilla, que se angostó al abrir el detalle)

    def go_back(self):
        if self.history:
            self.open_card(self.history.pop(), remember=False)

    def close_card(self):
        self.panel.pack_forget()
        self.card, self.history = None, []
        self._redraw_later()

    def toggle_evo(self):
        self.evo = not self.evo
        self._render()

    def _section(self, title, en, es, tr=None):
        if not en and not es:
            return
        self.text.insert("end", "\n" + title + "\n", "h")
        self.app.markup(es or tr or en, "es" if es else "tr" if tr else "en", t=self.text, go=self.open_card)
        self.text.insert("end", "\n")

    def _render(self):
        d, c, t, app = self.data, self.data.cards[self.card], self.text, self.app
        app.tooltip.hide()
        t.config(state="normal")
        t.delete("1.0", "end")
        for tag in t.tag_names():
            if tag.startswith(("kwtag_", "link_")):
                t.tag_delete(tag)
        img = app.load_image(c, self.evo)
        pic = tk.Label(t, image=img or "", text="" if img else "(imagen todavía no descargada)", bg=PANEL, fg=MUTED,
                       font=F(*FONT), cursor=cursor("lupa", "hand2"))
        pic.bind("<Button-1>", lambda _: app.open_zoom(self.card, self.evo))
        t.window_create("end", window=pic, pady=4)
        t.insert("end", "\n")
        t.tag_add("imgline", "1.0", "1.end")
        t.insert("end", c["name_en"] + "\n", "title")
        if c["name_es"]:
            t.insert("end", c["name_es"] + "\n", "sub")
        facts = [f"Costo {c['cost']}"] + ([f"{c['atk']}/{c['life']}"] if c["type_id"] == 1 else [])
        facts += [d.label("classes", c["class_id"]), d.label("types", c["type_id"]), d.label("rarities", c["rarity_id"]),
                  d.lookup["sets"].get(c["set_id"], ("",))[0]]
        t.insert("end", "\n")
        for fact in facts:
            t.insert("end", f" {fact} ".replace(" ", " "), "chip")
            t.insert("end", "  ")
        t.insert("end", "\n\n")

        # Botones: arriba normal / evolucionada y lo que crea; abajo sus voces.
        row = tk.Frame(t, bg=PANEL)
        if c["evo_img_en"] or c["evo_img_es"]:
            ttk.Button(row, text="Ver normal" if self.evo else "Ver evolucionada", width=16,
                       command=self.toggle_evo).pack(side="left", padx=(0, 6))
        for kind, label, finder in (("creators", "⤴ Ver creadoras", d.creators_of),
                                    ("creations", "⤵ Ver lo que crea", d.creations_of)):
            sure, possible = finder(self.card)
            if sure or possible:
                var = tk.BooleanVar(value=self.related == (kind, self.card))
                ttk.Checkbutton(row, text=f"{label} ({len(sure) + len(possible)})", style="Creators.Toolbutton",
                                variable=var, cursor="hand2",
                                command=lambda k=kind, v=var: self.show_related(k if v.get() else None, self.card)
                                ).pack(side="left", padx=(0, 6))
        # (los botones van dentro del texto: sin esto tomarían su puntero de texto en vez de la flecha)
        row.config(cursor="arrow")
        voice_row = tk.Frame(t, bg=PANEL, cursor="arrow")
        entry = app.voice_map.get(self.card) or {} if voices else {}
        self.voice_btns = {}
        for phase, label in (("normal", "🔊 Voz normal"), ("evo", "🔊 Voz evolucionada")):
            lines = entry.get(phase) or []
            if lines:
                heard = self.voice_pos.get((self.card, phase), 0)
                btn = ttk.Button(voice_row, text=f"{label} {heard}/{len(lines)}", command=lambda p=phase: self.play(p))
                btn.pack(side="left", padx=(0, 6))
                self.voice_btns[phase] = (btn, label)
        for frame in (row, voice_row):
            if frame.winfo_children():
                t.window_create("end", window=frame, pady=3)
                t.insert("end", "\n")

        self._section("EFECTO", c["skill_en"], c["skill_es"], c.get("skill_tr"))
        for e in c["specific"]:
            title = d.effect_title(e["key"])
            if e["key"] in ("crystal", "accelerate"):
                title += f" · COSTO {e['cost']}"
            self._section(title, e.get("en"), e.get("es"), e.get("tr"))
        self._section("AMBIENTACIÓN", c["flavour_en"], c["flavour_es"], c.get("flavour_tr"))
        if c["type_id"] == 1:
            self._section("AMBIENTACIÓN EVOLUCIONADA", c["evo_flavour_en"], c["evo_flavour_es"],
                          c.get("evo_flavour_tr"))
        t.insert("end", f"\n\nIlustración: {c['illustrator'] or '—'} · Voz: {c['cv'] or '—'} · ID {c['card_id']}\n", "note")
        t.yview_moveto(0)

    def play(self, phase):
        """Reproduce la siguiente línea de voz (normal o evolucionada); después de la última vuelve a la primera."""
        entry = self.app.voice_map[self.card]
        lines = entry[phase]
        key = (self.card, phase)
        i = self.voice_pos.get(key, 0) % len(lines)
        self.voice_pos[key] = i + 1
        voices.play(voices.line_path(lines[i], entry["bank"]))
        btn, label = self.voice_btns[phase]
        btn.config(text=f"{label} {i + 1}/{len(lines)}")

    def close(self):
        self.app.tooltip.hide()
        self.destroy()


class App(tk.Tk):
    def __init__(self, data, pending=None):
        super().__init__()
        import config
        self.data = data
        self.pending = pending or []  # novedades que el usuario decidió no actualizar al abrir
        self.title(f"Spanishverse Library {config.VERSION}")
        if ICON.exists():  # ícono propio en la ventana y en todas las ventanas secundarias
            self.iconbitmap(default=str(ICON))
        self.geometry("1400x860")  # tamaño al salir de pantalla completa
        self.minsize(480, 420)
        self.state("zoomed")  # se abre maximizada
        self.configure(bg=BG)
        self.images = {}
        self.history = []
        self.current = None
        self.show_evo = False
        # Modo especial de la lista: ("creators" | "creations", carta) o None (lista normal con filtros).
        self.creators_mode = None
        self.creators_var = self.creations_var = None
        self.deck_view = None  # armador de mazos (se crea la primera vez que se abre)
        scale = load_settings().get("tamaño_letra", 1.0)
        self.font_scale_var = tk.DoubleVar(value=scale if scale in FONT_SCALES else 1.0)
        set_font_scale(self.font_scale_var.get())
        self.tooltip = Tooltip(self)
        self._style()
        self._filters()
        self._body()
        self._glossary_panel()
        self.refresh()
        self.update_win = None

    # ---------- aspecto ----------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=INK, fieldbackground=PANEL, font=F(*FONT), bordercolor=LINE)
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=INK)
        s.configure("Muted.TLabel", background=BG, foreground=MUTED)
        s.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        # Botón de "Ver creadoras": se ve apretado (violeta) mientras está activo.
        s.configure("Creators.Toolbutton", background=FIELD, foreground=INK, padding=(10, 4), relief="raised",
                    borderwidth=1, bordercolor=LINE)
        s.map("Creators.Toolbutton", background=[("selected", ACCENT), ("active", LINE)],
              foreground=[("selected", "#ffffff")], relief=[("selected", "sunken")])
        s.configure("Panel.TCheckbutton", background=PANEL, foreground=INK)
        s.map("Panel.TCheckbutton", background=[("active", PANEL)], indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])
        s.configure("TCheckbutton", background=BG, foreground=INK)
        s.map("TCheckbutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT), ("!selected", PANEL)])
        s.configure("TButton", background=PANEL, foreground=INK, padding=(10, 4))
        s.map("TButton", background=[("active", LINE)])
        # Botón de filtro con algo marcado.
        s.configure("Active.TButton", background=ACCENT, foreground="#ffffff", padding=(10, 4))
        s.map("Active.TButton", background=[("active", "#8a6fe0")])
        # Los campos un poco más claros que el fondo, para que se distingan dentro de los recuadros.
        s.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=INK, arrowcolor=INK)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)])
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", INK)
        s.configure("TEntry", fieldbackground=FIELD, foreground=INK, insertcolor=INK, padding=4)
        s.configure("TSpinbox", fieldbackground=FIELD, foreground=INK, arrowcolor=INK)
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK, rowheight=round(24 * _font_scale[0]),
                    borderwidth=0)
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
        s.configure("Treeview.Heading", background=BG, foreground=MUTED, relief="flat")
        s.map("Treeview.Heading", background=[("active", LINE)])
        s.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG, arrowcolor=INK)

    # ---------- filtros ----------
    # ---------- filtros: una fila de botones desplegables ----------
    def _group(self, flow, title, summary):
        """Botón "Título ▾" en la fila de filtros y su panel desplegable (se devuelve para poner los controles).
        summary(): lista de (texto, quitar) con lo que está activo en el grupo, para el botón y la fila de activos."""
        popup = tk.Frame(self, bg=PANEL, padx=12, pady=10, highlightthickness=1, highlightbackground=ACCENT)
        tk.Label(popup, text=title.upper(), bg=PANEL, fg=MUTED, font=F("Segoe UI Semibold", 8)).grid(
            row=0, column=0, columnspan=12, sticky="w", pady=(0, 6))
        btn = ttk.Button(flow, text=f"{title} ▾")
        btn.config(command=lambda: self._toggle_popup(popup, btn))
        flow.add(btn)
        self.filter_groups.append((title, btn, summary))
        self.filter_popups[title] = popup
        return popup

    def _compact_menu(self):
        """Modo compacto (columna angosta): un solo botón "☰ Filtros" con la lista de grupos."""
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=INK, activebackground=ACCENT, activeforeground="#ffffff",
                       font=F(*FONT))
        for title, _, summary in self.filter_groups:
            items = summary()
            label = f"{title}  ({len(items)})" if items else title
            menu.add_command(label=label, command=lambda t=title: self._toggle_popup(self.filter_popups[t], self.compact_btn))
        b = self.compact_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def _font_scale_changed(self):
        """Nuevo tamaño de letra: las fuentes cambian solas; acá se acomoda lo que tiene medidas fijas."""
        scale = self.font_scale_var.get()
        set_font_scale(scale)
        ttk.Style(self).configure("Treeview", rowheight=round(24 * scale))
        self.update_idletasks()
        # El buscador de arriba tiene el alto fijo (el de sus controles al abrir el programa).
        self.search_box.configure(height=max(w.winfo_reqheight() for w in self.search_box.winfo_children()))
        # Los renglones de botones se reacomodan con el nuevo ancho de cada botón.
        stack = [self]
        while stack:
            w = stack.pop()
            if isinstance(w, Flow) and w.winfo_ismapped():
                w._layout(w.winfo_width())
            elif isinstance(w, ttk.Treeview):
                scale_columns(w)
            stack.extend(w.winfo_children())
        self._fit_filters(type("E", (), {"width": self.left.winfo_width()}))
        for cid in list(getattr(self, "expanded", {})):  # recuadros abiertos en la lista: otro alto de texto
            if self.tree.exists(str(cid)):
                self._fit_expansion(cid, force=True)
        self.after_idle(self._place_expansions)
        self.size_tip()

    def _fit_filters(self, event):
        """Con la columna izquierda angosta, los botones de filtro se reemplazan por uno solo."""
        # (el interruptor de formato ocupa ~170 px a la izquierda; con letra más grande, los botones son más anchos)
        compact = event.width < 720 * _font_scale[0]
        if compact and self.flow.winfo_manager():
            # Interruptor (y tamaño de letra) arriba y "☰ Filtros" debajo, así ninguno queda aplastado.
            self.flow.pack_forget()
            self.format_col.pack_configure(side="top", anchor="w", pady=(0, 6))
            self.compact_btn.pack(side="top", anchor="w")
        elif not compact and not self.flow.winfo_manager():
            self.compact_btn.pack_forget()
            self.format_col.pack_configure(side="left", anchor="n", pady=(6, 0))
            self.flow.pack(side="left", fill="x", expand=True)

    @staticmethod
    def _tri_summary(vars_, labels, prefix=""):
        return [(f"{prefix}{'☑' if v.get() == 1 else '☒'} {labels[k]}", lambda var=v: var.set(0))
                for k, v in vars_.items() if v.get()]

    def _checks(self, flow, title, items, cols):
        """Grupo de casillas de tres estados, ordenadas en `cols` columnas dentro de su panel."""
        vars_, labels = {}, dict(items)
        popup = self._group(flow, title, lambda: self._tri_summary(vars_, labels, f"{title}: "))
        for i, (key, text) in enumerate(items):
            check = TriCheck(popup, text, self.refresh, bg=PANEL)
            check.grid(row=1 + i // cols, column=i % cols, sticky="w", padx=(0, 10), pady=2)
            vars_[key] = check.var
        return vars_

    def _choice(self, flow, title, values, on_pick, default="Todas"):
        """Filtro de una sola opción (expansión, tribu, palabra clave): una lista; un clic elige y cierra."""
        var = tk.StringVar(value=default)
        popup = self._group(flow, title, lambda: [] if var.get() == default
                            else [(f"{title}: {var.get()}", lambda: var.set(default))])
        frame = tk.Frame(popup, bg=PANEL)
        frame.grid(row=1, column=0, sticky="nsew")
        box = tk.Listbox(frame, height=min(12, len(values)), width=min(48, max(len(v) for v in values) + 2),
                         bg=FIELD, fg=INK, font=F(*FONT), selectbackground=ACCENT, selectforeground="#ffffff",
                         highlightthickness=0, relief="flat", activestyle="none", exportselection=False,
                         selectmode="browse", cursor="hand2")
        for v in values:
            box.insert("end", v)
        box.pack(side="left", fill="both", expand=True)
        if len(values) > 12:
            sb = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
            box.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")

        def pick(event):
            if event.type == tk.EventType.ButtonRelease:
                if not 0 <= event.y <= box.winfo_height():
                    return  # soltó el mouse fuera de la lista
                i = box.nearest(event.y)  # la opción que está bajo el puntero
            else:  # Enter: la opción marcada con el teclado
                sel = box.curselection()
                if not sel:
                    return
                i = sel[-1]
            var.set(values[i])
            self._close_popup()
            on_pick()

        def on_open():  # marca la opción actual al abrir
            box.selection_clear(0, "end")
            if var.get() in values:
                i = values.index(var.get())
                box.selection_set(i)
                box.see(i)
        box.bind("<ButtonRelease-1>", pick)
        box.bind("<Return>", pick)
        popup.on_open = on_open
        return var

    def _toggle_popup(self, popup, btn):
        if self.open_popup is popup:
            self._close_popup()
            return
        self._close_popup()
        if hasattr(popup, "on_open"):
            popup.on_open()  # antes de medir: puede cambiar el ancho del panel
        popup.update_idletasks()
        x = btn.winfo_rootx() - self.winfo_rootx()
        y = btn.winfo_rooty() - self.winfo_rooty() + btn.winfo_height() + 4
        x = max(4, min(x, self.winfo_width() - popup.winfo_reqwidth() - 4))  # que no se salga por la derecha
        popup.place(x=x, y=y)
        popup.lift()
        self.open_popup, self.open_btn = popup, btn

    def _close_popup(self, _=None):
        if self.open_popup is not None:
            self.open_popup.place_forget()
        self.open_popup = self.open_btn = None

    def _click_outside(self, event):
        """Un clic fuera del panel abierto (y de su botón) lo cierra."""
        if self.open_popup is None:
            return
        path = str(event.widget)
        if path.startswith(str(self.open_popup)) or path.startswith(str(self.open_btn)):
            return
        self._close_popup()

    def _update_filter_summary(self):
        """Los botones con algo marcado se pintan (su texto no cambia, así no se mueven); al pasar el cursor
        muestran la lista de lo que filtran. Debajo, la fila de filtros activos con su ✕."""
        if not getattr(self, "filter_groups", None):
            return
        # El interruptor de formato también figura en la fila de activos cuando está en Rotación.
        actives = [("Rotación", lambda: self.format_var.set("Ilimitado"))] if self.format_var.get() == "Rotación" else []
        for title, btn, summary in self.filter_groups:
            items = summary()
            actives += items
            btn.config(style="Active.TButton" if items else "TButton")
            self.filter_tips[btn] = [text for text, _ in items]
        self.compact_btn.config(style="Active.TButton" if actives else "TButton")
        self.filter_tips[self.compact_btn] = [text for text, _ in actives]
        flow = self.active_flow
        for unit in flow.units:
            unit.destroy()
        flow.units = []
        if not actives:
            flow.pack_forget()
            return
        flow.add(tk.Label(flow, text="Activos:", bg=BG, fg=MUTED, font=F(*FONT)))
        for text, clear in actives:
            flow.add(self._active_chip(flow, text, clear))
        if not flow.winfo_manager():
            flow.pack(fill="x", pady=(0, 8), before=self.list_host)
        self.after_idle(lambda: flow._layout(max(1, flow.winfo_width())))

    def _active_chip(self, flow, text, clear):
        """Un filtro activo: lo incluido con ✔ verde, lo excluido con ✖ rojo, y aparte el ✕ gris
        que quita el filtro (así no se confunde con "excluir")."""
        chip = tk.Frame(flow, bg=FIELD, padx=8, pady=2, cursor="hand2")
        prefix, mark, value = text, None, ""
        for sym in ("☑", "☒"):
            if sym in text:
                prefix, value = (p.strip() for p in text.split(sym, 1))
                mark = sym
        if mark:
            color = TriCheck.MARKS[1 if mark == "☑" else 2][1]
            tk.Label(chip, text=prefix + " ", bg=FIELD, fg=INK, font=F(*FONT)).pack(side="left")
            tk.Label(chip, text="✔" if mark == "☑" else "✖", bg=FIELD, fg=color,
                     font=F("Segoe UI Symbol", 10, "bold")).pack(side="left")
            tk.Label(chip, text=" " + value, bg=FIELD, fg=color, font=F(*FONT)).pack(side="left")
        else:
            tk.Label(chip, text=text, bg=FIELD, fg=INK, font=F(*FONT)).pack(side="left")
        close = tk.Label(chip, text="✕", bg=FIELD, fg=MUTED, font=F(*FONT), padx=4)
        close.pack(side="left", padx=(10, 0))
        for w in (chip, *chip.winfo_children()):
            w.bind("<Button-1>", lambda _, c=clear: (c(), self.refresh()))
        close.bind("<Enter>", lambda e: (close.config(fg=INK, bg=LINE),
                                         self.tooltip.show("Quitar este filtro", e.x_root, e.y_root)))
        close.bind("<Leave>", lambda _: (close.config(fg=MUTED, bg=FIELD), self.tooltip.hide()))
        return chip

    def _filters(self):
        d = self.data
        # Barra principal (de lado a lado): búsqueda, contador y acciones.
        bar = ttk.Frame(self, padding=(12, 10, 12, 10))
        bar.pack(fill="x")
        # El buscador ocupa el ancho de la columna de la lista (termina en el divisor y lo sigue al moverlo);
        # sobre el detalle de la carta quedan el contador y los botones.
        self.search_box = ttk.Frame(bar)
        ttk.Label(self.search_box, text="Buscar", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh())
        entry = ttk.Entry(self.search_box, textvariable=self.search, width=12)
        # La búsqueda se hace sola al escribir; la lupa (o Enter) igual la ejecuta, como en cualquier buscador.
        search_now = lambda *_: (self.refresh(), entry.focus_set())
        ttk.Button(self.search_box, text="🔍", width=3, command=search_now).pack(side="right", padx=(4, 0))
        entry.pack(side="left", fill="x", expand=True)
        entry.focus_set()
        entry.bind("<Return>", search_now)
        self.entry_menu(entry)
        self.tokens = tk.BooleanVar()
        self.only_es = tk.BooleanVar()
        self.update_btn = ttk.Button(bar, text="⟳ Actualizar", command=self.ask_update)
        self.update_btn.pack(side="right", padx=(8, 0))
        self.update_btn.bind("<Enter>", lambda e: self.tooltip.show(
            "Hay novedades para actualizar:\n• " + "\n• ".join(self.pending) if self.pending
            else "Buscar y bajar cartas nuevas y versiones nuevas del programa",
            self.update_btn.winfo_rootx(), self.update_btn.winfo_rooty() + self.update_btn.winfo_height() - 12))
        self.update_btn.bind("<Leave>", lambda e: self.tooltip.hide())
        self._mark_update_button()
        ttk.Button(bar, text="? Glosario", command=self.toggle_glossary).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="🃏 Armar mazo", command=self.open_deck_builder).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Limpiar filtros", command=self.reset).pack(side="right")
        self.count = ttk.Label(bar, style="Muted.TLabel", text="000 cartas")
        self.count.pack(side="right", padx=(0, 14))
        import config
        ttk.Label(bar, style="Muted.TLabel", text=f"versión {config.VERSION}").pack(side="right", padx=(0, 14))
        self.search_box.update_idletasks()
        self.search_box.configure(height=self.search_box.winfo_reqheight(), width=600)
        self.search_box.pack_propagate(False)
        self.search_box.pack(side="left")

        # Debajo de la barra: columna izquierda (filtros + lista) y columna derecha (detalle de la carta),
        # así el detalle usa todo el alto en vez de dejar libre el espacio al costado de los filtros.
        self.pane = ttk.PanedWindow(self, orient="horizontal")
        self.left = ttk.Frame(self.pane)
        # (la barra y la columna empiezan en el mismo margen de 12 px, así el buscador termina justo en el divisor)
        self.left.bind("<Configure>", lambda e: self.search_box.configure(width=max(160, e.width)), add="+")
        # Fila de botones de filtro (cada uno abre su panel) y, debajo, la fila de filtros activos.
        self.filter_groups = []
        self.filter_popups = {}
        self.open_popup = self.open_btn = None
        # Renglón de filtros: a la izquierda el interruptor Ilimitado/Rotación (siempre visible) y al lado
        # los botones de filtro (o, con poco ancho, el botón único "☰ Filtros").
        self.filter_row = ttk.Frame(self.left)
        self.filter_row.pack(fill="x", pady=(0, 8))
        # Formato, como en la página oficial: Ilimitado = todas las expansiones; Rotación = solo las cartas
        # que la página marca como incluidas en la rotación.
        # Debajo del interruptor, el tamaño de letra de todo el programa.
        self.format_col = tk.Frame(self.filter_row, bg=BG)
        self.format_col.pack(side="left", anchor="n", padx=(0, 14), pady=(6, 0))
        self.format_switch = Switch(self.format_col, "Ilimitado", "Rotación", self.refresh)
        self.format_switch.pack(anchor="w")
        self.format_var = self.format_switch.var
        slider = SizeSlider(self.format_col, self.font_scale_var, self._font_scale_changed,
                            lambda: save_settings(tamaño_letra=self.font_scale_var.get()))
        slider.pack(anchor="w", pady=(10, 0))
        self.size_tip = lambda: self.tooltip.show(f"Tamaño de letra: {round(self.font_scale_var.get() * 100)} %",
                                                  slider.winfo_rootx(), slider.winfo_rooty() + slider.winfo_height() - 12)
        slider.canvas.bind("<Enter>", lambda _: self.size_tip(), add="+")
        slider.canvas.bind("<Leave>", lambda _: self.tooltip.hide(), add="+")
        flow = Flow(self.filter_row, padx=6, pady=6)
        flow.pack(side="left", fill="x", expand=True)
        self.compact_btn = ttk.Button(self.filter_row, text="☰ Filtros ▾", command=self._compact_menu)
        self.left.bind("<Configure>", self._fit_filters, add="+")
        self.active_flow = Flow(self.left, padx=6, pady=6)
        self.list_host = ttk.Frame(self.left)
        self.list_host.pack(fill="both", expand=True)
        self.bind_all("<Button-1>", self._click_outside, add="+")
        self.bind("<Escape>", self._close_popup, add="+")
        self.class_vars = self._checks(flow, "Clase", [(k, d.label("classes", k)) for k in sorted(d.lookup["classes"])], cols=4)
        self.cost_vars = self._checks(flow, "Costo", [(n, str(n)) for n in range(10)] + [(10, "10+")], cols=6)
        self.type_vars = self._checks(flow, "Tipo", [(k, d.label("types", k)) for k in sorted(d.lookup["types"])], cols=2)
        self.rarity_vars = self._checks(flow, "Rareza", [(k, d.label("rarities", k)) for k in sorted(d.lookup["rarities"])], cols=2)

        def options(table):
            opts = [("", "Todas")]
            for key, (en, es) in sorted(d.lookup[table].items(), key=lambda kv: (table == "tribes" and kv[1][0]) or kv[0]):
                if en and en != "-":
                    opts.append((key, f"{en} ({es})" if es and es != en else en))
            return dict((label, key) for key, label in opts)

        self.set_map = options("sets")
        # Cada tribu con su cantidad de cartas; varias solo existen en fichas (tokens).
        self.tribe_cards = {k: 0 for k in d.lookup["tribes"]}
        self.tribe_tokens = {k: 0 for k in d.lookup["tribes"]}
        for c in d.cards.values():
            for tr in c["tribes"]:
                (self.tribe_tokens if c["is_token"] else self.tribe_cards)[tr] = (
                    (self.tribe_tokens if c["is_token"] else self.tribe_cards).get(tr, 0) + 1)
        self.tribe_map = {"Todas": ""}
        for label, key in options("tribes").items():
            if not key:
                continue
            cards, tokens = self.tribe_cards.get(key, 0), self.tribe_tokens.get(key, 0)
            if not cards and not tokens:
                continue
            count = (f"{cards} carta" + ("s" if cards != 1 else "")) if cards else f"solo fichas ({tokens})"
            self.tribe_map[f"{label} · {count}"] = key
        self.kw_map = {"Todas": ""}
        self.kw_map.update({es: en for es, en in d.keyword_options})
        on_pick = lambda: self._tribe_tokens_if_needed() or self.refresh()
        self.set_var = self._choice(flow, "Expansión", list(self.set_map), on_pick)
        self.tribe_var = self._choice(flow, "Tribu", list(self.tribe_map), on_pick)
        self.kw_var = self._choice(flow, "Palabra clave", list(self.kw_map), on_pick)

        def stats_summary():
            out = []
            for stat, name in (("atk", "Ataque"), ("life", "Defensa")):
                lo, hi = self.stat_vars[(stat, "min")].get(), self.stat_vars[(stat, "max")].get()
                if lo or hi:
                    rng = f"{lo} a {hi}" if lo and hi else (f"≥ {lo}" if lo else f"≤ {hi}")
                    out.append((f"{name} {rng}", lambda s=stat: [self.stat_vars[(s, b)].set("") for b in ("min", "max")]))
            return out
        box = self._group(flow, "Ataque y defensa", stats_summary)
        ttk.Label(box, text="mín", style="PanelMuted.TLabel").grid(row=1, column=1)
        ttk.Label(box, text="máx", style="PanelMuted.TLabel").grid(row=1, column=3)
        self.stat_vars = {}
        for row, (stat, title) in enumerate((("atk", "Ataque"), ("life", "Defensa")), start=2):
            ttk.Label(box, text=title, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            for col, bound in ((1, "min"), (3, "max")):
                v = tk.StringVar()
                v.trace_add("write", lambda *_: self.refresh())
                ttk.Spinbox(box, from_=0, to=20, width=4, textvariable=v).grid(row=row, column=col, pady=2)
                self.stat_vars[(stat, bound)] = v
            ttk.Label(box, text="–", style="PanelMuted.TLabel").grid(row=row, column=2, padx=4)

        # Cartas que traen, crean, invocan o copian otras cartas durante la partida.
        self.gen_src_vars, self.gen_how_vars = {}, {}
        sources = [("any", "Cualquiera")] + list(card_generation.SOURCES.items())
        box = self._group(flow, "Trae o crea cartas", lambda: (
            self._tri_summary(self.gen_src_vars, dict(sources), "Desde ")
            + self._tri_summary(self.gen_how_vars, card_generation.MODES, "Cómo ")))
        src_label = ttk.Label(box, text="Desde", style="PanelMuted.TLabel")
        how_label = ttk.Label(box, text="Cómo", style="PanelMuted.TLabel")
        src_checks, how_checks = [], []
        # Este filtro solo marca o desmarca (sin la cruz de "todo menos esto").
        for key, text in sources:
            check = TriCheck(box, text, self.refresh, bg=PANEL, states=2)
            self.gen_src_vars[key] = check.var
            src_checks.append(check)
        for key, text in card_generation.MODES.items():
            check = TriCheck(box, text, self.refresh, bg=PANEL, states=2)
            self.gen_how_vars[key] = check.var
            how_checks.append(check)

        def regrid():  # 4 columnas si entra en la ventana; si no, 2
            cols = 4 if self.winfo_width() >= 640 else 2
            row = 1
            for label, checks in ((src_label, src_checks), (how_label, how_checks)):
                label.grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=1)
                for i, check in enumerate(checks):
                    check.grid(row=row + i // cols, column=1 + i % cols, sticky="w", padx=(0, 8), pady=1)
                row += (len(checks) + cols - 1) // cols
        regrid()
        box.on_open = regrid

        box = self._group(flow, "Mostrar", lambda: (
            ([("Incluye fichas", lambda: self.tokens.set(False))] if self.tokens.get() else [])
            + ([("Solo español oficial", lambda: self.only_es.set(False))] if self.only_es.get() else [])))
        ttk.Checkbutton(box, text="Incluir fichas (tokens)", variable=self.tokens, command=self.refresh,
                        style="Panel.TCheckbutton").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Checkbutton(box, text="Solo con español oficial", variable=self.only_es, command=self.refresh,
                        style="Panel.TCheckbutton").grid(row=2, column=0, sticky="w", pady=2)
        self.flow = flow
        # Todos los botones con el mismo ancho fijo (el del título más largo): marcar o desmarcar
        # filtros nunca los cambia de tamaño ni de lugar.
        width = max(len(title) for title, _, _ in self.filter_groups) + 2
        self.filter_tips = {}
        for _, btn, _ in self.filter_groups:
            btn.config(width=width)
        self.compact_btn.config(width=width)
        for btn in [b for _, b, _ in self.filter_groups] + [self.compact_btn]:
            btn.bind("<Enter>", lambda e, b=btn: self._show_filter_tip(b), add="+")
            btn.bind("<Leave>", lambda e: self.tooltip.hide(), add="+")

    def _show_filter_tip(self, btn):
        """Ventanita con lo que el filtro incluye (☑) o rechaza (☒)."""
        items = self.filter_tips.get(btn)
        if not items or self.open_popup is not None:
            return
        self.tooltip.show("Filtrando:\n" + "\n".join(f"  {t}" for t in items),
                          btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height() - 12)

    def reset(self):
        for group in (self.class_vars, self.cost_vars, self.type_vars, self.rarity_vars,
                      self.gen_src_vars, self.gen_how_vars):
            for v in group.values():
                v.set(0)
        for v in self.stat_vars.values():
            v.set("")
        self.tokens.set(False)
        self.only_es.set(False)
        self.set_var.set("Todas")
        self.tribe_var.set("Todas")
        self.kw_var.set("Todas")
        self.format_var.set("Ilimitado")
        self.search.set("")

    def _tribe_tokens_if_needed(self):
        """Si la tribu elegida solo existe en fichas, activa "Incluir fichas" para que no quede vacío."""
        tribe = self.tribe_map.get(self.tribe_var.get())
        if tribe and not self.tribe_cards.get(tribe) and not self.tokens.get():
            self.tokens.set(True)

    def toggle_keyword(self, en_key):
        """Clic en una palabra clave del efecto: la marca en su filtro, o la desmarca si ya estaba."""
        d = self.data
        if en_key in d.tribe_ids:
            tribe_id = d.tribe_ids[en_key]
            label = next(lbl for lbl, k in self.tribe_map.items() if k == tribe_id)
            self.tribe_var.set("Todas" if self.tribe_var.get() == label else label)
            self._tribe_tokens_if_needed()
        elif en_key in d.type_ids:
            var = self.type_vars[d.type_ids[en_key]]
            var.set(0 if var.get() == 1 else 1)
        else:
            label = next((es for es, en in self.kw_map.items() if en == en_key), None)
            if label is None:
                return
            self.kw_var.set("Todas" if self.kw_var.get() == label else label)
        self.refresh()

    # ---------- lista y detalle ----------
    def _body(self):
        pane = self.pane
        pane.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        left = self.list_host
        cols =(("name", "Nombre", 230), ("name_es", "Nombre en español", 210), ("cost", "Costo", 55),
                ("class", "Clase", 95), ("type", "Tipo", 110), ("rarity", "Rareza", 85),
                ("stats", "A/D", 55), ("set", "Expansión", 160))
        self.tree = ttk.Treeview(left, columns=[c[0] for c in cols], show="headings", selectmode="browse", height=3)
        for key, title, width in cols:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by(k))
            # Ancho mínimo: en ventanas angostas aparece la barra horizontal en vez de aplastar los nombres.
            self.tree.column(key, width=width, minwidth={"name": 170, "name_es": 150}.get(key, width),
                             anchor="center" if key in ("cost", "stats") else "w", stretch=key in ("name", "name_es"))
        # Con grid las barras conservan su lugar aunque la ventana sea chica.
        # Columna angosta a la izquierda del nombre con la flechita (▼ abre / ▲ cierra) que despliega el resumen de la carta.
        self.tree.configure(show="tree headings")
        self.tree.column("#0", width=30, minwidth=30, stretch=False, anchor="center")
        self.tree.heading("#0", text="")
        scale_columns(self.tree)
        self.tree.tag_configure("exp", background=FIELD)
        self.expanded = {}  # carta -> (ventana visible, contenido) de cada resumen abierto
        self.tree.bind("<Button-1>", self._arrow_click, add="+")
        self.tree.bind("<Configure>", lambda e: self._place_expansions(), add="+")
        vscroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        hscroll = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=lambda *a: (vscroll.set(*a), self._place_expansions()),
                            xscrollcommand=hscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.tag_configure("possible", foreground=MUTED)
        self.sort_key, self.sort_desc = None, False
        pane.add(self.left, weight=3)

        right = ttk.Frame(pane, style="Panel.TFrame", padding=12)
        nav = ttk.Frame(right, style="Panel.TFrame")
        nav.pack(fill="x")
        self.back_btn = ttk.Button(nav, text="← Volver", command=self.go_back, state="disabled")
        self.back_btn.pack(side="left")
        # Ancho fijo (el del texto más largo): al cambiar a "Ver normal" el botón no se achica.
        self.evo_btn = ttk.Button(nav, text="Ver evolucionada", command=self.toggle_evo, width=16)
        self.evo_btn.pack(side="right")
        # Voces: 🔊 reproduce la siguiente línea (normal o evolucionada según lo que se ve);
        # 🎙 abre el asistente para asociar la voz de la carta escuchándola en el juego.
        self.voice_map = voices.load_mapping() if voices else {}
        if voices:  # salida de audio siempre despierta: las voces suenan enteras apenas se aprieta 🔊
            self.audio_stop = threading.Event()
            threading.Thread(target=voices.keep_audio_awake, args=(self.audio_stop,), daemon=True).start()
        self.voice_pos = {}
        # Ancho fijo para que entre «🔊 10/11» (hasta 11 líneas por carta) sin que el botón cambie de tamaño.
        self.voice_btn = ttk.Button(nav, text="🔊", width=9, command=self.play_voice, state="disabled")
        self.voice_btn.pack(side="right", padx=(0, 6))
        self.assist_btn = ttk.Button(nav, text="🎙", width=3, command=self.open_voice_assistant)
        self.assist_btn.pack(side="right", padx=(0, 6))
        if not voices:
            self.assist_btn.config(state="disabled")
        for b, tip in ((self.voice_btn, "Escuchar la siguiente línea de voz"),
                       (self.assist_btn, "Asociar la voz de esta carta (asistente)")):
            b.bind("<Enter>", lambda e, t=tip, w=b: self.tooltip.show(t, w.winfo_rootx(), w.winfo_rooty() + w.winfo_height() - 12))
            b.bind("<Leave>", lambda e: self.tooltip.hide())
        # La imagen va dentro del texto (se crea en show()) para que todo el detalle se desplace junto.
        self.image = None
        self.text = tk.Text(right, bg=PANEL, fg=INK, font=F(*FONT), wrap="word", relief="flat", padx=4,
                            highlightthickness=0, cursor="xterm", width=40, height=3,
                            selectbackground=ACCENT, selectforeground="#ffffff", inactiveselectbackground=ACCENT,
                            insertwidth=0)
        tscroll = ttk.Scrollbar(right, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=tscroll.set)
        tscroll.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        t = self.text
        t.tag_configure("imgline", justify="center")
        t.tag_configure("title", font=F("Segoe UI Semibold", 15))
        t.tag_configure("sub", foreground=MUTED)
        t.tag_configure("chip", foreground=INK, background="#2a2833")
        t.tag_configure("h", font=F("Segoe UI Semibold", 9), foreground=MUTED, spacing1=10, spacing3=3)
        t.tag_configure("b", font=F("Segoe UI Semibold", 10))
        t.tag_configure("i", font=F("Segoe UI", 10, "italic"))
        t.tag_configure("bi", font=F("Segoe UI Semibold", 10, "italic"))
        t.tag_configure("kw", foreground=KW, background=KW_BG)
        t.tag_configure("tip", underline=True)
        t.tag_configure("link", foreground=LINK, underline=True)
        t.tag_configure("note", foreground=MUTED, font=F("Segoe UI", 9))
        t.tag_configure("hr", background=LINE, font=F("Segoe UI", 1), spacing1=7, spacing3=7)
        t.tag_configure("qa", lmargin1=10, lmargin2=10, spacing1=4)
        # Solo lectura: se puede seleccionar y copiar, pero no escribir ni borrar.
        t.bind("<Key>", self._readonly_key)
        t.bind("<<Paste>>", lambda _: "break")
        t.bind("<<Cut>>", lambda _: "break")
        t.bind("<Button-1>", lambda _: t.focus_set(), add="+")
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=INK, activebackground=ACCENT, activeforeground="#ffffff")
        menu.add_command(label="Copiar", command=self.copy_selection)
        menu.add_command(label="Seleccionar todo", command=lambda: t.tag_add("sel", "1.0", "end-1c"))
        t.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        self._trimming = False
        t.bind("<<Selection>>", self._trim_selection)
        self.empty_detail()
        pane.add(right, weight=2)
        self.pane = pane
        # Lista ~64 % y detalle de la carta el resto (el tamaño que eligió el usuario); si mueve el divisor,
        # se mantiene su proporción al cambiar el tamaño de la ventana.
        self.sash_ratio = 0.64
        pane.bind("<Configure>", self._keep_sash_visible)
        pane.bind("<ButtonRelease-1>", lambda _: setattr(
            self, "sash_ratio", self.pane.sashpos(0) / max(1, self.pane.winfo_width())), add="+")

    def _keep_sash_visible(self, event):
        """Ubica el divisor según la proporción, sin que la lista ni el detalle queden fuera de la vista."""
        width = event.width
        if width < 50:
            return
        low, high = min(180, width // 3), max(width - 380, width // 2)
        self.pane.sashpos(0, min(max(int(width * self.sash_ratio), low), high))

    # ---------- glosario ----------
    def _glossary_panel(self):
        """Panel lateral con el glosario oficial: buscador propio (español o inglés) y barra de desplazamiento."""
        panel = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        head = tk.Frame(panel, bg=PANEL)
        head.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(head, text="Glosario", bg=PANEL, fg=INK, font=F("Segoe UI Semibold", 13)).pack(side="left")
        close = tk.Label(head, text="✕", bg=PANEL, fg=MUTED, font=F("Segoe UI", 13), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda _: self.toggle_glossary(False))

        search_row = tk.Frame(panel, bg=PANEL)
        search_row.pack(fill="x", padx=14, pady=(0, 10))
        self.gloss_query = tk.StringVar()
        self.gloss_query.trace_add("write", lambda *_: self.render_glossary())
        self.gloss_entry = ttk.Entry(search_row, textvariable=self.gloss_query)
        self.gloss_entry.pack(side="left", fill="x", expand=True)
        self.entry_menu(self.gloss_entry)
        clear = tk.Label(search_row, text="×", bg=PANEL, fg=MUTED, font=F("Segoe UI", 13), cursor="hand2")
        clear.pack(side="left", padx=(6, 0))
        clear.bind("<Button-1>", lambda _: self.gloss_query.set(""))

        body = tk.Frame(panel, bg=PANEL)
        body.pack(fill="both", expand=True, padx=(14, 4), pady=(0, 12))
        text = tk.Text(body, bg=PANEL, fg=INK, font=F(*FONT), wrap="word", relief="flat", highlightthickness=0,
                       cursor="xterm", padx=2, width=10, height=3, insertwidth=0,
                       selectbackground=ACCENT, selectforeground="#ffffff", inactiveselectbackground=ACCENT)
        scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("gtitle", font=F("Segoe UI Semibold", 11), foreground=KW, spacing1=10)
        text.tag_configure("gen", font=F("Segoe UI", 9), foreground=MUTED)
        text.tag_configure("gtext", spacing1=3, spacing3=10, lmargin1=0, lmargin2=0)
        text.tag_configure("gnote", font=F("Segoe UI", 9, "italic"), foreground=MUTED)
        text.tag_configure("gempty", foreground=MUTED)
        # Solo lectura pero copiable, igual que el detalle de las cartas.
        text.bind("<Key>", lambda e: self._readonly_key(e, text))
        text.bind("<<Paste>>", lambda _: "break")
        text.bind("<<Cut>>", lambda _: "break")
        text.bind("<Button-1>", lambda _: text.focus_set(), add="+")
        text.bind("<<Selection>>", self._trim_selection)
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=INK, activebackground=ACCENT, activeforeground="#ffffff")
        menu.add_command(label="Copiar", command=lambda: self.copy_selection(text))
        menu.add_command(label="Seleccionar todo", command=lambda: text.tag_add("sel", "1.0", "end-1c"))
        text.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        self.gloss_panel, self.gloss_text = panel, text
        self.gloss_open = False
        self.bind("<Escape>", lambda _: self.toggle_glossary(False), add="+")
        self.bind("<Configure>", lambda e: self._place_glossary() if e.widget is self else None, add="+")
        self.render_glossary()

    def _place_glossary(self):
        if self.gloss_open:
            width = max(280, min(440, int(self.winfo_width() * 0.9)))
            self.gloss_panel.place(relx=1.0, rely=0, x=0, anchor="ne", width=width, relheight=1.0)
            self.gloss_panel.lift()

    def toggle_glossary(self, show=None):
        self.gloss_open = (not self.gloss_open) if show is None else show
        if self.gloss_open:
            self._place_glossary()
            self.gloss_entry.focus_set()
        else:
            self.gloss_panel.place_forget()

    @staticmethod
    def _fold(s):
        """Minúsculas y sin tildes, para que "aparicion" encuentre "Aparición"."""
        return "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(ch) != "Mn")

    def render_glossary(self):
        t = self.gloss_text
        t.delete("1.0", "end")
        query = self._fold(self.gloss_query.get()).strip()
        words = query.split()
        kw_es = {en.lower(): es for en, es in self.data.lookup["keywords"].values() if en and es}
        found = []
        for e in self.data.glossary:
            title = e["title_es"] or kw_es.get(e["title_en"].lower()) or e["title_en"]
            titles = [self._fold(title), self._fold(e["title_en"])]
            hay = self._fold(" ".join(filter(None, (title, e["title_en"], e["text_en"], e["text_es"]))))
            if not all(w in hay for w in words):
                continue
            # Primero el concepto que se llama así, después los que empiezan así, y al final los que solo lo
            # mencionan en la descripción (si no, "invocar" mostraba primero "Sello de Tierra").
            if not words:
                rank = 0
            elif query in titles:
                rank = 0
            elif any(t.startswith(query) for t in titles):
                rank = 1
            elif all(any(w in t for t in titles) for w in words):
                rank = 2
            else:
                rank = 3
            found.append((rank, title, e))
        found.sort(key=lambda f: f[0])  # el orden estable conserva el del glosario dentro de cada grupo
        shown = len(found)
        for _, title, e in found:
            t.insert("end", title, "gtitle")
            if title.lower() != e["title_en"].lower():
                t.insert("end", f"   {e['title_en']}", "gen")
            t.insert("end", "\n")
            body = re.sub(r"\n\s*\n+", "\n", (e["text_es"] or e["text_en"]).strip())
            t.insert("end", body + "\n", "gtext")
            if not e["text_es"]:
                t.insert("end", "Solo disponible en inglés por ahora.\n", "gnote")
        if not self.data.glossary:
            t.insert("end", "El glosario todavía no está descargado. Usá «⟳ Actualizar».", "gempty")
        elif not shown:
            t.insert("end", "No hay conceptos que coincidan con la búsqueda.", "gempty")
        t.yview_moveto(0)

    def _readonly_key(self, event, widget=None):
        widget = widget or self.text
        ctrl = event.state & 0x4
        if ctrl and event.keysym.lower() == "c":
            self.copy_selection(widget)
            return "break"
        if ctrl and event.keysym.lower() == "a":
            widget.tag_add("sel", "1.0", "end-1c")
            return "break"
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"):
            return None
        return "break"

    def _trim_selection(self, event=None):
        """Deja seleccionado solo el texto: saca espacios y renglones vacíos de los bordes y los saltos de línea."""
        if self._trimming:
            return
        t = event.widget if event is not None and isinstance(event.widget, tk.Text) else self.text
        ranges = t.tag_ranges("sel")
        if not ranges:
            return
        start, end = t.index(ranges[0]), t.index(ranges[-1])
        blank = lambda ch: ch == "" or ch.isspace()  # "" = línea separadora embebida
        while t.compare(start, "<", end) and blank(t.get(start)):
            start = t.index(f"{start}+1c")
        while t.compare(end, ">", start) and blank(t.get(f"{end}-1c")):
            end = t.index(f"{end}-1c")
        # Tramos que deberían quedar seleccionados: el texto, cortado en cada salto de línea
        # (un salto de línea seleccionado pinta hasta el borde del panel).
        wanted, pos = [], start
        while t.compare(pos, "<", end):
            nl = t.search("\n", pos, stopindex=end)
            stop = nl if nl and t.compare(nl, "<", end) else end
            if t.compare(pos, "<", stop):
                wanted += [pos, stop]
            if stop == end:
                break
            pos = t.index(f"{stop}+1c")
        current = [t.index(r) for r in ranges]
        if current == [t.index(w) for w in wanted]:
            return  # ya está recortada; no tocarla evita un ciclo de eventos <<Selection>>
        self._trimming = True
        try:
            t.tag_remove("sel", "1.0", "end")
            for a, b in zip(wanted[::2], wanted[1::2]):
                t.tag_add("sel", a, b)
        finally:
            self._trimming = False

    def entry_menu(self, entry):
        """Menú de clic derecho de un campo de texto (Pegar, Copiar, Cortar...), como en cualquier programa."""
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=INK, activebackground=ACCENT, activeforeground="#ffffff")
        menu.add_command(label="Pegar", command=lambda: entry.event_generate("<<Paste>>"))
        menu.add_command(label="Copiar", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Cortar", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_separator()
        menu.add_command(label="Seleccionar todo", command=lambda: entry.select_range(0, "end"))
        menu.add_command(label="Borrar", command=lambda: entry.delete(0, "end"))

        def show(e):
            entry.focus_set()
            menu.tk_popup(e.x_root, e.y_root)
        entry.bind("<Button-3>", show)

    def copy_selection(self, widget=None):
        try:
            selected = (widget or self.text).get("sel.first", "sel.last")
        except tk.TclError:
            return
        # Limpia el espaciado de la vista (espacios duros de las etiquetas, separaciones y renglones vacíos).
        lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in selected.splitlines()]
        cleaned = re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()
        if not cleaned:
            return
        self.clipboard_clear()
        self.clipboard_append(cleaned)

    def sort_by(self, key):
        self.sort_desc = not self.sort_desc if self.sort_key == key else False
        self.sort_key = key
        if self.creators_mode is not None:
            self.show_related_list(*self.creators_mode)  # ordenar no saca del modo especial
        else:
            self.refresh()

    def _num(self, stat, bound):
        try:
            return int(self.stat_vars[(stat, bound)].get())
        except ValueError:
            return None

    def matches(self, c):
        # Las fichas no van en mazos, así que el formato no las afecta.
        if self.format_var.get() == "Rotación" and not c["is_token"] and not c["in_rotation"]:
            return False
        if not self.tokens.get() and c["is_token"]:
            return False
        if self.only_es.get() and not c["has_es"]:
            return False
        for vars_, value in ((self.class_vars, c["class_id"]), (self.cost_vars, min(c["cost"] or 0, 10)),
                             (self.type_vars, c["type_id"]), (self.rarity_vars, c["rarity_id"])):
            chosen = {k for k, v in vars_.items() if v.get() == 1}    # visto: solo esto
            excluded = {k for k, v in vars_.items() if v.get() == 2}  # cruz: todo menos esto
            if (chosen and value not in chosen) or value in excluded:
                return False
        set_id = self.set_map.get(self.set_var.get())
        if set_id and c["set_id"] != set_id:
            return False
        tribe = self.tribe_map.get(self.tribe_var.get())
        if tribe and tribe not in c["tribes"]:
            return False
        keyword = self.kw_map.get(self.kw_var.get())
        if keyword and keyword not in c["kw"]:
            return False
        if not self._gen_matches(c["gen"]):
            return False
        for stat in ("atk", "life"):
            lo, hi = self._num(stat, "min"), self._num(stat, "max")
            if (lo is not None or hi is not None) and c["type_id"] != 1:
                return False
            if lo is not None and (c[stat] or 0) < lo:
                return False
            if hi is not None and (c[stat] or 0) > hi:
                return False
        words = self.search.get().lower().split()
        return all(w in c["haystack"] for w in words)

    def _gen_matches(self, pairs):
        """Filtro "Trae o crea cartas". ☑ = alguno de los marcados; ☒ = ninguno de esos.
        "Desde" y "Cómo" se cumplen en el mismo efecto (ej. Del mazo + Al azar)."""
        src_in = {k for k, v in self.gen_src_vars.items() if v.get() == 1}
        src_out = {k for k, v in self.gen_src_vars.items() if v.get() == 2}
        how_in = {k for k, v in self.gen_how_vars.items() if v.get() == 1}
        how_out = {k for k, v in self.gen_how_vars.items() if v.get() == 2}
        any_in = "any" in src_in
        src_in.discard("any")
        if "any" in src_out and pairs:
            return False  # ☒ Cualquiera: solo cartas que no traen ni crean nada
        if any(s in src_out or h in how_out for s, h in pairs):
            return False
        if any_in or src_in or how_in:
            return any((not src_in or s in src_in) and (not how_in or h in how_in) for s, h in pairs)
        return True

    def row(self, c):
        d = self.data
        return (c["name_en"], c["name_es"] or "", c["cost"], d.label("classes", c["class_id"]),
                d.label("types", c["type_id"]), d.label("rarities", c["rarity_id"]),
                f"{c['atk']}/{c['life']}" if c["type_id"] == 1 else "", d.lookup["sets"].get(c["set_id"], ("",))[0])

    def _sorted(self, cards):
        if self.sort_key:
            idx = ("name", "name_es", "cost", "class", "type", "rarity", "stats", "set").index(self.sort_key)
            numeric = self.sort_key in ("cost",)
            cards.sort(key=lambda c: (self.row(c)[idx] if numeric else str(self.row(c)[idx]).lower()), reverse=self.sort_desc)
        return cards

    def _fill(self, cards, possible=frozenset()):
        self.tree.delete(*self.tree.get_children())
        for c in cards:
            values = list(self.row(c))
            if c["card_id"] in possible:
                src = possible.get(c["card_id"]) if isinstance(possible, dict) else None
                where = {"mazo": " (de tu mazo)", "cementerio": " (de tu cementerio)"}.get(src, "")
                values[0] += f"   · posible{where}"
            self.tree.insert("", "end", iid=str(c["card_id"]), text="▼", values=values,
                             tags=("possible",) if c["card_id"] in possible else ())
        # Los resúmenes abiertos siguen abiertos si la carta sigue en la lista.
        for cid in list(self.expanded):
            if self.tree.exists(str(cid)):
                self._expand(cid)
            else:
                self._collapse(cid)
        if self.current and self.tree.exists(str(self.current)):
            self.tree.selection_set(str(self.current))
            self.tree.see(str(self.current))
        elif cards:
            self.tree.see(self.tree.get_children()[0])

    def refresh(self):
        """Lista normal según los filtros. Cualquier cambio de filtro sale del modo especial."""
        self.creators_mode = None
        cards = self._sorted([c for c in self.data.cards.values() if self.matches(c)])
        self._fill(cards)
        self.count.config(text=f"{len(cards)} cartas")
        self._sync_mode_buttons()
        self._update_filter_summary()

    def _sync_mode_buttons(self):
        """Los botones del detalle reflejan el modo actual (solo uno puede estar apretado)."""
        for kind, var in (("creators", self.creators_var), ("creations", self.creations_var)):
            if var is not None:
                var.set(self.creators_mode == (kind, self.current))

    def show_related_list(self, kind, card_id):
        """Reemplaza la lista, sin tocar los filtros, por:
        - "creators": las cartas que crean o podrían traer esta carta;
        - "creations": las cartas que esta carta crea o podría traer."""
        self.creators_mode = (kind, card_id)
        sure, possible = (self.data.creators_of if kind == "creators" else self.data.creations_of)(card_id)
        by_class = lambda c: (c["class_id"], c["cost"] or 0, c["card_id"])
        cards = [self.data.cards[i] for i in sure]
        extra = [self.data.cards[i] for i in possible]
        if self.sort_key:
            cards = self._sorted(cards + extra)
        else:  # primero las seguras/nombradas y después las posibles
            cards = sorted(cards, key=by_class) + sorted(extra, key=by_class)
        self._fill(cards, possible)
        if kind == "creators":
            self.count.config(text=f"{len(cards)} creadoras ({len(sure)} seguras, {len(possible)} posibles)")
        else:
            self.count.config(text=f"{len(cards)} que puede traer ({len(sure)} nombradas, {len(possible)} posibles)")
        self._sync_mode_buttons()

    def toggle_related_list(self, kind, card_id, on):
        if self._deck_shown():  # en el armador: la lista aparece en el lugar de las cartas disponibles
            self.creators_mode = (kind, card_id) if on else None
            self._sync_mode_buttons()
            self.deck_view.show_related(kind if on else None, card_id)
            return
        if on:
            self.show_related_list(kind, card_id)
        else:
            self.refresh()  # vuelve a la lista que había antes de apretar el botón

    def _on_select(self, _):
        sel = self.tree.selection()
        if sel and not sel[0].isdigit():
            # Fila de un resumen desplegado: no se selecciona; con las flechas del teclado se salta a la carta
            # siguiente (bajando desde la carta) o a la carta del resumen (subiendo).
            owner = sel[0][3:].split("_")[0]
            target = owner
            if self.current == int(owner):
                nxt = self.tree.next(f"exp{owner}_{self._exp_rows(int(owner)) - 1}")
                target = nxt or owner
            self.tree.selection_set(target)
            self.tree.see(target)
            return
        if sel and int(sel[0]) != self.current:
            self.show(int(sel[0]), from_list=True)

    # ---------- resumen desplegable dentro de la lista ----------
    EXP_MIN_ROWS = 6  # alto mínimo del resumen (lo que ocupa la carta chiquita), en filas de la lista
    THUMB_SPACE = 10 + 106 + 12 + 16  # márgenes + ancho de la carta chiquita, a la izquierda del texto

    def _exp_rows(self, cid):
        return self.expanded[cid]["rows"] if cid in self.expanded else 0

    def _arrow_click(self, event):
        """Clic en la flechita (columna de la izquierda): abre o cierra el resumen de esa carta."""
        if self.tree.identify_region(event.x, event.y) != "tree" or self.tree.identify_column(event.x) != "#0":
            return None
        row = self.tree.identify_row(event.y)
        if not row.isdigit():
            return None
        cid = int(row)
        if cid in self.expanded:
            self._collapse(cid)
        else:
            self._expand(cid)
        return "break"  # abrir el resumen no cambia la carta seleccionada

    def _expand(self, cid):
        if cid not in self.expanded:
            self.expanded[cid] = self._summary_widget(self.data.cards[cid])
        self.tree.item(str(cid), text="▲")
        self._fit_expansion(cid, force=True)
        self.after_idle(self._place_expansions)

    def _collapse(self, cid):
        for i in range(self._exp_rows(cid)):
            if self.tree.exists(f"exp{cid}_{i}"):
                self.tree.delete(f"exp{cid}_{i}")
        if self.tree.exists(str(cid)):
            self.tree.item(str(cid), text="▼")
        info = self.expanded.pop(cid, None)
        if info:
            info["view"].destroy()
        self.after_idle(self._place_expansions)

    def _fit_expansion(self, cid, force=False):
        """Ajusta el alto del resumen al texto (según el ancho de la lista): tantas filas vacías como haga falta."""
        info = self.expanded[cid]
        wrap = max(160, self.tree.winfo_width() - self.THUMB_SPACE)
        rows_now = sum(1 for i in range(info["rows"] + 1) if self.tree.exists(f"exp{cid}_{i}"))
        if not force and wrap == info["wrap"] and rows_now == info["rows"]:
            return
        info["wrap"] = wrap
        info["effect"].config(wraplength=wrap)
        info["effect"].update_idletasks()
        rh = self._row_height()
        need = info["effect"].winfo_reqheight() + info["basics"].winfo_reqheight() + 22
        rows = max(self.EXP_MIN_ROWS, -(-need // rh))
        for i in range(rows_now - 1, rows - 1, -1):  # sobran filas
            self.tree.delete(f"exp{cid}_{i}")
        idx = self.tree.index(str(cid))
        for i in range(rows_now, rows):  # faltan filas
            self.tree.insert("", idx + 1 + i, iid=f"exp{cid}_{i}", values=(), tags=("exp",))
        info["rows"] = rows

    def _summary_widget(self, c):
        """El recuadro: la carta chiquita, sus datos básicos y todo su efecto (con evolución, blasón, fe...)."""
        view = tk.Frame(self.tree, bg=FIELD, highlightthickness=0)
        content = tk.Frame(view, bg=FIELD)
        img = self._thumbnail(c)
        tk.Label(content, image=img, text="" if img else "(sin imagen)", bg=FIELD, fg=MUTED,
                 font=F(*FONT)).pack(side="left", anchor="n", padx=(10, 12), pady=3)
        info = tk.Frame(content, bg=FIELD)
        info.pack(side="left", fill="both", expand=True, pady=6)
        _, _, cost, cls, kind, rarity, stats, _ = self.row(c)
        basics = tk.Label(info, text=" · ".join(str(x) for x in (f"Costo {cost}", stats, cls, kind, rarity) if x),
                          bg=FIELD, fg=KW, font=F("Segoe UI Semibold", 10), anchor="w")
        basics.pack(fill="x")
        effect = tk.Label(info, text=self._full_effect(c), bg=FIELD, fg=INK, font=F(*FONT), anchor="nw", justify="left",
                          wraplength=400)
        effect.pack(fill="both", expand=True, pady=(4, 0))
        # La ruedita del mouse sobre el recuadro sigue desplazando la lista.
        wheel = lambda e: (self.tree.yview_scroll(int(-e.delta / 120), "units"), "break")[1]
        for w in (view, content, info, *content.winfo_children(), *info.winfo_children()):
            w.bind("<MouseWheel>", wheel)
        return {"view": view, "content": content, "effect": effect, "basics": basics, "rows": 0, "wrap": None}

    def _full_effect(self, c):
        """Todo lo que hace la carta, como en el detalle: su efecto (con evolución y superevolución) y sus
        efectos especiales (blasón, fe, cristalizar, acelerar). Texto oficial, si no la traducción propia."""
        def plain(text):
            lines = re.sub(r"<[^>]+>", "", re.sub(r"<hr>", "\n", text or "")).splitlines()
            return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in lines if ln.strip())
        parts = [plain(c["skill_es"] or c.get("skill_tr") or c["skill_en"])]
        for e in c["specific"]:
            title = self.data.effect_title(e["key"])
            if e["key"] in ("crystal", "accelerate"):
                title += f" · COSTO {e['cost']}"
            body = plain(e.get("es") or e.get("tr") or e.get("en"))
            if body:
                parts.append(f"{title}\n{body}")
        return "\n\n".join(p for p in parts if p) or "(sin efecto)"

    def _thumbnail(self, c):
        for lang, folder in (("es", "es419"), ("en", "eng")):
            h = c[f"img_{lang}"]
            path = IMAGES / folder / f"{h}.png" if h else None
            if path is not None and path.exists():
                key = (path, 5)
                if key not in self.images:
                    try:
                        self.images[key] = tk.PhotoImage(file=str(path)).subsample(5)  # ~106 x 137
                    except tk.TclError:
                        continue
                return self.images[key]
        return None

    def _row_height(self):
        return int(ttk.Style().lookup("Treeview", "rowheight") or 24)

    def _place_expansions(self):
        """Ubica cada recuadro sobre sus filas vacías; si se ve solo en parte, se muestra solo esa parte."""
        if not getattr(self, "expanded", None):
            return
        tree = self.tree
        for cid in list(self.expanded):  # si cambió el ancho de la lista, el texto ocupa otro alto
            if tree.exists(str(cid)):
                self._fit_expansion(cid)
        rh = self._row_height()
        # Fin de los títulos de las columnas = donde empieza la primera fila visible. (Con la lista desplazada,
        # identify_row sobre los títulos devuelve filas que ya no se ven: se toma la primera con posición real.)
        head = 0
        for y in range(0, 100):
            row = tree.identify_row(y)
            box = tree.bbox(row) if row else ""
            if box:
                head = box[1]
                break
        height, width = tree.winfo_height(), tree.winfo_width()
        for cid, info in self.expanded.items():
            view, content, rows = info["view"], info["content"], info["rows"]
            total = rows * rh
            top = None
            box = tree.bbox(str(cid)) if tree.exists(str(cid)) else ""
            if box:
                top = box[1] + box[3]
            else:
                for i in range(rows):
                    b = tree.bbox(f"exp{cid}_{i}") if tree.exists(f"exp{cid}_{i}") else ""
                    if b:
                        top = b[1] - i * rh
                        break
            if top is None:
                view.place_forget()
                continue
            vis_top, vis_bottom = max(top, head), min(top + total, height)
            if vis_bottom <= vis_top:
                view.place_forget()
                continue
            view.place(x=1, y=vis_top, width=max(1, width - 2), height=vis_bottom - vis_top)
            content.place(x=0, y=top - vis_top, relwidth=1, height=total)

    # ---------- detalle ----------
    def load_image(self, card, evo):
        tries = []
        for lang, folder in (("es", "es419"), ("en", "eng")):
            h = card[f"evo_img_{lang}" if evo else f"img_{lang}"]
            if h:
                tries.append(IMAGES / folder / f"{h}.png")
        # Con el panel angosto la imagen se achica más para que entre (530 px de ancho original).
        width = self.text.winfo_width()
        factor = 3 if 1 < width < 300 else 2
        for path in tries:
            if (path, factor) in self.images:
                return self.images[(path, factor)]
            if path.exists():
                try:
                    img = tk.PhotoImage(file=str(path)).subsample(factor)
                except tk.TclError:
                    continue
                self.images[(path, factor)] = img
                return img
        return None

    def open_zoom(self, card_id=None, evo=None):
        """Visor de una carta (por defecto la que se ve, normal o evolucionada): la ilustración sin marco si
        está bajada, si no la imagen oficial."""
        card_id = self.current if card_id is None else card_id
        evo = self.show_evo if evo is None else evo
        if card_id is None:
            return
        art = ART / f"{card_id + (1 if evo else 0)}.png"
        if art.exists():
            ImageZoom(self, art)
            return
        c = self.data.cards[card_id]
        for lang, folder in (("es", "es419"), ("en", "eng")):
            h = c[f"evo_img_{lang}" if evo else f"img_{lang}"]
            path = IMAGES / folder / f"{h}.png" if h else None
            if path is not None and path.exists():
                ImageZoom(self, path)
                return

    def update_image(self):
        c = self.data.cards[self.current]
        has_evo = bool(c["evo_img_en"] or c["evo_img_es"])
        self.evo_btn.config(state="normal" if has_evo else "disabled",
                            text="Ver normal" if self.show_evo else "Ver evolucionada")
        self._update_voice_button()
        if self.image is None:
            return
        img = self.load_image(c, self.show_evo)
        if img:
            self.image.config(image=img, text="")
        else:
            self.image.config(image="", text="(imagen todavía no descargada)")

    def toggle_evo(self):
        self.show_evo = not self.show_evo
        self.voice_pos.clear()  # al evolucionar (o volver a normal) las voces arrancan de la línea 1
        self.update_image()

    # ---------- voces ----------
    def _voice_lines(self):
        """Líneas de voz de la carta actual para lo que se está viendo (normal o evolucionada)."""
        entry = self.voice_map.get(self.current) if self.current else None
        if not entry:
            return []
        return entry["evo" if self.show_evo else "normal"]

    def _update_voice_button(self):
        lines = self._voice_lines()
        # Con la cuenta de líneas: «🔊 1/3» = sonó la primera de tres (0 = todavía ninguna).
        heard = self.voice_pos.get((self.current, self.show_evo), 0)
        self.voice_btn.config(state="normal" if lines else "disabled",
                              text=f"🔊 {heard}/{len(lines)}" if lines else "🔊")
        # 🎙 solo con una carta seleccionada que tenga audio en el juego (y si las voces están disponibles).
        card = self.data.cards.get(self.current) if self.current is not None else None
        self.assist_btn.config(state="normal" if voices and card and self.card_has_audio(card) else "disabled")

    @staticmethod
    def card_has_audio(card):
        """¿La carta tiene audio en el juego? Los combatientes siempre pueden tenerlo (las criaturas que no
        hablan igual rugen o gruñen, sin actor acreditado); hechizos y amuletos solo si tienen voz acreditada."""
        return card["type_id"] == 1 or bool((card.get("cv") or "").strip())

    def play_voice(self):
        """Reproduce la siguiente línea; al llegar a la última vuelve a empezar."""
        lines = self._voice_lines()
        if not lines:
            return
        key = (self.current, self.show_evo)
        i = self.voice_pos.get(key, 0) % len(lines)
        self.voice_pos[key] = i + 1
        # puede venir de otro paquete o ser una grabación propia
        path = voices.line_path(lines[i], self.voice_map[self.current]["bank"])
        voices.play(path)  # con un silencio adelante si el audio estuvo quieto (auriculares Bluetooth)
        self._update_voice_button()

    def open_voice_assistant(self):
        if self.current is None:
            return
        VoiceAssistant(self, self.current)

    def _mark_update_button(self):
        """Con novedades sin actualizar, el botón se ve violeta y con un punto."""
        self.update_btn.config(text="⟳ Actualizar ●" if self.pending else "⟳ Actualizar",
                               style="Active.TButton" if self.pending else "TButton")

    def ask_update(self):
        """«Actualizar»: si al abrir había novedades, primero pregunta (y dice cuáles son)."""
        if self.pending and not messagebox.askyesno(
                "Actualizar", "Hay novedades para actualizar:\n\n• " + "\n• ".join(self.pending) +
                "\n\n¿Actualizar ahora a la versión más reciente? Tus mazos, voces, imágenes y ajustes se conservan.",
                parent=self):
            return
        self.open_update()

    def open_update(self, first_time=False):
        if self.update_win is not None and self.update_win.winfo_exists():
            self.update_win.lift()
            return
        self.update_win = UpdateWindow(self, first_time)

    def open_deck_builder(self):
        """El armador de mazos ocupa el lugar de los filtros y la lista de cartas (el botón lo abre y lo cierra)."""
        if self._deck_shown():
            return self.close_deck_builder()
        first = self.deck_view is None
        if first:
            self.deck_view = DeckBuilder(self)
        self._close_popup()
        self._swap_left(self.left, self.deck_view)
        self.search_box.pack_forget()  # el buscador de arriba es de la lista; el armador tiene el suyo
        if first:  # lista de cartas del armador más ancha que la del mazo
            inner = self.deck_view.inner
            self.after(50, lambda: inner.sashpos(0, int(inner.winfo_width() * 0.58)))

    def _deck_shown(self):
        return self.deck_view is not None and str(self.deck_view) in [str(p) for p in self.pane.panes()]

    def close_deck_builder(self):
        if not self._deck_shown():
            return
        if self.deck_view.related:  # la lista del armador vuelve a todas las cartas
            self.deck_view.show_related(None)
        self._swap_left(self.deck_view, self.left)
        self.search_box.pack(side="left")

    def _swap_left(self, old, new):
        """Cambia lo que se ve a la izquierda del divisor, sin moverlo."""
        pos = self.pane.sashpos(0)
        self.pane.forget(old)
        self.pane.insert(0, new, weight=3)
        self.update_idletasks()
        self.pane.sashpos(0, pos)

    def go_back(self):
        if self.history:
            self.show(self.history.pop(), remember=False)

    def empty_detail(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.image = None
        self.text.insert("end", "Elegí una carta de la lista para ver su detalle.", "sub")
        self.evo_btn.config(state="disabled")
        # Sin carta seleccionada no hay nada que escuchar ni a qué asociarle una voz.
        self.voice_btn.config(state="disabled", text="🔊")
        self.assist_btn.config(state="disabled")

    def show(self, card_id, remember=True, from_list=False):
        if remember and self.current and self.current != card_id:
            self.history.append(self.current)
        self.current = card_id
        self.show_evo = False
        self.voice_pos.clear()  # al abrir una carta (otra o la misma de nuevo) las voces arrancan de la línea 1
        self.back_btn.config(state="normal" if self.history else "disabled")
        # Con "Ver creadoras" activo, elegir una de esas cartas en la lista mantiene la lista;
        # llegar a otra carta por otro camino (enlace, Volver) la devuelve a como estaba.
        if self.creators_mode is not None and not (from_list and self.tree.exists(str(card_id))):
            self.refresh()
        if self.tree.exists(str(card_id)) and self.tree.selection() != (str(card_id),):
            self.tree.selection_set(str(card_id))
            self.tree.see(str(card_id))

        d, c, t = self.data, self.data.cards[card_id], self.text
        self.tooltip.hide()
        t.config(state="normal")
        t.delete("1.0", "end")
        for tag in t.tag_names():
            if tag.startswith(("kwtag_", "link_", "chiptag_")):
                t.tag_delete(tag)
        self.n_tags = 0

        # Con la lupa: un clic abre la imagen en grande (normal o evolucionada, según lo que se ve).
        self.image = tk.Label(t, bg=PANEL, fg=MUTED, font=F(*FONT), cursor=cursor("lupa", "hand2"))
        self.image.bind("<Button-1>", lambda _: self.open_zoom())
        t.window_create("end", window=self.image, pady=4)
        t.insert("end", "\n")
        t.tag_add("imgline", "1.0", "1.end")
        self.update_image()
        t.insert("end", c["name_en"] + "\n", "title")
        origin = ("texto oficial en español" if c["has_es"] else
                  "traducción propia" if c.get("skill_tr") else "solo en inglés por ahora")
        sub = (c["name_es"] + " · " if c["name_es"] else "") + origin
        t.insert("end", sub + "\n\n", "sub")
        # Cada etiqueta, con el filtro que marca o desmarca al hacerle clic.
        chips = [(f"Costo {c['cost']}", ("cost", min(c["cost"] or 0, 10)))]
        if c["type_id"] == 1:
            chips.append((f"{c['atk']}/{c['life']}", ("stats", (c["atk"], c["life"]))))
        chips += [(d.label("classes", c["class_id"]), ("class", c["class_id"])),
                  (d.label("types", c["type_id"]), ("type", c["type_id"])),
                  (d.label("rarities", c["rarity_id"]), ("rarity", c["rarity_id"])),
                  (d.lookup["sets"].get(c["set_id"], ("",))[0], ("set", c["set_id"]))]
        chips += [(d.label("tribes", tr), ("tribe", tr)) for tr in c["tribes"] if d.label("tribes", tr) not in ("-", "—")]
        if c["is_token"]:
            chips.append(("Ficha (token)", ("token", True)))
        for chip, (kind, value) in chips:
            self.n_tags += 1
            tag = f"chiptag_{self.n_tags}"
            # Espacios duros para que una etiqueta no se corte entre dos renglones.
            t.insert("end", f" {chip} ".replace(" ", " "), ("chip", tag))
            t.tag_bind(tag, "<Enter>", lambda _: t.config(cursor="hand2"))
            t.tag_bind(tag, "<Leave>", lambda _: t.config(cursor="xterm"))
            t.tag_bind(tag, "<ButtonRelease-1>", lambda _, k=kind, v=value: self._chip_click(k, v))
            t.insert("end", "  ")
        t.insert("end", "\n")

        # Botones que quedan apretados: en la lista, quién puede traer esta carta / qué puede traer esta carta.
        self.creators_var = self.creations_var = None
        buttons = []
        for kind, label, finder in (("creators", "⤴ Ver creadoras", d.creators_of),
                                    ("creations", "⤵ Ver lo que trae", d.creations_of)):
            sure, possible = finder(card_id)
            if not (sure or possible):
                continue
            var = tk.BooleanVar(value=self.creators_mode == (kind, card_id))
            if kind == "creators":
                self.creators_var = var
            else:
                self.creations_var = var
            buttons.append(ttk.Checkbutton(
                t, text=f"{label} ({len(sure) + len(possible)})", style="Creators.Toolbutton", variable=var,
                cursor="hand2", command=lambda k=kind, v=var: self.toggle_related_list(k, card_id, v.get())))
        if buttons:
            t.insert("end", "\n")
            for b in buttons:
                t.window_create("end", window=b, pady=2, padx=(0))
                t.insert("end", "  ")
            t.insert("end", "\n")

        en_only = self.section("EFECTO", c["skill_en"], c["skill_es"], c.get("skill_tr"))
        for e in c["specific"]:
            title = self.data.effect_title(e["key"])
            if e["key"] in ("crystal", "accelerate"):
                title += f" · COSTO {e['cost']}"
            en_only |= self.section(title, e.get("en"), e.get("es"), e.get("tr"))
        if en_only:
            t.insert("end", "\nTexto en inglés con las palabras clave en español. Pasá el mouse sobre ellas "
                            "para ver el término original.\n", "note")

        # "Crea" = lo que su propio efecto crea; el resto de la lista oficial son cartas relacionadas
        # (en cadena o mencionadas), que esta carta no crea.
        made_by = d.made_by.get(card_id, set())
        groups = (("CARTAS QUE CREA", sorted(c["creates"])),
                  ("OTRAS CARTAS RELACIONADAS (no las crea esta carta)", sorted(set(c["related"]) - c["creates"])),
                  ("CARTAS QUE LA CREAN", sorted(made_by)),
                  ("OTRAS CARTAS QUE LA MENCIONAN", sorted(set(c["related_by"]) - made_by)))
        for title, ids in groups:
            if ids:
                t.insert("end", "\n" + title + "\n", "h")
                for rid in ids:
                    r = d.cards[rid]
                    t.insert("end", "• ")
                    self.link(r["name_en"], rid)
                    extra = f"  ({r['name_es']})" if r["name_es"] else ""
                    extra += "  · esta misma carta" if rid == card_id else ""
                    t.insert("end", extra + ("  · ficha" if r["is_token"] else "") + "\n", "note")

        # Oficial en español; si no hay, la traducción propia (tools/translate_lore.py); si tampoco, el inglés.
        langs = {q[0] for q in c["qa"]}
        qa_lang = next(lang for lang in ("es", "tr", "en") if lang in langs or lang == "en")
        qa = [q for q in c["qa"] if q[0] == qa_lang]
        if qa:
            t.insert("end", "\nPREGUNTAS OFICIALES\n", "h")
            for _, q, a in qa:
                t.insert("end", q + "\n", ("b", "qa"))
                t.insert("end", a + "\n", "qa")

        self.section("AMBIENTACIÓN", c["flavour_en"], c["flavour_es"], c.get("flavour_tr"))
        if c["type_id"] == 1:
            self.section("AMBIENTACIÓN EVOLUCIONADA", c["evo_flavour_en"], c["evo_flavour_es"],
                          c.get("evo_flavour_tr"))
        t.insert("end", f"\n\nIlustración: {c['illustrator'] or '—'} · Voz: {c['cv'] or '—'} · ID {c['card_id']}\n", "note")
        t.yview_moveto(0)

    def section(self, title, en, es, tr=None):
        """Texto oficial en español; si no hay, la traducción propia; si tampoco, el inglés."""
        if not en and not es:
            return False
        self.text.insert("end", "\n" + title + "\n", "h")
        self.markup(es or tr or en, "es" if es else "tr" if tr else "en")
        self.text.insert("end", "\n")
        return not (es or tr)

    def link(self, text, card_id, extra_tags=(), t=None, go=None):
        """Nombre de carta con enlace. t / go: otro cuadro de texto y qué hacer al hacer clic (el detalle de la
        vista del mazo); por defecto, el detalle de la ventana principal."""
        t, go = t or self.text, go or self.show
        self.n_tags = getattr(self, "n_tags", 0) + 1
        tag = f"link_{self.n_tags}"
        t.insert("end", text, ("link", tag) + tuple(extra_tags))
        t.tag_bind(tag, "<Button-1>", lambda _: go(card_id))
        t.tag_bind(tag, "<Enter>", lambda _: t.config(cursor="hand2"))
        t.tag_bind(tag, "<Leave>", lambda _: t.config(cursor="xterm"))

    def keyword(self, text, en_key, styles, original=None, t=None):
        """Palabra clave resaltada; con clic se marca o desmarca en el filtro (solo en el detalle principal)."""
        t = t or self.text
        self.n_tags = getattr(self, "n_tags", 0) + 1
        tag = f"kwtag_{self.n_tags}"
        t.insert("end", text, ("kw", tag) + (("tip",) if original else ()) + tuple(styles))
        # Al pasar el mouse: el significado según el glosario (y, si el texto estaba en inglés, el término original).
        meaning = self.data.definition(en_key) if en_key else None
        tip = "\n".join(filter(None, [f"{meaning[0]}: {meaning[1]}" if meaning else None,
                                      f"(Original: {original})" if original else None]))
        if tip:
            t.tag_bind(tag, "<Enter>", lambda e: self.tooltip.show(tip, e.x_root, e.y_root, wrap=340), add="+")
            t.tag_bind(tag, "<Leave>", lambda _: self.tooltip.hide(), add="+")
        if en_key and t is self.text:
            t.tag_bind(tag, "<Enter>", lambda _: t.config(cursor="hand2"), add="+")
            t.tag_bind(tag, "<Leave>", lambda _: t.config(cursor="xterm"), add="+")
            t.tag_bind(tag, "<ButtonRelease-1>", lambda _: self._keyword_click(en_key))

    def _chip_click(self, kind, value):
        if self.text.tag_ranges("sel"):
            return  # fue para seleccionar texto, no un clic
        self.toggle_filter(kind, value)

    def toggle_filter(self, kind, value):
        """Clic en un dato de la carta (costo, A/V, clase, tipo...): lo marca en su filtro, o lo desmarca."""
        groups = {"cost": self.cost_vars, "class": self.class_vars, "type": self.type_vars, "rarity": self.rarity_vars}
        if kind in groups:
            var = groups[kind][value]
            var.set(0 if var.get() == 1 else 1)
        elif kind == "stats":
            atk, life = (str(x) for x in value)
            fields = [("atk", "min"), ("atk", "max"), ("life", "min"), ("life", "max")]
            same = [self.stat_vars[f].get() for f in fields] == [atk, atk, life, life]
            for f, v in zip(fields, [atk, atk, life, life]):
                self.stat_vars[f].set("" if same else v)
        elif kind == "set":
            label = next(lbl for lbl, k in self.set_map.items() if k == value)
            self.set_var.set("Todas" if self.set_var.get() == label else label)
        elif kind == "tribe":
            label = next(lbl for lbl, k in self.tribe_map.items() if k == value)
            self.tribe_var.set("Todas" if self.tribe_var.get() == label else label)
            self._tribe_tokens_if_needed()
        elif kind == "token":
            self.tokens.set(not self.tokens.get())
        self.refresh()

    def _keyword_click(self, en_key):
        # Si el clic fue para seleccionar texto (arrastrando), no se toca el filtro.
        if self.text.tag_ranges("sel"):
            return
        self.toggle_keyword(en_key)

    def markup(self, source, lang, t=None, go=None):
        """Inserta texto con el marcado del juego (<color=Keyword>, <b>, <i>, <hr>).
        lang: "en" (inglés), "es" (oficial en español) o "tr" (traducción propia).
        t / go: otro cuadro de texto y adónde llevan sus enlaces (ver link)."""
        t, bold, italic, in_kw, kw_parts = t or self.text, False, False, False, []
        translated_prev = False  # para descartar terminaciones sueltas como la "d" de "Fuse"+"d"

        def style():
            return ("bi",) if bold and italic else ("b",) if bold else ("i",) if italic else ()

        # Los saltos de línea pegados a <hr> dejaban renglones vacíos entre el estado normal y el evolucionado.
        source = re.sub(r"\s*<hr>\s*", "<hr>", source.replace("\r", ""))
        for part in MARKUP.split(source):
            if not part:
                continue
            if part == "<color=Keyword>":
                in_kw, kw_parts = True, []
            elif part == "</color>":
                in_kw = False
                word = "".join(kw_parts)
                key = word.strip().lower()
                # En la traducción propia los nombres de cartas siguen en inglés.
                names = self.data.by_name_en if lang in ("en", "tr") else self.data.by_name_es
                target = names.get(key)
                es = self.data.kw_es.get(key) if lang == "en" else None
                en_key = key if lang == "en" else self.data.kw_en_by_es.get(key)
                if translated_prev and len(key) <= 2 and key.isalpha():
                    pass  # terminación inglesa pegada a una palabra ya traducida
                elif target:
                    self.link(word, target["card_id"], style(), t=t, go=go)
                elif es:
                    # En las cartas en inglés la palabra clave se muestra en español; el original, al pasar el mouse.
                    self.keyword(es, en_key, style(), original=word.strip(), t=t)
                else:
                    self.keyword(word, en_key if en_key in self.data.kw_es else None, style(), t=t)
                translated_prev = bool(es) and not target
            elif part in ("<b>", "</b>"):
                bold = part == "<b>"
            elif part in ("<i>", "</i>"):
                italic = part == "<i>"
            elif part == "<hr>":
                # Línea fina de un píxel, del ancho del panel, entre el estado normal y el evolucionado.
                t.insert("end", "\n")
                line = tk.Frame(t, height=1, width=max(60, t.winfo_width() - 16), bg=LINE)
                t.window_create("end", window=line, pady=7)
                t.insert("end", "\n")
            elif part.startswith("<") and part.endswith(">"):
                continue
            elif in_kw:
                kw_parts.append(part)
            else:
                t.insert("end", part, style())


def log_errors():
    """Sin consola (el .exe o el .pyw), los errores se anotan en errores.log, para poder mandarlos si algo falla."""
    if sys.stderr is None or not sys.stderr.isatty():
        try:
            sys.stderr = open(ROOT / "errores.log", "a", encoding="utf-8", buffering=1)
        except OSError:
            return
    tk.Tk.report_callback_exception = lambda self, *exc: __import__("traceback").print_exception(*exc)


def main():
    log_errors()
    # Identificador propio para Windows: así la barra de tareas muestra el ícono del programa
    # y no el ícono genérico de Python.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Spanishverse.Library")
    except Exception:
        pass
    if not install_checks():
        return
    # Pantalla de inicio: el programa se abre solo si está todo al día (o si el usuario elige usarlo sin conexión).
    start = StartScreen(auto_update="--actualizar" in sys.argv)
    start.mainloop()
    if start.result != "abrir" or not DB.exists():
        return
    App(Data(DB), pending=getattr(start, "pending", [])).mainloop()


class StartScreen(tk.Tk):
    """Pantalla de inicio: logo y nombre del programa. Al abrir busca actualizaciones; si está todo al día entra
    directo al programa, y si falta algo o hay novedades, el programa no se usa hasta actualizar (botones
    «Actualizar» y «Salir»). Al terminar de bajar todo, ofrece los accesos directos y pide volver a abrirlo.
    Usa fuentes comunes (no las de F()): esta ventana se cierra antes de que se abra el programa."""

    BTN = dict(relief="flat", bd=0, cursor="hand2", padx=22, pady=8, font=("Segoe UI Semibold", 11))

    def __init__(self, auto_update=False):
        super().__init__()
        import config
        self.result = None  # "abrir" = entrar al programa
        self.auto_update = auto_update
        self.title("Spanishverse Library")
        if ICON.exists():
            self.iconbitmap(default=str(ICON))
        self.configure(bg=BG)
        w, h = 780, 600
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+{(self.winfo_screenheight() - h) // 3}")
        self.minsize(640, 520)
        self.protocol("WM_DELETE_WINDOW", self.quit_program)
        self.messages = queue.Queue()
        self.running = False
        box = tk.Frame(self, bg=BG)
        box.pack(fill="both", expand=True, padx=36, pady=24)
        logo = ROOT / "tools" / "icon_png" / "128.png"
        if logo.exists():
            self.logo = tk.PhotoImage(file=str(logo))
            tk.Label(box, image=self.logo, bg=BG).pack(pady=(0, 6))
        tk.Label(box, text="Spanishverse Library", bg=BG, fg=INK, font=("Segoe UI Semibold", 26)).pack()
        tk.Label(box, text="Biblioteca de cartas de Shadowverse: Worlds Beyond en español", bg=BG, fg=MUTED,
                 font=("Segoe UI", 11)).pack()
        tk.Label(box, text=f"De fans y para fans · libre y gratuito · versión {config.VERSION}", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 10)).pack(pady=(2, 14))
        self.status = tk.Label(box, text="Buscando actualizaciones…", bg=BG, fg=INK, font=("Segoe UI Semibold", 12),
                               wraplength=680, justify="center")
        self.status.pack()
        self.detail = tk.Label(box, text="", bg=BG, fg=MUTED, font=("Segoe UI", 10), wraplength=680, justify="center")
        self.detail.pack(pady=(4, 10))
        self.buttons = tk.Frame(box, bg=BG)
        self.buttons.pack(side="bottom", pady=(10, 0))
        self.work = tk.Frame(box, bg=BG)  # progreso de la actualización (aparece al apretar «Actualizar»)
        self.bar = ttk.Progressbar(self.work, mode="indeterminate")
        self.log = tk.Text(self.work, bg=FIELD, fg=INK, relief="flat", font=("Consolas", 9), wrap="word", height=10,
                           state="disabled", padx=8, pady=6)
        threading.Thread(target=self._check, daemon=True).start()
        self._poll_id = self.after(100, self._poll)

    # ---------- botones ----------
    def destroy(self):
        """Al cerrar, se cancela la lectura periódica de mensajes (si no, Tcl avisa de un comando inexistente)."""
        try:
            self.after_cancel(self._poll_id)
        except (AttributeError, tk.TclError, ValueError):
            pass
        super().destroy()

    def _button(self, text, command, primary=False):
        b = tk.Button(self.buttons, text=text, command=command, bg=ACCENT if primary else PANEL,
                      fg="#ffffff" if primary else INK, activebackground="#8a6fe0" if primary else LINE,
                      activeforeground="#ffffff" if primary else INK, **self.BTN)
        b.pack(side="left", padx=6)
        return b

    def _clear_buttons(self):
        for b in self.buttons.winfo_children():
            b.destroy()

    # ---------- revisar ----------
    def _check(self):
        try:
            import updater
            reasons, online = updater.pending()
            usable = updater.usable_offline()
        except Exception as e:
            reasons, online, usable = [f"No se pudo revisar ({e})"], False, False
        self.messages.put(("revisado", (reasons, online, usable)))

    def _checked(self, reasons, online, usable):
        """La primera descarga completa es obligatoria; después, actualizar es opcional y el programa funciona sin
        internet con lo que ya tiene."""
        first_done = load_settings().get("descarga_inicial_completa")
        if online and not reasons:
            if not first_done:
                save_settings(descarga_inicial_completa=True)  # ya tenía todo (por ejemplo, de una versión anterior)
            return self.open_program()
        self.first_time = not first_done
        self._clear_buttons()
        if self.first_time and not online:
            self.status.config(text="Hace falta internet para la primera descarga.")
            self.detail.config(text="La primera vez el programa baja las cartas, las imágenes y las voces. Conectate a "
                                    "internet y apretá «Reintentar». Después ya funciona sin internet.")
            self._button("Reintentar", self.retry, primary=True)
            self._button("Salir", self.quit_program)
            return
        if not online:  # sin internet: se usa con lo que ya tiene
            return self.open_program()
        import paths
        no_game = ("\n\nNo encontré Shadowverse: Worlds Beyond en Steam: sin el juego no hay voces (todo lo demás "
                   "funciona). Si lo tenés instalado en otro lugar, elegí su carpeta antes de seguir."
                   if paths.game_data() is None else "")
        if self.first_time:
            self.status.config(text="Primera vez: hay que descargar todo antes de usar el programa.")
            self.detail.config(text="Se baja:\n• " + "\n• ".join(reasons) +
                                    "\n\nPuede tardar un buen rato; se hace una sola vez." + no_game)
            self._button("Descargar todo", self.start_update, primary=True)
            self._game_button(no_game)
            self._button("Salir", self.quit_program)
        else:
            self.status.config(text="Hay novedades para actualizar.")
            self.detail.config(text="Novedades:\n• " + "\n• ".join(reasons) +
                                    "\n\nPodés actualizar ahora o más tarde con «⟳ Actualizar» dentro del programa."
                                    + no_game)
            self._button("Actualizar", self.start_update, primary=True)
            self._game_button(no_game)
            self._button("Iniciar sin actualizar", lambda: self.open_program(reasons))
        if self.auto_update:  # se volvió a abrir solo después de instalar una versión nueva: sigue
            self.start_update()

    def _game_button(self, show):
        """«Elegir carpeta del juego», solo si no se encontró el juego; después de elegirla se vuelve a revisar."""
        if show:
            self._button("🎮 Elegir carpeta del juego", lambda: choose_game_folder(self) and self.retry())

    def retry(self):
        self._clear_buttons()
        self.status.config(text="Buscando actualizaciones…")
        self.detail.config(text="")
        threading.Thread(target=self._check, daemon=True).start()

    # ---------- actualizar ----------
    def start_update(self):
        self._clear_buttons()
        self.running = True
        self.status.config(text="Actualizando… no cierres esta ventana.")
        self.detail.config(text="La primera vez tarda bastante (imágenes y voces). Si se corta internet, la próxima "
                                "vez sigue desde donde quedó.")
        self.work.pack(fill="both", expand=True)
        self.bar.pack(fill="x", pady=(0, 6))
        self.log.pack(fill="both", expand=True)
        self.bar.start(12)
        self._button("Salir", self.quit_program)
        threading.Thread(target=self._update, daemon=True).start()

    def write(self, text):
        self.messages.put(("texto", text))

    def _update(self):
        try:
            import updater
            info = updater.remote_info()
            version = updater.program_update(info)
            if version:
                self.write(f"Versión nueva del programa ({version}): se instala primero; el programa se cierra, se "
                           "vuelve a abrir solo y sigue con el resto.")
                script = updater.prepare_program_update(self.write)
                if script:
                    self.messages.put(("instalar", script))
                    return
            result = updater.run(progress=self.write)
            reasons, online = updater.pending()
        except Exception as e:
            self.write(f"Error inesperado: {e}")
            result, reasons, online = {}, ["la actualización no terminó"], True
        self.messages.put(("fin", (result, reasons)))

    def _poll(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:  # la ventana (o el programa) ya se cerró
            return
        lines = []
        while not self.messages.empty():
            kind, value = self.messages.get()
            if kind == "texto":
                lines.append(value)
                continue
            if lines:
                self._append("\n".join(lines))
                lines = []
            if kind == "revisado":
                self._checked(*value)
            elif kind == "instalar":
                import updater
                self._append("\nInstalando la versión nueva: el programa se vuelve a abrir solo.")
                self.update()
                updater.run_program_update(value)
                self.after(300, self.destroy)
                return
            elif kind == "fin":
                self._finished(*value)
        if lines:
            self._append("\n".join(lines))
        self._poll_id = self.after(100, self._poll)

    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- listo ----------
    def _finished(self, result, reasons):
        import setup_checks
        self.running = False
        self.bar.stop()
        self.bar.configure(mode="determinate", value=100)
        self._clear_buttons()
        if reasons:
            self.status.config(text="La actualización terminó, pero quedó algo pendiente.")
            self.detail.config(text="Pendiente:\n• " + "\n• ".join(reasons) +
                               "\n\nRevisá el detalle de abajo y volvé a intentar.")
            self._button("Reintentar", self.start_update, primary=True)
            if load_settings().get("descarga_inicial_completa"):  # solo la primera descarga es obligatoria
                self._button("Abrir el programa", self.open_program)
            self._button("Salir", self.quit_program)
            return
        first = not load_settings().get("descarga_inicial_completa")
        save_settings(descarga_inicial_completa=True)
        if not first:  # actualización de siempre: se entra directo
            self.status.config(text="¡Listo! El programa está al día.")
            self.detail.config(text="")
            self._button("Abrir el programa", self.open_program, primary=True)
            return
        self.status.config(text="¡Listo! Ya está todo descargado.")
        self.detail.config(text="Cerrá el programa y volvé a abrirlo para empezar a usarlo. De ahora en más funciona "
                                "sin internet; las actualizaciones son opcionales.")
        self.log.pack_forget()
        opts = tk.Frame(self.work, bg=BG)
        opts.pack(fill="x", pady=(10, 0))
        exe = setup_checks.program_path()
        self.want_desktop = tk.BooleanVar(value=not setup_checks.shortcut_exists("desktop"))
        self.want_start = tk.BooleanVar(value=not setup_checks.shortcut_exists("start"))
        for text, var in (("Crear un acceso directo en el escritorio", self.want_desktop),
                          ("Agregar el programa al menú Inicio de Windows", self.want_start)):
            tk.Checkbutton(opts, text=text, variable=var, bg=BG, fg=INK, selectcolor=FIELD, activebackground=BG,
                           activeforeground=INK, font=("Segoe UI", 11), anchor="w").pack(fill="x", pady=2)
        tk.Label(opts, text="Para tenerlo en la barra de tareas: abrí el programa, hacé clic derecho en su ícono de la "
                            "barra de tareas (abajo) y elegí «Anclar a la barra de tareas».",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10), wraplength=680, justify="left").pack(fill="x", pady=(8, 0))
        self._button("Cerrar", lambda: self._close_done(exe), primary=True)

    def _close_done(self, exe):
        import setup_checks
        if self.want_desktop.get():
            setup_checks.create_shortcut(exe, icon=exe, where="desktop")
        if self.want_start.get():
            setup_checks.create_shortcut(exe, icon=exe, where="start")
        self.destroy()

    # ---------- salir / entrar ----------
    def open_program(self, pending=None):
        self.result = "abrir"
        self.pending = pending or []  # el programa marca el botón «Actualizar» si quedaron novedades
        self.destroy()

    def quit_program(self):
        if self.running and not messagebox.askyesno(
                "Salir", "La actualización sigue trabajando. Si salís, queda a medias y la próxima vez sigue desde "
                "donde quedó. ¿Salir igual?", parent=self):
            return
        self.result = None
        self.destroy()


def install_checks():
    """Errores comunes al instalar: se avisan con una explicación en vez de fallar después. False = no abrir."""
    import setup_checks
    root = tk.Tk()
    root.withdraw()
    title = "Spanishverse Library"
    try:
        if setup_checks.running_from_zip(ROOT):
            messagebox.showerror(title, "Abriste el programa sin descomprimirlo.\n\nCerrá esta ventana, buscá el archivo "
                                 "«SpanishverseLibrary-….zip» que bajaste, hacé clic derecho sobre él → «Extraer todo…», "
                                 "elegí una carpeta (por ejemplo, Documentos) y abrí «Spanishverse Library.exe» desde la "
                                 "carpeta descomprimida.", parent=root)
            return False
        if not setup_checks.writable(ROOT):
            messagebox.showerror(title, "Windows no deja guardar archivos en esta carpeta:\n"
                                 f"{ROOT}\n\nMové la carpeta «Spanishverse Library» entera a otro lugar, por ejemplo "
                                 "Documentos o el Escritorio (no a «Archivos de programa»), y abrí el programa desde ahí.",
                                 parent=root)
            return False
        if setup_checks.in_onedrive(ROOT) and not load_settings().get("aviso_onedrive"):
            save_settings(aviso_onedrive=True)
            messagebox.showwarning(title, "La carpeta del programa está dentro de OneDrive:\n"
                                   f"{ROOT}\n\nOneDrive va a subir a la nube las imágenes (unos 3 GB) y puede llenar tu "
                                   "espacio de OneDrive. Te conviene mover la carpeta «Spanishverse Library» a un lugar "
                                   "fuera de OneDrive (por ejemplo, C:\\Juegos). Este aviso no se vuelve a mostrar.",
                                   parent=root)
    finally:
        root.destroy()
    return True


if __name__ == "__main__":
    main()
