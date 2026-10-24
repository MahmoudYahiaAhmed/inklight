# Evaluation: general documents in English, Arabic and mixed language

This report covers what Inklight's GitHub development build does on letters, contracts, reports, forms,
certificates, invoices and receipts, in English, Arabic and mixed language, as digital PDFs, scans and
photographs. Every number comes from `bench/usecases/` and the raw outputs are in
[`bench/results/usecases/`](../bench/results/usecases/). It is a small automated evaluation; no person reviewed
anything, and no human timing exists.

| | |
|---|---|
| Builds compared | **P0** = `6b4cc12` (frozen wheel `9318449b…`) · **final** = `8c54921` code, measured; `2709d33` changes only the wording of unsupported-request answers |
| OCR | Indra OCR 1.1.2, pinned model snapshot `bd02167f…` (same files for both builds) |
| Optional models | reader `Xenova/distilbert-base-cased-distilled-squad` @ `bdbb0a5e…`, embedder `Xenova/bge-small-en-v1.5` @ `ea104dac…`, writer `HuggingFaceTB/SmolLM2-135M-Instruct` (not installed, `use_writer = false`) |
| Modes | `auto` = optional models when installed (the default); `rules` = no models |
| Machine | Windows 11, AMD Zen 4 laptop CPU, Python 3.12 (P0) / 3.13 (final) |
| Unit tests | 617, separate from everything below |

## The documents

75 documents in three splits. Groups keep translations, one company's receipts, a contract and a synthetic
template in one split. Full list with sources and licences: [`bench/usecases/corpus.json`](../bench/usecases/corpus.json).

| Split | Docs | Role | Independence |
|---|---|---|---|
| dev | 35 | failures here were diagnosed and fixed | none: tuned on |
| reserved | 30 | evaluated once, first access logged before reading | **independent for the first run** (`first-access-*`). Two fixes it prompted were made afterwards (below); later reserved runs are not independent for those |
| fresh | 10 | added to check those fixes on unseen documents, expectations written first | independent for its first run; it prompted two more fixes, confirmed only by regression tests |

| Kind | Genuine | Synthetic (**labelled**) |
|---|---|---|
| English | UN letters and reports (digital 2022–24, typewritten scans 1974–1990), CUAD contracts, IRS W-9 / W-4, FUNSD forms, INV-CDIP invoice scans, CORU receipts | Voxel51 invoice images |
| Arabic | the same UN documents in Arabic (digital and scans), Arabic Wikipedia "مصر", "القاهرة" | certificate, tax invoice, two leases (digital, photo-like, scan-like) |
| Mixed | CORU receipts from Egypt (Arabic and English) | bilingual membership form, bilingual salary letter |

**Gaps (no openly licensed data found):** genuine Arabic forms, certificates, invoices and contracts (synthetic stand-ins
are used and labelled); handwriting.

## Do the optional models harm Arabic?

The hypothesis was "OCR worked well before the small language models were integrated". It was tested by stage, on
identical documents and settings (dev split, P0 build), with model calls counted from ONNX Runtime itself.

| Stage | Comparison | English | Arabic | Mixed |
|---|---|---|---|---|
| OCR and layout | models off vs on | identical text (same stored text hash per document; OCR does not use the models) | identical | identical |
| Retrieval, right document in the top 3 (library-wide) | keyword vs hybrid (embedder) | 37 → **42** of 53 | 29 → **20** of 36 | 7 → 5 of 12 |
| Answering, **same passages replayed** | reader off vs on | 16 → **20** of 53 | 17 → **3** of 36 | 4 → 4 of 12 |
| Writer | — | not loaded in any run (0 calls) | | |

**Conclusion.**
- OCR is not degraded by the models: they do not touch it.
- The English-only models do degrade Arabic. The reader turned correct Arabic passages into wrong spans, and the embedder pushed the right Arabic document down 19 times while pulling it up 6.
- Both models help English.

The fix routes by language instead of removing the models:
- **Arabic queries use keyword search.**
- **The reader is not asked about Arabic questions or Arabic evidence.**
- Every skip is stated in the result's `checks`.

Final build, dev split:

| | models off | models on | models on, passages replayed |
|---|---|---|---|
| Arabic answers correct | 17/36 | 17/36 | 17/36 |
| English answers correct | 20/53 | 25/53 | 25/53 |
| Reader / embedder calls during QA | 0 / 0 | 191 / 123 | 168 / 0 |

A larger model was not tried: the failure is the language coverage of these two models, and bypassing them on
Arabic already restores the rules result. A multilingual reader would have to beat 17/36 on dev and the reserved
set before it could be adopted.

## Results by language and task

Outcomes are kept apart:
- **correct**
- **correct·flagged**: correct, but marked for review
- **wrong·flagged**: wrong, but marked for review
- **silent wrong**

"Flagged" means a low-confidence warning, a `partial` state, or a confidence under 0.3.

### Questions with a cited source — reserved split, first access, models on

