# Evaluation: general documents in English, Arabic and mixed language

This report covers what Inklight's GitHub development build does on letters, contracts, reports, forms,
certificates, invoices and receipts, in English, Arabic and mixed language, as digital PDFs, scans and
photographs. Every number comes from `bench/usecases/` and the raw outputs are in
[`bench/results/usecases/`](../bench/results/usecases/). It is a small automated evaluation; no person reviewed
anything, and no human timing exists.

| | |
|---|---|
| Builds compared | **P0** = `6b4cc12` (frozen wheel `9318449b…`) · **first access** = uncommitted source, reconstructed as `8c54921` + a [patch](../bench/results/usecases/provenance/README.md) whose re-run reproduces the stored outputs (a behavioural reconstruction, not the original bytes) · **rerun** = `8c54921`; `2709d33` changes only the wording of unsupported-request answers |
| OCR | Indra OCR 1.1.2, pinned model snapshot `bd02167f…` (same files for both builds) |
| Optional models | reader `Xenova/distilbert-base-cased-distilled-squad` @ `bdbb0a5e…`, embedder `Xenova/bge-small-en-v1.5` @ `ea104dac…`, writer `HuggingFaceTB/SmolLM2-135M-Instruct` (not installed, `use_writer = false`) |
| Modes | `auto` = optional models when installed (the default); `rules` = no models |
| Machine | Windows 11, AMD Zen 4 laptop CPU, Python 3.12 (P0) / 3.13 (final) |
| Unit tests | 617, separate from everything below |

## The documents

90 documents in four splits. Groups keep translations, one company's receipts, a contract and a synthetic
template in one split. Full list with sources and licences: [`bench/usecases/corpus.json`](../bench/usecases/corpus.json).

| Split | Docs | Role | Independence |
|---|---|---|---|
| dev | 35 | failures here were diagnosed and fixed | none: tuned on |
| reserved | 30 | evaluated once, first access logged before reading | **independent for the first run only** (`first-access-res-*`). Three fixes it prompted were made afterwards (below), so the rerun on `8c54921` (`final-res-*`) is not independent |
| fresh | 10 | added to check those fixes on unseen documents, expectations written first | independent for its first run (`first-access-fresh-auto`); it prompted two more fixes, so its rerun (`final-fresh-*`) is not independent |
| fresh2 | 15 | 15 new genuine documents ([selection and exclusions](../bench/results/usecases/provenance/fresh2-selection.md)) (2025 UN letters and a 1984 scan in English and Arabic, two CUAD contracts, IRS W-8BEN, Arabic Wikipedia "الإسكندرية", three CORU receipts from new companies), with answerable and unanswerable questions; expectations committed (`6c1659c`) before any run | **independent for its first run** (`fresh2-first-access-*`): the build under test was frozen first (`d012e07`) |

**Provenance.** The first-access runs record Git HEAD `6b4cc12`, but they ran from modified, uncommitted source.
That source was reconstructed from the session transcript as `8c54921` plus a patch removing the later fixes.
Re-running the reconstruction reproduced every stored answer, confidence, outcome and ingestion hash; only the export
file path differs. This shows the same behaviour on these documents; it does not recover the original source bytes
or environment.
Details: [`provenance/README.md`](../bench/results/usecases/provenance/README.md).

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
- OCR is not degraded by the models: they do not touch it, and the text is identical.
- The English-only models degrade **two Arabic stages, retrieval and answering**:
  - Retrieval: the embedder pushed the right Arabic document down 19 times while pulling it up 6.
  - Answering: the reader turned correct Arabic passages into wrong spans.
- Both models help English.

The fix routes by language instead of removing the models:
- **Arabic queries use keyword search.**
- **The reader is not asked about Arabic questions or Arabic evidence.**
- Every skip is stated in the result's `checks`.

`8c54921`, dev split (tuned on, not independent):

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

### Questions with a cited source — reserved split, models on

The first-access run and P0 are the independent comparison. The rerun follows fixes prompted by these documents.

| Language | Run | correct | correct·flagged | wrong·flagged | silent wrong | n |
|---|---|---|---|---|---|---|
| English | P0 | 24 | 1 | 9 | 8 | 42 |
| English | first access | **29** | 1 | 4 | 8 | 42 |
| English | rerun `8c54921` | 29 | 1 | 4 | 8 | 42 |
| Arabic | P0 | 0 | 1 | 22 | 0 | 23 |
| Arabic | first access | 0 | **11** | 12 | 0 | 23 |
| Arabic | rerun `8c54921` | 0 | 11 | 12 | 0 | 23 |
| Mixed | P0 | 4 | 1 | 4 | 6 | 15 |
| Mixed | first access | 4 | 1 | 2 | **8** | 15 |
| Mixed | rerun `8c54921` | 4 | 1 | 4 | 6 | 15 |

