# Examples

Small synthetic documents to try Inklight on. They are made up (no real company, person or invoice) and are part of
this repository only: `pip install` does not install them, and Inklight never adds them to a library by itself.

| File | What it shows |
|---|---|
| `documents/registration-card-turned.pdf` | A synthetic company registration card scanned sideways: OCR on a turned page, fields read at their labels and table cells (company name, registration number, tax office). |
| `documents/suppliers.pdf` | A sheet with two supplier tables: table extraction, and a field with several candidates. |
| `documents/invoice_initech_scan.png` | A scanned invoice image: OCR on a photo-like page. |
| `documents/invoice_acme.pdf`, `invoice_globex.pdf` | Digital invoices with a text layer. |
| `documents/contract_cloud.pdf`, `contract_office.pdf` | Short contracts with dates and parties. |
| `documents/report_q1.pdf`, `report_q2.pdf` | Two quarterly reports, for comparisons across documents. |
| `documents/memo_untrusted.pdf` | A memo that contains instructions aimed at an AI ("ignore previous instructions…"). Inklight reads it as text and flags it; it never follows it. |
| `schemas/invoice.json` | A field schema for `inklight extract --schema` and `agent.extract(..., schema=...)`. |
| `quickstart.py` | The Python API on these files: text, tables, fields with their sources, search. |

## Get them

From a checkout of the repository they are already here. With Inklight installed from pip, download one file:

```bash
curl -LO https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/examples/documents/suppliers.pdf
```

(on Windows PowerShell, type `curl.exe`), or clone the repository to get them all.

## Run

```bash
inklight extract examples/documents/registration-card-turned.pdf --fields "company name, tax office"
python examples/quickstart.py
```

Each command reads the files into your library (`~/.inklight`, or `INKLIGHT_HOME`). Remove them again with
`inklight remove <id>` (ids from `inklight docs`), or try them in a separate library:

```bash
INKLIGHT_HOME=/tmp/inklight-try inklight serve
```

## Regenerate

`python tests/factory.py examples/documents` writes the invoices, contracts, reports and memo again.
`registration-card-turned.pdf` and `suppliers.pdf` come from `bench/usecases/make_synthetic.py`.
