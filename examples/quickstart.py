"""Quickstart: python examples/quickstart.py [folder]

Regenerate the demo documents first with:  python tests/factory.py examples/documents
"""

import sys
from pathlib import Path

from inklight import DocumentAgent

folder = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "documents")


def main() -> None:
    agent = DocumentAgent(allow_write=True, output_dir=Path(__file__).parent / "out")
    report = agent.add(folder)
    print(f"Indexed {len(report.documents)} documents ({report.pages} new pages) in {report.seconds:.1f}s")

    result = agent.ask("Extract the invoice number, date, and total", files=[folder / "invoice_acme.pdf"])
    print("\n", result.answer)
    print("source:", result.sources[0].cite(), result.sources[0].bbox)

    for request in [
        "Find every contract that expires within 90 days",
        "Read all these invoices and create a CSV of vendor, date, tax, and total",
        "What was revenue growth in Q2?",
    ]:
        result = agent.ask(request)
        print(f"\n▶ {request}  [{result.state.value}, confidence {result.confidence:.2f}]")
        print(result.answer)
        for warning in result.warnings:
            print("  ⚠", warning)


if __name__ == "__main__":  # required on Windows/macOS: Indra may use worker processes
    main()
