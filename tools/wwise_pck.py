"""Lectura de paquetes Wwise (.pck / AKPK) y hashes de nombres (FNV-1 de 32 bits, como usa Wwise)."""
import struct


def fnv1_32(name):
    h = 2166136261
    for b in name.lower().encode("utf-8"):
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= b
    return h


def read_pck(path):
    """Devuelve {"langs": {id: nombre}, "banks": [(id, offset, size, lang)], "streams": [(id, offset, size, lang)]}."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"AKPK":
        return None
    hdr_size, version, lang_size, bank_size, stm_size, ext_size = struct.unpack_from("<IIIIII", data, 4)
    # Con tabla de externos el encabezado tiene 4 tamaños (datos desde el byte 28); sin ella, 3 (desde el 24).
    if hdr_size == 4 + 16 + lang_size + bank_size + stm_size + ext_size:
        pos = 28
    else:
        ext_size, pos = 0, 24
    lang_blob = data[pos:pos + lang_size]
    langs = {}
    n = struct.unpack_from("<I", lang_blob, 0)[0]
    for i in range(n):
        off, lid = struct.unpack_from("<II", lang_blob, 4 + i * 8)
        raw = lang_blob[off:off + 80]
        name = raw.decode("utf-16-le", "ignore").split("\x00")[0] if raw[1:2] == b"\x00" else raw.split(b"\x00")[0].decode("ascii", "ignore")
        langs[lid] = name
    pos += lang_size

    def lut(blob, wide):
        out = []
        if len(blob) < 4:
            return out
        count = struct.unpack_from("<I", blob, 0)[0]
        if count == 0:
            return out
        entry = (len(blob) - 4) // count
        for i in range(count):
            base = 4 + i * entry
            if entry == 24:  # id de 64 bits
                fid, bsize, size, start, lang = struct.unpack_from("<QIIII", blob, base)
            else:
                fid, bsize, size, start, lang = struct.unpack_from("<IIIII", blob, base)
            out.append((fid, start * bsize, size, lang))
        return out

    banks = lut(data[pos:pos + bank_size], False)
    pos += bank_size
    streams = lut(data[pos:pos + stm_size], True)
    return {"langs": langs, "banks": banks, "streams": streams, "data_len": len(data)}


def read_events(path):
    """Eventos de los bancos del paquete: [(id_evento, [id_audio, ...])]. Cada evento es una situación en la
    que el juego reproduce un audio (evento -> acción -> sonido -> audio)."""
    info = read_pck(path)
    if not info:
        return []
    with open(path, "rb") as f:
        data = f.read()
    sounds, actions, events = {}, {}, []
    for _, off, size, _ in info["banks"]:
        bnk = data[off:off + size]
        pos = 0
        while pos + 8 <= len(bnk):
            tag, ln = bnk[pos:pos + 4], struct.unpack_from("<I", bnk, pos + 4)[0]
            if tag == b"HIRC":
                p = pos + 12
                for _ in range(struct.unpack_from("<I", bnk, pos + 8)[0]):
                    kind, sz = bnk[p], struct.unpack_from("<I", bnk, p + 1)[0]
                    body = bnk[p + 5:p + 5 + sz]
                    oid = struct.unpack_from("<I", body, 0)[0]
                    if kind == 2:    # sonido: id del audio que reproduce
                        sounds[oid] = struct.unpack_from("<I", body, 9)[0]
                    elif kind == 3:  # acción: a qué sonido apunta
                        actions[oid] = struct.unpack_from("<I", body, 6)[0]
                    elif kind == 4:  # evento: sus acciones
                        events.append((oid, [struct.unpack_from("<I", body, 5 + 4 * k)[0] for k in range(body[4])]))
                    p += 5 + sz
            pos += 8 + ln
    return [(eid, [sounds[actions[a]] for a in acts if actions.get(a) in sounds]) for eid, acts in events]