- **Arabic answers are never shown as reliable.** They are whole sentences chosen by shared words, and every one carries a "check the cited passage" flag. 11 of 23 were right and 0 were silently wrong.
- **Mixed-language silent errors.** At first access they rose from 6 to 8, both new ones on the synthetic salary letter. The rerun flags those two (rule answers sharing under half the question's words), back to 6. That fix was prompted by these documents, so the 6 is not an independent result.
- **Retrieval and answering are separate stages.** Retrieval had the answer for 40/42 English, 22/23 Arabic and 12/15 mixed questions; most wrong answers fail at the answering stage.
- **Citations.** When the answer is right, the cited passage contains it 27/30 (English), 11/11 (Arabic) and 5/5 (mixed).

Fresh split (10 documents, unseen at first access): English 8/8 correct for P0, first access and rerun. Arabic
0/14 (P0) → 9/14 correct·flagged at first access, also 9/14 on the rerun.

Dev split, models on, P0 → `8c54921`: English 20/53 → 25/53, Arabic 4/36 → 17/36 (6 of them correct without a flag, all
from labelled fields on the synthetic invoice), mixed 5/12 → 5/12.

### First stage where a wrong answer went wrong (reserved, models on; identical for first access and rerun)

| | ingestion/OCR | request parsing | retrieval | answering |
|---|---|---|---|---|
| English | 1 | 1 | 1 | 9 |
| Arabic | 1 | 0 | 0 | 11 |
| Mixed | 2 | 0 | 1 | 7 |

The answering stage dominates. For Arabic it is a rule-based sentence choice with no model that reads Arabic.

### Summaries (extractive)

| Split | Language | Recognised as a summary (P0 → first access; rerun) | Key facts covered | Quoted sentences found verbatim in the document |
|---|---|---|---|---|
| reserved | English | 16/16 → 16/16; 16/16 | 25/48 → 25/48; 25/48 | 76/76 |
| reserved | Arabic | 0/9 → **9/9**; 9/9 | 1/27 → **17/27**; 17/27 | 45/45 |
| reserved | mixed | 5/5 → 5/5; 5/5 | 7/15 → 7/15; 7/15 | 22/22 |
| fresh | Arabic | 0/6 → **6/6**; 6/6 | 1/18 → **11/18**; 11/18 | 30/30 |

Summaries quote the document, so they cannot invent text; they can miss key facts. The quoted text is the stored OCR,
misreadings included.

### Missing information (the document does not contain the answer)

| Split, run | English | Arabic | Mixed |
|---|---|---|---|
| reserved, P0 | declined or flagged 8/16 | 9/9 | 2/5 |
| reserved, first access | 8/16 | 9/9 | 1/5 |
| reserved, rerun `8c54921` | 8/16 | 9/9 | 2/5 |
| fresh, first access and rerun | 4/4 | 6/6 | — |
| dev, `8c54921` | 14/19 | 12/12 | 4/4 |

Half of the English questions about facts a document lacks still get an unflagged sentence on the reserved split.
None of these runs ever *declined*: every "declined or flagged" above is a low-confidence answer, not a statement
that the document lacks the fact.

### Missing information: "not found" (`d012e07`)

**What changed.** A question about a subject the documents in scope never mention now gets
"Not found: this document does not mention “IBAN”." instead of a nearby sentence. (Later builds say "I couldn't find
supporting evidence for “IBAN” in the processed text of this document", because OCR can miss words; the decision
is the same.) Each specific word of the question
is looked up in the full-text index, with English synonyms and Arabic equivalents.

**What it will not do.** It does not decline when:
- the only missing words are generic ("number", "date") or verbs ("sent")
- the missing word is the document's own type ("form")
- the missing word is an everyday word with many paraphrases ("price", "due", "phone")
- the documents may be in another language and the word has no known equivalent
- a document in scope is not indexed yet

Design and tuning used the dev split only. The fresh2 split was then run once, on the frozen build and on the
build before it.

**fresh2, first access, models on** (`6c1659c` → `d012e07`; 15 documents, all genuine). Every unanswerable question
is listed with its outcome in `fresh2-first-access-*.json`.

| Unanswerable question | English | Arabic | Mixed |
|---|---|---|---|
| subject never mentioned (`absent_subject`): declined "not found" | 0 → **10** of 11 | 0 → **6** of 6 | 0 → **2** of 2 |
| … answered silently | 3 → 1 | 0 → 0 | 1 → 0 |
| subject mentioned, value not given (`present_subject`): declined | 0 → 0 of 6 | 0 → 0 of 3 | 0 → 1 of 2 |
| … answered silently | 4 → 4 | 1 → 1 | 1 → 1 |
| **Answerable questions declined** | 0 → **0** of 25 | 0 → **0** of 11 | 0 → **0** of 6 |
| Answerable questions correct | 23 → 23 of 25 | 2 → 2 of 11 | 3 → 3 of 6 |

- **Silent answers to unanswerable questions: 10 → 7 of 30.** No answerable question changed outcome.
- **Still silent where the subject is never mentioned:**
  - "What is the termination fee?" over a maintenance agreement is answered "$40 per month". "Termination" is not a
    listed subject, and "fee" is an everyday word.
- **Not handled: the subject is mentioned but the value is not.** 6 of 11 such questions are still answered
  silently, unchanged. Examples:
  - "On what date will the open debate be held?" → the letter's own date.
  - "Which towns were struck on 25 February?" → governorates named in another sentence.
  - "What is the beneficial owner's name?" on a blank form → a line of the form.
- **One decline was right for the wrong reason.**
  - Question: "What is the VAT amount?" on the Lulu receipt (`present_subject`, so declining is correct).
  - The answer says the receipt does not mention VAT. In fact its Arabic line about VAT was not read clearly by OCR.
- **Request parsing.** "كم عدد طلاب جامعة الإسكندرية؟" ("how many students…") is read as a document count by both
  builds. This is unrelated to this change.
- **Rules only** (`d012e07`, no models): the same declines. Answerable English questions are correct 16 of 25,
  against 23 of 25 with models.
- **Dev split** (tuned on), `6c1659c` → `d012e07`, models on: declined English 0 → 13 of 19, Arabic 0 → 5 of 12,
  mixed 0 → 4 of 4. Silent English answers 5 → 3. Answerable outcomes are identical, 0 of 101 declined.
- **Harness note.** The first fresh2 attempt of each build crashed in the harness before writing any result. The
  cause was a document with no expected fields. The harness was fixed, nothing in Inklight changed, and the runs
  were repeated. All six accesses are in `reserved-access.log`.

### Fields, library tasks, export

- **Library tasks**:

  | Split | P0 | First access | Rerun `8c54921` |
  |---|---|---|---|
  | reserved | 2/9 | **5/9** | 4/9 |
  | fresh | 1/4 | **4/4** | 3/4 |
  | dev (tuned on) | 1/9 | — | 6/9 |

  - Reserved at first access, pass: find the document (Arabic), compare letters, filter, both unsupported refusals.
  - Reserved at first access, fail: find (English, "which document *reports*…" read as a document type), count and sum of receipts (one receipt unclassified, totals misread on photos), export (one OCR-misread invoice number).
  - Lost on the rerun:
    - Reserved, compare letters: "Identical letters dated…" is no longer read as a letter date, because "Letter dated" now dates only a letter's own title line.
    - Fresh, find (English): the request comes back `partial` on both runs ("credentials", "representative" and "Brazil" are not applied). At first access the English report came first. On the rerun its Arabic translation came first, because the Arabic cue fix now classifies it as a report too.
- **Unsupported requests** ("translate", "sign", "email"): P0 answered all with `succeeded`; final returns `unsupported` with the reason, 5/5.
- **Fields**:
  - Synthetic Arabic invoice and certificate (dev, `8c54921`): 11/12 correct.
  - Genuine Arabic UN letters, letter dates (reserved): 2/4 at first access and on the rerun.
  - At first access, these were silently wrong; all are correct on the rerun (the Arabic report dates with a flag):
    - Two synthetic Arabic leases: a parenthesised restatement of the rent read as negative (one reserved, one fresh).
    - Two fresh Arabic reports: dated by a letter cited in their body.
  - Full tables per language, type and genuine/synthetic: `python -I bench/usecases/summarize.py bench/results/usecases/final-res-auto.json`.
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
- questions whose subject is mentioned but whose value is not (6 of 11 still answered silently on fresh2)
- genuine Arabic forms, certificates and invoices
- documents longer than 36 pages (the longest tested)
- tables beyond invoice line items
- UI use by people
- Arabic answering with any model (none suitable is shipped)
