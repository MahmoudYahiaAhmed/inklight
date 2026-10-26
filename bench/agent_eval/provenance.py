"""Freeze what is being evaluated: build, installed packages, model weights, hardware and configurations.

    EVAL_PYTHON -m ... (run with the evaluation environment's python)
    python bench/agent_eval/provenance.py WHEEL CONFIG_DIR OUT.json

Records the wheel's SHA-256, the installed inklight's location and version, every installed distribution, the model
snapshots on disk (Indra, Docling layout/table, Inklight small models) with their sizes, the hardware, and the
configuration files of each arm. No document content.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from importlib.metadata import distributions, version
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tree(path: Path) -> dict:
    files = [p for p in path.rglob("*") if p.is_file()] if path.exists() else []
    return {"path": str(path), "files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def hf_snapshots(repo: str) -> list[str]:
    root = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots"
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def main() -> None:
    wheel, config_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    import inklight

    memory = None
    try:
        import psutil

        memory = round(psutil.virtual_memory().total / 2**30, 1)
    except ImportError:
        pass
    cpu = [platform.processor()]
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        cpu = [winreg.QueryValueEx(key, "ProcessorNameString")[0]]
    except (ImportError, OSError):
        pass
    record = {
        "build": {
            "commit": subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parents[2]
            ).stdout.strip(),
            "wheel": wheel.name,
            "wheel_sha256": sha256(wheel),
            "installed_inklight": inklight.__file__,
            "inklight_version": version("inklight"),
        },
        "python": sys.version,
        "packages": sorted(f"{d.metadata['Name']}=={d.version}" for d in distributions()),
        "models": {
            "indra (default download)": {"snapshots": hf_snapshots("datalab-to/indra-ocr")},
            "docling layout heron": {"snapshots": hf_snapshots("docling-project/docling-layout-heron")},
            "docling layout heron onnx": {"snapshots": hf_snapshots("docling-project/docling-layout-heron-onnx")},
            "docling tableformer": {"snapshots": hf_snapshots("docling-project/docling-models")},
            "inklight small models": tree(Path(os.environ.get("EVAL_SMALL_MODELS", "missing"))),
        },
        "hardware": {
            "platform": platform.platform(),
            "cpu": cpu[0].strip() if cpu else platform.processor(),
            "cores": os.cpu_count(),
            "memory_gb": memory,
            "gpu": "none used (CPU only)",
        },
        "configs": {p.name: p.read_text(encoding="utf-8") for p in sorted(config_dir.glob("*.toml"))},
    }
    out.write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(json.dumps(record["build"], indent=1))


if __name__ == "__main__":
    main()