| Language | Build | correct | correct·flagged | wrong·flagged | silent wrong | n |
|---|---|---|---|---|---|---|
| English | P0 | 24 | 1 | 9 | 8 | 42 |
| English | final | **29** | 1 | 4 | 8 | 42 |
| Arabic | P0 | 0 | 1 | 22 | 0 | 23 |
| Arabic | final | 0 | **11** | 12 | 0 | 23 |
| Mixed | P0 | 4 | 1 | 4 | 6 | 15 |
| Mixed | final | 4 | 1 | 2 | 8 | 15 |

- **Arabic answers are never shown as reliable.** They are whole sentences chosen by shared words, and every one carries a "check the cited passage" flag. 11 of 23 were right and 0 were silently wrong.
- **Mixed-language silent errors rose from 6 to 8.** Both new ones are on the synthetic salary letter.
- **Retrieval and answering are separate stages.** Retrieval had the answer for 40/42 English, 22/23 Arabic and 12/15 mixed questions; most wrong answers fail at the answering stage.
- **Citations.** When the answer is right, the cited passage contains it 27/30 (English), 11/11 (Arabic) and 5/5 (mixed).

Fresh split, first access (unseen; 10 documents): English 8/8 correct for both builds; Arabic 0/14 → 9/14 correct·flagged.

Dev split, models on, P0 → final: English 20/53 → 25/53, Arabic 4/36 → 17/36 (6 of them correct without a flag, all
from labelled fields on the synthetic invoice), mixed 5/12 → 5/12.

### First stage where a wrong answer went wrong (reserved, final, models on)

| | ingestion/OCR | request parsing | retrieval | answering |
|---|---|---|---|---|
| English | 1 | 1 | 1 | 9 |
| Arabic | 1 | 0 | 0 | 11 |
| Mixed | 2 | 0 | 1 | 7 |

The answering stage dominates. For Arabic it is a rule-based sentence choice with no model that reads Arabic.

### Summaries (extractive)

| Split | Language | Recognised as a summary (P0 → final) | Key facts covered | Quoted sentences found verbatim in the document |
|---|---|---|---|---|
| reserved | English | 16/16 → 16/16 | 25/48 → 25/48 | 76/76 |
| reserved | Arabic | 0/9 → **9/9** | 1/27 → **17/27** | 45/45 |
| reserved | mixed | 5/5 → 5/5 | 7/15 → 7/15 | 22/22 |

Summaries quote the document, so they cannot invent text; they can miss key facts. The quoted text is the stored OCR,
misreadings included.

### Missing information (the document does not contain the answer)

| Split | English | Arabic | Mixed |
|---|---|---|---|
| reserved, final | declined or flagged 8/16 | 9/9 | 2/5 |
| dev, final | 14/19 | 12/12 | 4/4 |

Half of the English questions about facts a document lacks still get an unflagged sentence on the reserved split.

### Fields, library tasks, export

- **Library tasks** (reserved, final):
  - Pass: find the document (Arabic), filter, both unsupported refusals.
  - Fail: find (English, "which document *reports*…" read as a document type), compare ("Identical letters dated" is not read as a letter date), count and sum of receipts (one receipt unclassified, totals misread on photos), export (one OCR-misread invoice number).
  - Dev: 6/9 (P0 1/9). Fresh: 3/4 (P0 1/4).
- **Unsupported requests** ("translate", "sign", "email"): P0 answered all with `succeeded`; final returns `unsupported` with the reason, 5/5.
- **Fields**: on the synthetic Arabic invoice and certificate, 11/12 correct. On genuine Arabic UN letters, letter dates 2/4 (reserved). Full tables per language, type and genuine/synthetic: `python -I bench/usecases/summarize.py bench/results/usecases/final-res-auto.json`.
- **Review export**: every custom field of every document was exported (51 rows reserved, 62 dev), with Arabic values unchanged.
- **Regression check** on the earlier synthetic benchmark (`bench/run.py`): identical metrics for P0 and final (request fidelity 1.000, extraction 0.967, QA 0.917; that QA value is the same for both builds today).

### Latency and model activity (final, models on)

- Questions: median 0.02–0.03 s, maximum 0.30 s.
- Ingestion with OCR: dev 69 s for 35 documents (2,300 OCR model calls), reserved 35 s for 30.
- Model calls during reserved QA: reader 155, embedder 106, writer 0.

## Fixes made after the reserved and fresh runs

These were found on held-out documents, so those documents no longer confirm them. Each fix has a regression test.

| Found on | Failure | Fix |
|---|---|---|
| reserved | "(8,000 ج.م)" after a written amount read as −8,000 | parentheses after a written-out amount or an Arabic word restate it |
| reserved | "has received a letter dated…" in a report taken as the report's date | "Letter dated" dates a document only when it is a letter and starts the title line |
| reserved | an English question about a missing fact answered by a weakly matching sentence, unflagged | rule answers sharing under half the question's words are flagged |
| fresh | the Arabic credentials report classified as a letter | Arabic cue "تقرير الأمين العام", parity with "report of the Secretary-General" |
| fresh | the scan of the second synthetic lease gave "−5,000" | as above |

## What is not measured

- handwriting
- genuine Arabic forms, certificates and invoices
- documents longer than 36 pages (the longest tested)
- tables beyond invoice line items
- UI use by people
- Arabic answering with any model (none suitable is shipped)
