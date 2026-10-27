"""The CI distribution check: runtime code and assets pass, documents, data and repository folders fail."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "check_dist.py"
spec = importlib.util.spec_from_file_location("check_dist", SCRIPT)
check_dist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_dist)

GOOD_WHEEL = [
    "inklight/__init__.py",
    "inklight/py.typed",
    "inklight/server/static/index.html",
    "inklight/server/static/js/main.js",
    "inklight/server/static/css/app.css",
    "inklight/server/static/logo.svg",
    "inklight/backends/ocr/LICENSE",
    "inklight-0.3.0.dist-info/METADATA",
    "inklight-0.3.0.dist-info/licenses/NOTICE",
]


def test_runtime_files_pass():
    assert check_dist.wheel_problems(GOOD_WHEEL) == []
    sdist = ["inklight-0.3.0/" + n for n in ("pyproject.toml", "PKG-INFO", "README.md", "LICENSE", "hatch_build.py")]
    sdist += ["inklight-0.3.0/src/" + n for n in GOOD_WHEEL if n.startswith("inklight/")]
    assert check_dist.sdist_problems(sdist) == []


def test_documents_data_and_repository_folders_fail():
    bad = [
        "inklight/samples/invoice.pdf",
        "inklight/server/static/screenshot.png",
        "inklight/library.db",
        "inklight/notes.ipynb",
        "inklight/models/det.onnx",
        "inklight/__pycache__/cli.cpython-312.pyc",
        "inklight/tests/test_x.py",
        "examples/documents/a.pdf",
        "evaluation/results/run.json",
    ]
    assert len(check_dist.wheel_problems(bad)) == len(bad)
    sdist = [
        "inklight-0.3.0/tests/test_x.py",
        "inklight-0.3.0/bench/run.py",
        "inklight-0.3.0/docs/images/a.png",
        "inklight-0.3.0/config.example.toml",
        "inklight-0.3.0/src/inklight/data/library.db",
    ]
    assert len(check_dist.sdist_problems(sdist)) == len(sdist)
