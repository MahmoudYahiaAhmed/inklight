"""A type word in a request ("receipts", "invoices") must not silently drop documents the classifier could not type.

Found by re-running the CORD receipt benchmark on 0.3 (evaluation/REPORT.md): 57 of 60 receipt photos were typed
"unknown", 3 "receipt", and "Find receipts above Rp 39,000" answered from those 3 as complete. A document of unknown
type may be what the request names, so it stays in scope and the answer says so.
"""

from __future__ import annotations

from inklight import DocumentAgent

from .conftest import make_settings

TYPED = "RECEIPT\nKedai Kopi\nCashier: 12\nSubtotal 41,000\nTotal Rp 45,000\nThank you for your purchase\n"
# Below the classifier's threshold, but with a receipt's vocabulary ("cash", "change"), as on most CORD photos
UNTYPED = [
    "Warung Nasi\nTotal 52,000\nCash 60,000\nChange 8,000\n",
    "Bakso Pak Min\nTotal 61,500\nCash 70,000\n",
    "Toko Roti\nSub Total 12,000\n",  # no receipt word at all, only a total line
    "Memo\nPlease file the attached papers by Friday. Budget 90,000\n",  # unknown, and nothing like a receipt
]


def _agent(tmp_path):  # noqa: ANN202
    files = []
    for n, text in enumerate([TYPED, *UNTYPED]):
        f = tmp_path / f"r{n}.txt"
        f.write_text(text, encoding="utf-8")
        files.append(f)
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    agent.add(files)
    return agent


def test_documents_of_unknown_type_stay_in_scope_with_a_warning(tmp_path):
    with _agent(tmp_path) as agent:
        types = {d.name: d.doc_type for d in agent.library.documents()}
        assert types["r0.txt"] == "receipt" and {types[f"r{n}.txt"] for n in (1, 2, 3, 4)} == {"unknown"}, types
        res = agent.ask("Find receipts above Rp 39,000", save=False)
        names = {r.name for r in res.records}
        assert {"r0.txt", "r1.txt", "r2.txt"} <= names and not {"r3.txt", "r4.txt"} & names, res.answer
        assert any("unknown type were included" in w for w in res.warnings), res.warnings
        assert any("1 document(s) of unknown type were left out" in w for w in res.warnings), res.warnings
        assert res.state.value == "partial", res.state  # the scope is a guess, so the result is not complete


def test_only_still_restricts_to_the_typed_documents(tmp_path):
    with _agent(tmp_path) as agent:
        res = agent.ask("Find only the receipts above Rp 39,000", save=False)
        assert {r.name for r in res.records} == {"r0.txt"}, res.answer
        assert any("unknown type" in w for w in res.warnings), res.warnings
