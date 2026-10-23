"""Peak memory of typical single-process runs (each in a fresh interpreter)."""

import subprocess
import sys
import tempfile

SNIPPET = """
import sys
sys.path.insert(0, {root!r})
from bench.run import peak_rss_mb
from inklight import DocumentAgent
from inklight.config import load_settings
agent = DocumentAgent(load_settings(home={home!r}, models={{"brain": {brain!r}}}))
agent.add([{docs!r}])
agent.ask("What was revenue growth in Q2?")
agent.ask("Find all invoices above $5,000")
print(peak_rss_mb())
"""

if __name__ == "__main__":
    import pathlib

    root = str(pathlib.Path(__file__).resolve().parents[1])
    docs = str(pathlib.Path(root) / "examples" / "documents")
    for brain in ("rules", "auto"):
        home = tempfile.mkdtemp(prefix="inklight-mem-")
        code = SNIPPET.format(root=root, home=home, brain=brain, docs=docs)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)  # noqa: S603
        print(f"{brain}: peak RSS {out.stdout.strip().splitlines()[-1]} MB (8 demo documents + 2 tasks)")
