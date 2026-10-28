"""Escanea bundles UnityFS y lista rutas internas y tipos de objeto.

Uso: py -3.13 -P -E scan_bundles.py <carpeta_dat> <salida.jsonl> [muestra]
"""
import json
import os
import random
import sys
from collections import Counter

import UnityPy

# Los bundles del juego tienen la versión borrada; la real sale del Player.log.
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"

UNITYFS = b"UnityFS\x00"


def iter_files(root):
    for dirpath, _, names in os.walk(root):
        for n in names:
            yield os.path.join(dirpath, n)


def main():
    root, out_path = sys.argv[1], sys.argv[2]
    sample = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    files = list(iter_files(root))
    if sample:
        random.seed(1)
        files = random.sample(files, min(sample, len(files)))

    with open(out_path, "w", encoding="utf-8") as out:
        for i, path in enumerate(files):
            rec = {"file": os.path.relpath(path, root), "size": os.path.getsize(path)}
            try:
                with open(path, "rb") as f:
                    magic = f.read(8)
                if magic != UNITYFS:
                    rec["magic"] = magic[:4].decode("latin-1")
                else:
                    env = UnityPy.load(path)
                    rec["containers"] = list(env.container.keys())[:20]
                    rec["types"] = dict(Counter(o.type.name for o in env.objects))
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"[:200]
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 200 == 0:
                print(f"{i}/{len(files)}", flush=True)
    print("listo", len(files))


if __name__ == "__main__":
    main()
