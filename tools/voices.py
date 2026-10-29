"""Voces de las cartas: conversión desde los paquetes Wwise del juego, huellas de sonido y reconocimiento.

- build_cache(): convierte todas las líneas de los paquetes de voces en japonés a WAV (24 kHz, mono) en
  voices/cache/ y guarda un índice con la "huella" de cada línea (voices/index.npz + voices/index.json).
- match(): dado un audio grabado (una línea), devuelve los paquetes/líneas más parecidos.
- Mapeo carta -> voz: voices/mapping.json (lo arma el asistente; no se borra al actualizar las cartas).

Uso por consola: py -3.13 tools/voices.py build
"""
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wwise_pck  # noqa: E402

from paths import ROOT, game_data  # noqa: E402
VOICES = ROOT / "voices"
CACHE = VOICES / "cache"
INDEX_JSON = VOICES / "index.json"
INDEX_NPZ = VOICES / "index.npz"
MAPPING = VOICES / "mapping.json"
VGMSTREAM = ROOT / "tools" / "vgmstream" / "vgmstream-cli.exe"

SR = 24000          # frecuencia de los WAV guardados
FEAT_SR = 16000     # frecuencia para las huellas (hasta 8 kHz: los rugidos y ruidos tienen mucho en agudos)
FRAME = 512         # 32 ms a 16 kHz
BANDS = 40
MAX_CARD_LINES = 30  # paquetes más grandes: voces de sistema, historia o líderes
MAX_SFX_BYTES = 400_000  # efectos más pesados que esto son música o ambientes largos, no sonidos de cartas
PROFILES = VOICES / "profiles.npy"
SIGNATURES = VOICES / "index_firmas.json"  # paquete -> tamaño y fecha con que se indexó (para no repetirlo)


# ---------- lectura de paquetes ----------
def voice_packs(root):
    """[(ruta_relativa, id_banco, [(id_audio, offset, tamaño), ...], tipo)] de los paquetes que pueden tener
    sonidos de cartas: "voice" (voces en japonés) y "sfx" (efectos sin idioma: rugidos, gruñidos, máquinas)."""
    out = []
    for dp, _, files in os.walk(root):
        for fn in files:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                if f.read(4) != b"AKPK":
                    continue
            info = wwise_pck.read_pck(p)
            if not info:
                continue
            langs = set(info["langs"].values())
            if any("japanese" in v for v in langs):
                kind = "voice"
            elif langs == {"sfx"}:
                kind = "sfx"
            else:
                continue  # voces en otros idiomas
            bank = info["banks"][0][0] if info["banks"] else 0
            streams = [(s[0], s[1], s[2]) for s in info["streams"]]
            # Además de los audios de la tabla del paquete, algunos bancos guardan audios adentro (DIDX/DATA).
            streams += _embedded_media(p, info)
            if kind == "sfx":
                streams = [s for s in streams if s[2] <= MAX_SFX_BYTES]
            if streams:
                out.append((os.path.relpath(p, root), bank, streams, kind))
    return out


