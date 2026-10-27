"""Quickstart: python examples/quickstart.py

Reads three sample documents from examples/documents (see examples/README.md) into your library and shows text,
tables, a field with its source, and search. Tables need the structure extra: pip install "inklight[structure]".
"""

from pathlib import Path

from inklight import DocumentAgent

DOCS = Path(__file__).parent / "documents"


def main() -> None:
    with DocumentAgent(structure={"engine": "inklight"}) as agent:
        print(agent.text(DOCS / "invoice_initech_scan.png")[:400], "…\n")

        for table in agent.tables(DOCS / "suppliers.pdf"):
            print("table on page", table["page"])
            for row in table["rows"]:
                print("  ", row)

        record = agent.extract([DOCS / "registration-card-turned.pdf"], fields=["company name", "tax office"])[0]
        for name, value in record.fields.items():
            where = f"page {value.source.page}, box {value.source.bbox}" if value.source else "not found"
            print(f"\n{name}: {value.value!r} ({where})")
            if value.warning:
                print("  check:", value.warning)

        for hit in agent.search("Golden Palm"):
            print("\nfound in", hit.source.name, "page", hit.source.page)


if __name__ == "__main__":  # required on Windows and macOS: OCR may use worker processes
    main()
