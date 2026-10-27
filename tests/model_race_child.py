"""A separate process fetching a small model set through a slow fake server (no network), for test_model_lock.py.

argv: start delay in seconds, then optionally a delay before each hash (an 18 MB model hashed on a busy disk).
Prints OK, CORRUPT or FAILED <error>. INKLIGHT_MODEL_CACHE names the shared cache.
"""

import hashlib
import io
import sys
import time
import urllib.request

from inklight import modelstore

DATA = bytes(range(256)) * 400  # 100 KB, read 2 KB at a time
SPEC = modelstore.ModelFile("lm_cjk.npz", len(DATA), hashlib.sha256(DATA).hexdigest())
SET = modelstore.ModelSet(key="race", title="Race models", repo="org/race", revision="0" * 16, files=(SPEC,))


class _Slow(io.BytesIO):
    status = 200

    def read(self, n: int = -1) -> bytes:
        time.sleep(0.01)
        return super().read(min(n, 2048) if n and n > 0 else 2048)

    def geturl(self) -> str:
        return "https://example.invalid/model"

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_):  # noqa: ANN002
        self.close()


def _fake(request, timeout=None):  # noqa: ANN001, ANN202
    rng = request.get_header("Range")
    start = int(rng.split("=")[1].rstrip("-")) if rng else 0
    response = _Slow(DATA[start:])
    response.status = 206 if rng else 200
    return response


def main() -> None:
    urllib.request.urlopen = _fake
    if len(sys.argv) > 2:
        real = modelstore._sha256

        def slow(path):  # noqa: ANN001, ANN202
            time.sleep(float(sys.argv[2]))
            return real(path)

        modelstore._sha256 = slow
    time.sleep(float(sys.argv[1]))
    try:
        folder = modelstore.ensure(SET)
        ok = hashlib.sha256((folder / SPEC.path).read_bytes()).hexdigest() == SPEC.sha256
        print("OK" if ok else "CORRUPT", flush=True)
    except Exception as exc:  # noqa: BLE001 - reported to the test
        print(f"FAILED {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