def _embedded_media(path, info):
    """Audios guardados dentro del banco de sonido (secciones DIDX + DATA): [(id, offset_absoluto, tamaño)]."""
    import struct
    out = []
    with open(path, "rb") as f:
        data = f.read()
    for _, off, size, _ in info["banks"]:
        bnk = data[off:off + size]
        pos, didx, data_start = 0, [], None
        while pos + 8 <= len(bnk):
            tag, ln = bnk[pos:pos + 4], struct.unpack_from("<I", bnk, pos + 4)[0]
            if tag == b"DIDX":
                didx = [struct.unpack_from("<III", bnk, pos + 8 + i * 12) for i in range(ln // 12)]
            elif tag == b"DATA":
                data_start = off + pos + 8
            pos += 8 + ln
        if didx and data_start is not None:
            out += [(mid, data_start + moff, msize) for mid, moff, msize in didx]
    return out


# ---------- audio ----------
def read_wav(path):
    with wave.open(str(path)) as wf:
        sr, ch, n = wf.getframerate(), wf.getnchannels(), wf.getnframes()
        x = np.frombuffer(wf.readframes(n), dtype=np.int16).astype(np.float32) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    y = np.clip(x * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(y.tobytes())


def resample(x, sr_from, sr_to):
    if sr_from == sr_to or len(x) == 0:
        return x
    n = int(len(x) * sr_to / sr_from)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


# Bordes de las bandas de frecuencia (fijos: así todas las huellas tienen la misma forma, aunque el audio
# sea muy corto). Algunos bordes graves se repiten al redondear, por eso hay algo menos de BANDS bandas.
_EDGES = np.unique(np.geomspace(2, FRAME // 2, BANDS + 1).astype(int))
N_BANDS = len(_EDGES) - 1


def _log_bands(x, sr):
    """Energía (log) en N_BANDS bandas de frecuencia, cada 32 ms."""
    x = resample(x, sr, FEAT_SR)
    n = len(x) // FRAME
    if n < 2:
        return np.zeros((1, N_BANDS), np.float32)
    frames = x[: n * FRAME].reshape(n, FRAME) * np.hanning(FRAME)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    bands = np.stack([spec[:, a:b].sum(axis=1) for a, b in zip(_EDGES[:-1], _EDGES[1:])], axis=1)
    return np.log1p(bands * 1000)


def features(x, sr):
    """Huella "dinámica": cómo cambia el sonido en el tiempo (distingue frases y palabras)."""
    f = _log_bands(x, sr)
    f = f - f.mean(axis=0, keepdims=True)
    norm = np.linalg.norm(f, axis=1, keepdims=True)
    return (f / np.maximum(norm, 1e-6)).astype(np.float32)


def window_scores(bands, ref):
    """Parecido de la línea ref (huella de features) con cada tramo de la grabación (bands = _log_bands).
    Cada tramo se normaliza por separado, igual que se hizo con la línea: si se normaliza la grabación entera,
    los silencios largos alrededor de una frase corta la deforman y ni el audio exacto se parece."""
    m, n = len(ref), len(bands)
    if m < 3 or n < m:
        return np.zeros(0, np.float32)
    out = []
    for t0 in range(0, n - m + 1, 256):  # de a pedazos, para no usar demasiada memoria
        w = np.lib.stride_tricks.sliding_window_view(bands[t0:t0 + 256 + m - 1], m, axis=0).transpose(0, 2, 1)
        w = w - w.mean(axis=1, keepdims=True)
        w = w / np.maximum(np.linalg.norm(w, axis=2, keepdims=True), 1e-6)
        out.append(np.einsum("tmb,mb->t", w, ref) / m)
    return np.concatenate(out).astype(np.float32)


def profile(x, sr):
    """Huella de "timbre": el color general del sonido (lo que más identifica un rugido o un ruido)."""
    f = _log_bands(x, sr)
    loud = f.sum(axis=1)
    keep = f[loud >= np.percentile(loud, 30)] if len(f) > 3 else f  # sin los silencios
    p = keep.mean(axis=0)
    p = p - p.mean()
    return (p / max(np.linalg.norm(p), 1e-6)).astype(np.float32)


# ---------- conversión de todas las voces ----------
def build_cache(root=None, progress=print):
    """Convierte los audios del juego que todavía no estén en voices/cache y rearma el índice. Devuelve False si no
    encontró el juego."""
    root = root or game_data()
    if root is None:
        progress("no encontré Shadowverse: Worlds Beyond instalado en Steam: el índice de voces queda como estaba")
        return False
    CACHE.mkdir(parents=True, exist_ok=True)
    packs = voice_packs(root)
    if not packs:
        progress(f"no encontré los audios del juego en {root}: el índice de voces queda como estaba")
        return False
    # Lo ya indexado se reusa: un paquete que no cambió (mismo tamaño, fecha y cantidad de audios) no se vuelve a
    # leer. Así, cuando el juego se actualiza, solo se procesan los paquetes nuevos o cambiados.
    old_sigs, old_entries, old_feats, old_profs = {}, {}, [], None
    if SIGNATURES.exists() and INDEX_JSON.exists() and INDEX_NPZ.exists():
        try:
            old_sigs = json.loads(SIGNATURES.read_text(encoding="utf-8"))
            old_entries = {e["rel"]: e for e in json.loads(INDEX_JSON.read_text(encoding="utf-8"))}
            npz = np.load(INDEX_NPZ)
            old_feats = [npz[f"arr_{i}"] for i in range(len(npz.files))]
            old_profs = np.load(PROFILES) if PROFILES.exists() else None
        except Exception:
            old_sigs, old_entries, old_feats, old_profs = {}, {}, [], None
    sigs, reused = {}, 0
    entries, feats, profs = [], [], []
    tmp = CACHE / "_tmp.wem"
    for i, (rel, bank, streams, kind) in enumerate(packs, 1):
        st = os.stat(os.path.join(root, rel))
        sig = f"{st.st_size}:{st.st_mtime_ns}:{len(streams)}"
        sigs[rel] = sig
        if old_sigs.get(rel) == sig and old_profs is not None:
            old = old_entries.get(rel)
            if old is None:  # se había revisado y no tenía líneas de cartas
                reused += 1
                continue
            if all((CACHE / ln["wav"]).exists() for ln in old["lines"]):
                lines = []
                for ln in old["lines"]:
                    lines.append(dict(ln, feat=len(feats)))
                    feats.append(old_feats[ln["feat"]])
                    profs.append(old_profs[ln["feat"]])
                entries.append(dict(old, lines=lines))
                reused += 1
                if i % 500 == 0 or i == len(packs):
                    progress(f"{i}/{len(packs)} paquetes")
                continue
        data = open(os.path.join(root, rel), "rb").read()
        lines = []
        for j, (sid, off, size) in enumerate(streams):
            out = CACHE / f"{bank}_{sid}.wav"
            if not out.exists():
                tmp.write_bytes(data[off:off + size])
                raw = CACHE / "_tmp.wav"
                subprocess.run([str(VGMSTREAM), "-o", str(raw), str(tmp)], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if not raw.exists():
                    continue
                x, sr = read_wav(raw)
                write_wav(out, resample(x, sr, SR), SR)
                raw.unlink()
            x, sr = read_wav(out)
            if kind == "sfx" and len(x) / sr > 8:
                continue  # sonidos largos: música o ambientes, no sonidos de una carta
            lines.append({"stream": sid, "wav": out.name, "dur": round(len(x) / sr, 3), "feat": len(feats)})
            feats.append(features(x, sr))
            profs.append(profile(x, sr))
        if lines:
            entries.append({"rel": rel, "bank": bank, "kind": kind, "lines": lines})
        if i % 100 == 0 or i == len(packs):
            progress(f"{i}/{len(packs)} paquetes")
    if tmp.exists():
        tmp.unlink()
    INDEX_JSON.write_text(json.dumps(entries), encoding="utf-8")
    np.savez_compressed(INDEX_NPZ, *feats)
    np.save(PROFILES, np.stack(profs))
    SIGNATURES.write_text(json.dumps(sigs), encoding="utf-8")
    progress(f"listo: {len(entries)} paquetes, {len(feats)} líneas ({len(packs) - reused} paquetes nuevos o cambiados)")


# ---------- reconocimiento ----------
class Index:
    def __init__(self):
        self.entries = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        npz = np.load(INDEX_NPZ)
        self.feats = [npz[f"arr_{i}"] for i in range(len(npz.files))]
        self.profiles = np.load(PROFILES) if PROFILES.exists() else None
        # Los paquetes con más de 30 líneas son voces de sistema, historia o líderes, nunca de una carta:
        # tienen tantas líneas que siempre encuentran algún parecido y "se roban" la votación.
        self.lines = [(e["bank"], k, ln) for e in self.entries if len(e["lines"]) <= MAX_CARD_LINES
                      for k, ln in enumerate(e["lines"])]
        # Algunos paquetes repiten el mismo audio en varias líneas (la misma frase para varias situaciones).
        # Se agrupan por contenido para buscar cada sonido una sola vez, pero todas las veces que aparezca.
        import hashlib
        self.same_audio = {}
        for e in self.entries:
            groups = {}
            for ln in e["lines"]:
                path = CACHE / ln["wav"]
                key = hashlib.md5(path.read_bytes()).hexdigest() if path.exists() else ln["wav"]
                groups.setdefault(key, []).append(ln)
            self.same_audio[e["bank"]] = list(groups.values())

    def match(self, x, sr, top=5):
        """Las líneas más parecidas a la grabación x: [(puntaje, banco, número_de_línea, línea)]."""
        q = features(x, sr)
        qp = profile(x, sr) if self.profiles is not None else None
        dur = len(x) / sr
        scored = []
        for bank, k, ln in self.lines:
            if abs(ln["dur"] - dur) > max(0.6, dur * 0.35):
                continue  # duraciones muy distintas: no puede ser
            ref = self.feats[ln["feat"]]
            s = _similarity(q, ref)
            if qp is not None:
                # 70 % cómo cambia el sonido en el tiempo + 30 % su timbre (clave para rugidos y ruidos).
                s = 0.7 * s + 0.3 * max(0.0, float(qp @ self.profiles[ln["feat"]]))
            scored.append((s, bank, k, ln))
        scored.sort(key=lambda t: -t[0])
        return scored[:top]

    def best_in_bank(self, x, sr, bank):
        """La línea de ese paquete que más se parece a la grabación: (puntaje, número_de_línea, línea)."""
        q = features(x, sr)
        best = (0.0, None, None)
        for b, k, ln in self.lines:
            if b == bank:
                s = _similarity(q, self.feats[ln["feat"]])
                if s > best[0]:
                    best = (s, k, ln)
        return best

    def _bank_peaks(self, rec_feat):
        """Búsqueda rápida de TODAS las líneas a lo largo de la grabación (correlación por FFT).
        Devuelve {paquete: [mejor parecido de cada línea]}. No depende de cortar la grabación por silencios,
        así que sirve también para rugidos y ruidos con colas o pausas internas."""
        n = len(rec_feat)
        size = 1 << int(np.ceil(np.log2(max(n, 2) * 2)))
        rec_fft = np.fft.rfft(rec_feat, size, axis=0)
        out = {}
        for b, _, ln in self.lines:
            ref = self.feats[ln["feat"]]
            m = len(ref)
            if m < 3 or n < m:
                continue
            conv = np.fft.irfft((rec_fft * np.fft.rfft(ref[::-1], size, axis=0)).sum(axis=1), size)
            peak = float(conv[m - 1:n].max()) / m
            out.setdefault(b, []).append(peak)
        return out

    def _peak(self, rec_bands, ln):
        """Mejor parecido de una línea en cualquier punto de la grabación."""
        scores = window_scores(rec_bands, self.feats[ln["feat"]])
        return float(scores.max()) if len(scores) else 0.0

    def lines_of(self, bank):
        """Todas las líneas de un paquete, en el orden en que están guardadas."""
        entry = next((e for e in self.entries if e["bank"] == bank), None)
        return entry["lines"] if entry else []

    def _detect(self, rec_bands, bank, threshold=0.55, relative=0.75):
        """Busca cada línea del paquete a lo largo de toda la grabación (sin cortarla por silencios).
        Devuelve [(posición, puntaje, id_audio)] de las líneas encontradas, sin superponerse, en orden de aparición."""
        found = []  # (posición, puntaje, largo, grupo de líneas con el mismo audio)
        for group in self.same_audio.get(bank, []):
            ref = self.feats[group[0]["feat"]]
            m = len(ref)
            scores = window_scores(rec_bands, ref)
            if not len(scores):
                continue
            # Todas las apariciones de este sonido (puede sonar varias veces si el juego repite la frase).
            order = np.argsort(-scores)
            taken = []
            for t in order:
                if scores[t] < threshold or len(taken) >= len(group):
                    break  # un sonido solo puede contarse tantas veces como esté repetido en el paquete
                if all(abs(t - t2) >= m * 0.6 for t2 in taken):
                    taken.append(int(t))
                    found.append((int(t), float(scores[t]), m, id(group), group))
        # Solo las apariciones que se parecen casi tanto como la mejor: descarta parecidos casuales.
        if found:
            top = max(f[1] for f in found)
            found = [f for f in found if f[1] >= relative * top]
        # Si dos sonidos distintos caen en el mismo lugar de la grabación, se queda el de mayor puntaje.
        kept = []
        for t, s, m, gid, group in sorted(found, key=lambda f: -f[1]):
            if all(min(t + m, t2 + m2) - max(t, t2) < 0.5 * min(m, m2) for t2, _, m2, _, _ in kept):
                kept.append((t, s, m, gid, group))
        # Las apariciones de un mismo sonido se reparten, en orden, entre sus líneas repetidas.
        used = {}
        out = []
        for t, s, m, gid, group in sorted(kept):
            k = used.get(gid, 0)
            used[gid] = k + 1
            out.append((t, s, group[k % len(group)]["stream"]))
        return out

    def identify(self, recordings, sr, force_bank=None):
        """recordings: {"normal": audio, "evo": audio}. Elige el paquete entre los más votados y ubica cada
        una de sus líneas dentro de las grabaciones; el orden de las líneas es el orden en que aparecen.
        Devuelve {"bank", "normal": [ids], "evo": [ids], "confidence", "total_lines"}."""
        recs = {phase: x for phase, x in recordings.items() if x is not None and len(x)}
        # 1) Candidatos: votación con trozos de la grabación cortados por silencios.
        votes = {}
        for x in recs.values():
            # Además de los trozos, las frases con pausas cortas adentro ("Delta... Cannon") enteras: cortadas
            # en dos, ninguna mitad se parece a la línea completa.
            segs = split_utterances(x, sr)
            whole = [s for s in split_utterances(x, sr, min_gap=1.0, min_len=0.2)
                     if not any(len(s) == len(t) for t in segs)]
            for seg in segs + whole:
                seen = set()
                for score, bank, _, _ in self.match(seg, sr, top=8):
                    if bank not in seen:
                        votes[bank] = votes.get(bank, 0.0) + score
                        seen.add(bank)
        if not votes and not force_bank:
            return None
        ranked = sorted(votes, key=votes.get, reverse=True)
        feats = {phase: features(x, sr) for phase, x in recs.items()}
        bands = {phase: _log_bands(x, sr) for phase, x in recs.items()}
        sounds = {phase: [(start / sr * FEAT_SR / FRAME, (start + len(seg)) / sr * FEAT_SR / FRAME)
                          for start, seg in split_utterances(x, sr, with_pos=True)] for phase, x in recs.items()}
        n_sounds = sum(len(s) for s in sounds.values())

        def evaluate(banks):
            out = []
            for b in banks:
                det = {phase: self._detect(f, b) for phase, f in bands.items()}
                hits = [s for d in det.values() for _, s, _ in d]
                # Sonidos grabados que quedan explicados por alguna línea ubicada. Se cuentan sonidos y no
                # líneas: una frase con una pausa adentro son dos sonidos que explica una sola línea.
                length = {ln["stream"]: len(self.feats[ln["feat"]]) for ln in self.lines_of(b)}
                explained = sum(any(min(b1, t + length[sid]) - max(a1, t) > 0.5 * (b1 - a1) for t, _, sid in det[phase])
                                for phase, segs in sounds.items() for a1, b1 in segs)
                out.append((float(np.mean(hits)) if hits else 0.0, explained, b, det, hits))
            return out

        # 2) Voces: el más votado; si el segundo quedó muy parejo, desempata el parecido PROMEDIO de las
        #    líneas ubicadas (la suma favorecería a paquetes con muchas líneas y parecidos casuales).
        if force_bank:
            scored = evaluate([force_bank])
        else:
            scored = evaluate([b for b in ranked[:3] if votes[b] >= 0.9 * votes[ranked[0]]])
            needed = max(1, 0.6 * min(n_sounds, 6))
            # 3) Si el resultado es débil (típico de rugidos y ruidos, donde cortar por silencios falla),
            #    buscar más candidatos con la búsqueda deslizante sobre todos los audios. Débil = ningún
            #    candidato se parece bien Y explica buena parte de los sonidos grabados.
            if not any(s[0] >= 0.75 and s[1] >= needed for s in scored):
                bank_score, bank_best = {}, {}
                for f in feats.values():
                    for b, peaks in self._bank_peaks(f).items():
                        top3 = sorted(peaks, reverse=True)[:3]
                        bank_score[b] = bank_score.get(b, 0.0) + sum(p for p in top3 if p >= 0.55)
                        bank_best[b] = max(bank_best.get(b, 0.0), max(peaks))
                # La suma de las 3 mejores favorece a paquetes con muchas líneas; los de una sola frase
                # (hechizos) entran también por su mejor línea.
                extra = sorted(bank_score, key=bank_score.get, reverse=True)[:12]
                extra += sorted(bank_best, key=bank_best.get, reverse=True)[:6]
                extra = [b for b in dict.fromkeys(extra) if b not in {s[2] for s in scored}]
                scored += evaluate(extra)
            # Solo cuentan los candidatos que explican una buena parte de los sonidos grabados.
            enough = [s for s in scored if s[1] >= needed]
            scored = enough or scored
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        # Entre candidatos casi igual de parecidos, gana el que explica más sonidos de la grabación
        # (uno que solo explica 3 de 5 sonidos no puede ganarle a uno que explica los 5 por décimas).
        close = [s for s in scored if s[0] >= scored[0][0] - 0.02]
        best = max(close, key=lambda s: (s[1], s[0]))
        scored.remove(best)
        scored.insert(0, best)
        best_mean, _, bank, det, hits = scored[0]
        # Otros personajes casi empatados (sonidos casi idénticos, típico de criaturas y máquinas).
        near = [s for s in scored[1:] if s[0] >= 0.985 * best_mean and s[1] >= 0.8 * scored[0][1] and s[0] > 0]
        alternatives = [s[2] for s in near[:3]]
        ties = len(near)  # muchos empatados = sonidos genéricos compartidos por varias cartas
        entry = next(e for e in self.entries if e["bank"] == bank)
        # Detalle para revisar problemas: puntaje de cada línea del paquete en cada grabación.
        self.last_debug = {
            "candidates": [(b, round(votes[b], 3)) for b in ranked[:5]],
            "bank": bank,
            "lines": {phase: [(ln["stream"], round(float(self._peak(bands[phase], ln)), 3))
                              for b, _, ln in self.lines if b == bank] for phase in feats},
            "kept": {phase: [(t, round(s, 3), sid) for t, s, sid in d] for phase, d in det.items()},
        }
        # 3) Líneas que el personaje comparte con otra carta (o como líder) y están en OTRO paquete: un sonido
        #    de la grabación que no cayó en ninguna línea del paquete principal pero coincide claramente con una
        #    línea de otro paquete se agrega en su lugar, como [paquete, id].
        length = {ln["stream"]: len(self.feats[ln["feat"]]) for b, _, ln in self.lines if b == bank}
        foreign_hits, lines_out = [], {}
        for phase, x in recs.items():
            items = [(t, sid) for t, _, sid in det.get(phase, [])]
            covered = [(t, t + length.get(sid, 1)) for t, sid in items]
            for start, seg in split_utterances(x, sr, with_pos=True):
                t0 = int(start / sr * FEAT_SR / FRAME)
                t1 = t0 + max(1, int(len(seg) / sr * FEAT_SR / FRAME))
                if any(min(t1, b) - max(t0, a) > 0.3 * (t1 - t0) for a, b in covered):
                    continue  # ese sonido ya es una línea del paquete principal
                top = self.match(seg, sr, top=1)
                # Umbral alto: otro personaje que dice la misma palabra puede parecerse bastante (≈0,6);
                # solo se acepta si el sonido es prácticamente el mismo.
                if top and top[0][1] != bank and top[0][0] >= 0.8:
                    score, other_bank, _, ln = top[0]
                    items.append((t0, [other_bank, ln["stream"]]))
                    foreign_hits.append(score)
            lines_out[phase] = [sid for _, sid in sorted(items, key=lambda it: it[0])]
        self.last_debug["foreign"] = {p: [s for s in l if isinstance(s, list)] for p, l in lines_out.items()}
        hits = hits + foreign_hits
        return {"bank": bank,
                "normal": lines_out.get("normal", []),
                "evo": lines_out.get("evo", []),
                "confidence": float(np.mean(hits)) if hits else 0.0,
                "total_lines": len(entry["lines"]),
                "alternatives": alternatives,
                "ties": ties}


def _similarity(a, b):
    """Parecido entre dos huellas, probando pequeños corrimientos en el tiempo."""
    best = 0.0
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    for shift in range(-6, 7):
        if shift >= 0:
            x, y = a[shift:], b
        else:
            x, y = a, b[-shift:]
        m = min(len(x), len(y))
        if m < 3:
            continue
        s = float((x[:m] * y[:m]).sum(axis=1).mean()) * (m / max(len(a), len(b)))
        best = max(best, s)
    return best


def split_utterances(x, sr, min_gap=0.35, min_len=0.4, with_pos=False):
    """Corta una grabación larga en líneas, usando los silencios entre ellas.
    with_pos=True devuelve además la muestra donde empieza cada trozo: [(inicio, audio)]."""
    hop = int(sr * 0.02)
    if len(x) < hop * 3:
        return []
    env = np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, mode="same"))[::hop]
    # Umbral según el ruido de fondo de esta grabación (música baja, ecualizador, etc.):
    # un poco por encima del piso de ruido, y siempre bastante por debajo de la voz.
    floor, peak = np.percentile(env, 10), env.max()
    thr = max(floor + 0.12 * (peak - floor), floor * 2.5, 1e-4)
    voiced = env > thr
    segs, start, silent = [], None, 0
    for i, v in enumerate(voiced):
        if v:
            if start is None:
                start = i
            silent = 0
        elif start is not None:
            silent += 1
            if silent * 0.02 >= min_gap:
                end = i - silent + 1
                if (end - start) * 0.02 >= min_len:
                    segs.append((start * hop, end * hop))
                start, silent = None, 0
    if start is not None and (len(voiced) - start) * 0.02 >= min_len:
        segs.append((start * hop, len(x)))
    pad = int(sr * 0.05)
    if with_pos:
        return [(max(0, a - pad), x[max(0, a - pad): b + pad]) for a, b in segs]
    return [x[max(0, a - pad): b + pad] for a, b in segs]


def ref(item, bank):
    """Una línea guardada puede ser solo su id (del paquete principal) o [paquete, id] si viene de otro."""
    return (item[0], item[1]) if isinstance(item, (list, tuple)) else (bank, item)


RECORDED = VOICES / "recorded"


def play(path):
    """Reproduce un WAV sin bloquear (la salida ya está despierta gracias a keep_audio_awake)."""
    import winsound
    path = Path(path)
    if path.exists():
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)


def keep_audio_awake(stop):
    """Mientras el programa está abierto, mantiene abierta la salida de audio con silencio, así los auriculares
    Bluetooth (y ecualizadores como FxSound) no se "duermen": dormidos perdían el primer segundo de cada voz.
    Corre en un hilo aparte hasta que stop (threading.Event) se active; si cambia la salida predeterminada
    (otros auriculares o parlantes), pasa a la nueva. Si algo falla, el programa sigue igual, sin esto."""
    import ctypes
    import time
    import warnings
    try:
        import soundcard as sc
    except ImportError:
        return
    warnings.filterwarnings("ignore")
    ctypes.windll.ole32.CoInitializeEx(None, 0)
    rate, block = 48000, 4800  # bloques de 0,1 s
    # Silencio exacto (ceros): mantiene la salida en uso sin sonar nada. (Un ruido muy bajo se oía como un
    # zumbido, porque FxSound sube los sonidos débiles; a los ceros no tiene nada que subirles.)
    signal = np.zeros((block, 1), dtype=np.float32)
    while not stop.is_set():
        try:
            speaker = sc.default_speaker()
            started = time.monotonic()
            with speaker.player(samplerate=rate, channels=1, blocksize=block) as player:
                while not stop.is_set():
                    player.play(signal)
                    if time.monotonic() - started > 5:  # cada 5 s: ¿sigue siendo la misma salida?
                        if sc.default_speaker().id != speaker.id:
                            break
                        started = time.monotonic()
        except Exception:
            stop.wait(5)  # sin salida de audio por ahora: se reintenta en unos segundos


def line_path(item, bank):
    """Ruta del WAV de una línea guardada: del juego (paquete + id) o grabada por el usuario ("rec:archivo")."""
    if isinstance(item, str) and item.startswith("rec:"):
        return RECORDED / item[4:]
    b, sid = ref(item, bank)
    return CACHE / f"{b}_{sid}.wav"


def save_recording_lines(card_id, recordings, sr):
    """Para sonidos que no están como archivo en el juego (mezclas o con efectos): corta las grabaciones del
    usuario en cada sonido y las guarda en voices/recorded/. Devuelve {"normal": [...], "evo": [...]}."""
    RECORDED.mkdir(parents=True, exist_ok=True)
    for old in RECORDED.glob(f"{card_id}_*.wav"):
        old.unlink()  # reemplaza una grabación anterior de la misma carta
    out = {"normal": [], "evo": []}
    for phase, x in recordings.items():
        if x is None or not len(x):
            continue
        for i, seg in enumerate(split_utterances(x, sr), 1):
            peak = float(np.abs(seg).max()) or 1.0
            name = f"{card_id}_{phase}_{i}.wav"
            write_wav(RECORDED / name, resample(seg / peak * 0.9, sr, SR), SR)  # volumen parejo
            out[phase].append(f"rec:{name}")
    return out


# ---------- mapeo carta -> voz ----------
def load_mapping():
    if MAPPING.exists():
        return {int(k): v for k, v in json.loads(MAPPING.read_text(encoding="utf-8")).items()}
    return {}


DEFAULTS = ROOT / "defaults"
DEFAULT_MAPPING = DEFAULTS / "voces.json"  # lo guarda tools/save_defaults.py


def default_voice(card_id):
    """La voz original de una carta (para el botón «Por defecto»): la guardada en defaults/voces.json; si la
    carta es más nueva que ese archivo, la que le asigna la regla automática. None si no tiene voz."""
    if DEFAULT_MAPPING.exists():
        saved = json.loads(DEFAULT_MAPPING.read_text(encoding="utf-8"))
        if str(card_id) in saved:
            return saved[str(card_id)]
    import auto_voices
    entries = {e["bank"]: e for e in json.loads(INDEX_JSON.read_text(encoding="utf-8"))}
    import sqlite3
    cards = [c for (c,) in sqlite3.connect(ROOT / "cards.db").execute("SELECT card_id FROM cards")]
    r = auto_voices.lines_for(card_id, entries, cards)
    if r:
        r["auto"] = True
    return r


def save_mapping(mapping):
    VOICES.mkdir(parents=True, exist_ok=True)
    MAPPING.write_text(json.dumps({str(k): v for k, v in mapping.items()}, ensure_ascii=False, indent=1),
                       encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_cache()
