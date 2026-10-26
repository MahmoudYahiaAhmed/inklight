# Agent-run workflow evaluation (October 2026)

**Can a person finish real document tasks with Inklight?** On this set — mostly scanned Egyptian commercial
registers, tax cards and VAT certificates, plus a bilingual NDA, an Arabic service agreement, receipt photos and UN
letters — **no**. In 76 scored task runs Inklight's first answer never answered the question correctly (one was a
justified "not in the document"), and after up to three follow-ups it completed 2 tasks on its own (one correct abstention, one answer after a clarification). Every other
correct deliverable (70 of 76) exists because the person read the page image and wrote or fixed the answer. Turning
on Docling structure did not change that. The results, failures and the harness are below; private documents and
their content never leave the evaluation machine.

Raw evidence (pseudonymous ids and numbers only): [`bench/results/agent_eval/`](../bench/results/agent_eval/).
Harness: [`bench/agent_eval/`](../bench/agent_eval/).

> **Amendment AM-1 and a bounded improvement cycle follow the original report** (see
> [Amendment AM-1](#amendment-am-1-reconciliation-corrections-diagnosis-and-a-bounded-improvement-cycle)). The
> sections up to "Reproduce" are the original evaluation of `3f1ec75`, kept as written; where AM-1 corrects a count
> or a grade, the correction is stated there, with the original. The short answer after the cycle: the corrected
> build (`d9e0496`) fixes the three demonstrated answer defects and gives rotated pages structure, but task
> completion on this workload did not improve (structure off 1 of 38 → 1 of 38; structure on 0 of 38 → 0 of 38, under
> the same strict grading). This is an agent-run evaluation; no human productivity claim is made.

## What ran

| | |
|---|---|
| System under test | commit `3f1ec75`, wheel `inklight-0.1.1.dev0` sha256 `4df7e42a…`, installed clean with `[structure]` into its own venv and used only through the public CLI (`inklight ask/extract/search/show`) |
| Models | Indra OCR 1.1.2 snapshot `bd02167f…`; Docling 2.142.1 with Heron ONNX `40bde044…` and TableFormer `fc0f2d45…`; small models (reader + embedder, 6 files, 100.7 MB) for the subset only |
| Configurations | **A** structure off · **B** Docling structure, TableFormer accurate · **B-models** B plus the optional small models (subset). `brain = "rules"` in A and B, no downloads |
| Machine | Windows 11, AMD Ryzen 7 8700F (16 threads), 31.6 GB, CPU only |
| Documents | 25 documents, 102 pages, 16 groups: 17 private business documents supplied by the user (Arabic scans, many rotated; one bilingual NDA; one Arabic service agreement with a text layer), 4 public receipt photos (CORU dataset, MIT) and 4 public UN Security Council letters (Arabic and English). Plus one synthetic control PDF. No near-duplicates (dHash). |
| Tasks | 38 scored tasks (6 development, 32 reserved), written with frozen references before any run: field lookup, tables, comparisons across documents, calculations, summaries, search, exports, ambiguous requests, facts absent from the document. Requests in Egyptian dialect, formal Arabic and English. Outside the score: 5 questions on the known tax-card control and 4 Alpha Ltd / Beta Ltd ambiguity questions. |
| Roles | separate agents for task author, user (one per batch, 4 actions per task, could open page images like a person opening the PDF), and judges (6, blinded to configuration, checked values on the page images). Deterministic checks (`check.py`) ran beside the judges. |
| Boundary | references, briefs, configs and harness hashed in `freeze.json` before the reserved split was opened; access logged. Only change after the freeze: `ik.py` printing UTF-8 (logged with its new hash; it changed no command or result). Harness failures are kept in `harness_log.txt`. |

## Results

Outcome of each task run, as handed over (judges' labels; one label made consistent across judges, see
[Adjudication](#evaluation-problems-and-adjudication)):

| | A (structure off) | B (Docling) |
|---|---|---|
| Runs | 38 | 38 |
| Completed by the tool (correct, correct after clarification, correct abstention) | **1** | **1** |
| Correct only after the person's manual correction | 35 | 35 |
| Honest partial / wrong with a relevant warning (person's own transcription errors) | 1 | 1 |
| Wrong abstention (values on the page) | 1 | 1 |
| Silent wrong / overstated completion as handed over | 0 | 0 |
| Technical failure | 0 | 0 |

The tool's **first answer**, judged on its own:

| First attempt | A | B |
|---|---|---|
| correct | 0 | 0 |
| partially correct | 8 | 10 |
| wrong | 14 | 15 |
| abstained (all but one unjustified) | 10 | 8 |
| failed (error, empty table) | 6 | 5 |
| asked for clarification | 0 | 0 |

"Silent wrong 0" describes the deliverables, not the tool: the person checked every answer against the page.
A person who accepted the tool's first answer would have handed over an incomplete, wrong or empty result in 75 of
76 runs.
That is what the controls (no manual correction) show: 4 of 10 control answers were wrong without a warning
that described the error.

By slice (A / B, runs completed by the tool): Arabic 0/11, 0/11 · English 1/3, 0/3 · mixed-language tasks 0/24,
1/24 · scans and photos 0/27, 0/27 · digital 1/11, 1/11. Commercial registers 0/9, tax cards 0/3, VAT 0/2,
receipts 0/6, contracts 0/6 and 1/6, letters 1/6 and 0/6, multi-type 0/6. By task type nothing exceeds 1 of 7. The full
table with denominators is in [`aggregate.md`](../bench/results/agent_eval/aggregate.md).

| Also measured | A | B |
|---|---|---|
| Citations supporting the claim (judged) | yes 2 · partly 15 · no 12 · none 9 | yes 1 · partly 20 · no 7 · none 10 |
| Warnings describing the actual problem | 6 of 38 | 16 of 38 |
| Export tasks with a usable tool-written file | 0 of 4 (all 4 handed-over files were typed by the person) | 0 of 4 |
| Actions per task (mean, budget 4) | 2.29 | 2.42 |
| Clarifying questions asked by the tool | 0 | 0 |

### Regression controls (outside the score, single action, no manual correction)

| | A | B |
|---|---|---|
| Alpha Ltd / Beta Ltd (synthetic, digital) — 4 questions | 0 of 4: "couldn't find supporting evidence" on 3; "The vendor is registration summary" | 2 of 4: types of Alpha and Beta correct with table citations. "What is the company name?" → "Alpha Ltd" only, Beta never mentioned. "Second supplier" → "The vendor is registration summary" |
| Known tax-card control (5 questions) | 0 of 5. Company name and company type both answered with the next form label "(ب) ٢- عنوان الشركة أو اسمها…", type with **no warning** | same 0 of 5 |

### Small models (B-models vs B, first action of 10 reserved tasks, 7 on Arabic-only documents)

All 10 answers were identical, character for character. The planner stayed `rules` everywhere; the embedder was
called on 3 questions, the reader on 1. During ingestion the embedder ran 82 calls and peak memory rose from 3.1 GB
to 5.1 GB. On this set the optional models cost memory and time and changed nothing.

### Speed and memory (26 files, 103 pages)

| | A | B | B-models |
|---|---|---|---|
| Ingest, cold / warm | 37.3 s / 32.0 s | 182.5 s / 146.3 s | 183.0 s / 158.4 s |
| Peak memory (ingest) | 655 MB | 3,072 MB | 5,091 MB |
| Question, CLI call incl. process start (median / p90) | 0.55 s / 0.68 s | 1.08 s / 1.19 s | about 1.2 s |
| Question, Inklight's own time (median) | 56 ms | 505 ms | — |

Docling ran on every page, but 40 of 103 pages are rotated scans (nearly all commercial-register pages); on those
it keeps Indra's plain lines and adds no structure. That is why B does not help where help was most needed.
(AM-1: this explanation was not supported. Tasks whose supporting pages were structured failed as well, and after
rotated pages were structured, B still completed nothing; see [the stage diagnosis](#where-the-tasks-failed-by-pipeline-stage).)

## Failures, ranked

Ranked by how often they decided an outcome and how much harm they do when a person trusts the answer.

1. **The answer is not about the question** (first answer wrong in 29 of 76 runs). Registers read as invoices (a
   national ID returned as a "total", a date in 2044); "avg of tax" for a date question; a URL, a page footer or
   "Original: Arabic" as the answer; sentences cut off before the value. The planner is rules-only, the documents
   are typed by keywords that do not cover Egyptian registers, tax cards or VAT certificates (0 of 7 tax-card and VAT
   documents recognised; registers typed as certificate, contract or unknown), and the answer step picks the best
   matching sentence.
2. **"Couldn't find supporting evidence" when the value is on the page** (18 of 76 first answers), mostly rotated
   or low-quality Arabic scans and dialect requests whose words do not match the page. Wrong abstentions are safe
   but useless.
3. **A form label returned as the value, without a relevant warning** (controls: 4 silent wrong of 10). The value
   beside label "١- نوع الشركة" is taken to be the next line, which is itself the next numbered label. This is the
   most harmful failure because it looks like an answer.
4. **No clarification, ever** (0 in 86 runs). With two VAT certificates in scope it answered from the wrong
   company's; with two companies in a table it named one; for "the date" on an order it averaged totals.
5. **Comparison of two documents fails** with "Comparison needs at least two documents" when two were given
   (A2-04 and A3-04, both arms). A type word in the request ("contracts", "letters") narrows the user's explicit
   document list to that type; in A3-04 one UN letter is also mistyped as a contract.
6. **Original vs current values** in registers: an outdated capital (10 M instead of 100 M) from the founding
   entry, not the latest amendment.
7. **Exports**: requests with several parts are split into keywords reported as "Not applied", which blocks the
   export; `extract` returns invoice columns or empty fields for registers and tax cards. 0 of 8 usable files.
8. **Ambiguous dates** (8/3/2023) read month-first, with a warning.

## Next three fixes, with reproductions

Chosen for harm prevented first, then frequency; none was applied during this evaluation. (All three were made
afterwards, with a rotated-page fix; see [Amendment AM-1](#what-was-changed).)

1. **Never return a form label as a value** (failure 3). Decline, or move to the value, when the candidate value is
   itself an enumerated label ("(ب)", "٢-", label vocabulary) or matches another label in the document.
   Reproduce: `inklight ask <known tax-card control> "ما نوع الشركة؟"` → label text, state succeeded, no warning
   (CTRL-02, both arms). A synthetic page with two consecutive numbered labels should be added as a test, since the
   control document is private.
2. **Present all candidates or ask when the scope holds several** (failure 4). When a field matches more than one
   entity, table, document or date kind, list them with their sources or ask which one. Reproduce (public,
   synthetic): `python bench/agent_eval/make_controls.py OUT`, then `inklight ask OUT/control-two-companies.pdf
   "What is the company name?"` with structure on → "Alpha Ltd" only.
3. **Keep the user's explicit documents; type words do not filter them** (failure 5), and add Egyptian register,
   tax card and VAT certificate types to classification (part of failure 1). Reproduce (public UN letters
   S/2025/455 and S/2025/470, Arabic): `inklight ask S_2025_455-ar.pdf S_2025_470-ar.pdf "قارن لي بين الرسالتين
   S/2025/455 و S/2025/470: تاريخ كل رسالة، وتاريخ التوزيع، ومن أرسلها، وما موضوعها باختصار. أيهما أقدم؟"` → "Comparison needs at least two documents".

After these, the largest remaining gaps are rotated-scan OCR and structure (40% of pages) and request
understanding for dialect Arabic; neither has a small fix.

## Evaluation problems and adjudication

- **References were wrong twice.** For A2-05 and A1-06 the task author took a company's founding capital from page 2
  of the register and missed later amendments (the same original-vs-current error as failure 6). Judges flagged both
  from the pages; A2-05 was checked again by the orchestrator on the page. A third dispute (A2-07: which register
  entry goes with which trade name) and a name spelling (A1-12) do not change outcomes. Frozen references were not
  edited; decisions are in [`adjudication.json`](../bench/results/agent_eval/adjudication.json).
- **One judge inconsistency** was overridden: the same tool behaviour on A1-06 got `correct_complete` from one judge
  and `correct_after_manual_correction` from another; the stricter label is used for both (the tool quoted the two
  figures but did not answer the percentage asked).
- **Harness failures**, kept in the log: the first ingest called a method that does not exist (no document read);
  `ik.py` crashed printing Arabic to a cp1252 console after its command had run and been logged.
- **Limits of the method.** The user and judges are AI agents (not people), from the same model family. The user
  agent read page images skilfully, so "correct after manual correction" says more about the user than about the
  tool; a person might have given up. Two handed-over files had the person's own transcription errors (VAT digit
  groups reversed, one wrong digit). The private set is dominated by rotated Egyptian registers. One machine; each
  question is a fresh CLI process.

## What still needs a human

Everything that was delivered here. Reading registers, tax cards and VAT certificates; deciding which of several
companies, documents or dates is meant; current vs original values in amended registers; handwriting (a signature
date); the order of digit groups in right-to-left printed numbers; checking that the references are right.

## Fit for supervised work?

Not on documents like these. Supervision presumes the tool does the work and the person checks it; here the person
did the work. Inklight's citations pointed at the right page in about half the runs (partly or fully supporting:
17 of 38 in A, 21 of 38 in B), so it can help find the page, but its answers should not be relied on, and a
form label returned as a value can pass as an answer. The earlier evaluation in [EVALUATION.md](EVALUATION.md)
measured better results on a different, more digital and less form-heavy set; both are true for their documents.

No README workflow is shown as "selected" from this evaluation: no run on a public document was completed by the
tool.

## Human rehearsal plan (not run; no time savings are claimed)

- **Participants:** 6–8 office workers who read Arabic and English; none involved in Inklight.
- **Material:** two matched task sets of 8 from the reserved tasks, with the private documents replaced by public or
  consenting documents of the same kinds; references written and frozen beforehand, as here.
- **Design:** within-subject, counterbalanced (Latin square on condition × task set × order): Inklight with page
  viewer vs page viewer only. A 2-person pilot first, to fix instructions and timing.
- **Measures:** time per task, correctness of the handed-over result (same outcome labels, blinded judges), tool
  errors accepted without correction (automation bias, especially form labels as values), number of follow-ups,
  perceived workload (NASA-TLX) and usability (SUS), with comments.
- **Rules:** analysis plan written before the sessions; failures and drop-outs reported; no claim of time saved
  unless measured with this design.

## Amendment AM-1: reconciliation, corrections, diagnosis and a bounded improvement cycle

Everything below comes from one per-run ledger ([`bench/agent_eval/ledger.py`](../bench/agent_eval/ledger.py)),
not from hand-kept totals. Public files: [`bench/results/agent_eval/amendment-1/`](../bench/results/agent_eval/amendment-1/).
The frozen originals (tasks, references, judgments, runs) are unchanged.

### Reconciled counts

| Count in the original report | Reconciled from the ledger |
|---|---|
| 102 vs 103 pages | 25 documents have 102 pages; with the one-page synthetic control, 103 pages were processed. |
| "20 control runs" (stated in a summary) | 9 control questions × 2 arms = **18** runs: 10 judged (known tax card) and 8 scored automatically (Alpha/Beta). |
| 104 runs vs "76 + 20 + 10 = 106" | **104** = 76 scored + 18 controls + 10 small-model subset. "106" came from the wrong 20. |
| "1 completed per arm" vs "no first answer answered the question" | A's one completion (A3-08) was a correct "not in the document" on the first action; the judge labelled that first attempt "abstained", not "correct". B's (A2-12) came after a follow-up in which the person pointed the tool to the notices clause. Under the stricter v2 grading below, B's is manual rescue. |

Run status: all 104 runs were attempted and finished their actions; no technical failure. Excluded from the score
by design: the 18 control runs and the 10 subset runs. In the rerun, 26 runs on a superseded build were set aside
(below). The person (an AI user agent) could open the original page images at every action; anything they read
there is **manual rescue**, not completion by the tool.

### Reference and judgment corrections

Each was verified on the page image (the judges flagged them; the orchestrator re-read them). Originals, corrected
versions, page evidence and reasons: [`amendment.json`](../bench/results/agent_eval/amendment-1/amendment.json)
(values stay private).

| Item | Original | Corrected | Evidence | Effect |
|---|---|---|---|---|
| A2-05 reference | founding capital (p2): 10% paid, 90M unpaid | latest position: fully paid, 0 unpaid | register p7 (and p6) | deterministic checks unchanged; outcomes unchanged |
| A1-06 reference | founding capital (p2): 25% paid | latest entry [9] (2023): issued = paid | register p5 | value checks 0/4 → 4/4 (both arms); outcomes unchanged |
| A2-07 reference | entry paired with the name above it | entry paired with the name it introduces | register p1, column 2 (and column 7) | none |
| A1-12 reference | a family name added | as printed (no family name) | register p5 | value checks 2/4 → 3/4 (arm B); none |
| A1-06, arm A judgment | correct_complete | correct_after_manual_correction | the tool quoted the figures but did not compute the percentage asked | A: 1 tool completion → still 1 (A3-08) |

Two of 38 references (5%) took founding values instead of the latest amendment: the same "original vs current"
error the tool makes.

### Where the tasks failed, by pipeline stage

`diagnose.py` replayed every task's first request exactly, in process, and followed each reference value through
the stored OCR text, the documents selected, the retrieved passages and the answer (`stages.py` names the earliest
stage where a needed value was demonstrably lost; computed values and paraphrases of digital text are not counted).

| Earliest demonstrated stage (original build) | A | B |
|---|---|---|
| Document selection (the plan dropped documents the user passed) | 4 | 4 |
| Request parsing (a non-invoice request read as invoice columns) | 2 | 2 |
| OCR, rotated page (value not in the stored text) | 7 | 7 |
| OCR, upright page | 9 | 9 |
| Retrieval (in the text, not retrieved; only where a search ran) | 4 | 4 |
| Answer selection (retrieved or handled, not in the answer) | 11 | 11 |
| Every value in the answer, still judged wrong | 0 | 1 |
| Completed | 1 | 0 |

Of 199 reference values, **148 (74%) were in the OCR text**, 36 reached the retrieved passages (where a search ran)
and 19 (A) / 28 (B) appeared in the first answer. Most losses are after OCR. OCR losses are real too: on photocopied
cards and rotated certificates dates and numbers come out as "1/1", "000000" or garbage.

Structure on the supporting pages (B): structured 26 tasks, skipped as rotated 7, mixed 4, no reference page 1;
the rotated-page skip is therefore not why B did not help: tasks whose pages were structured failed as well.

### What was changed

Tests were written first, on synthetic pages that copy each failure's mechanism (no private names or values), and go
through `DocumentAgent.ask` or the CLI. Commits:

- `f6b717c` evaluation reconciliation (ledger, amendment, stage diagnosis).
- `bfeae05` answer selection and scope ([tests](../tests/test_eval_regressions.py),
  [structure-path tests](../tests/test_structure_candidates.py)):
  - **form labels as values**: list markers ("١-", "(ب)", "2.") are stripped from labels, a numbered field name or a
    "Label: value" line is never another label's value, a field name with no readable value is declined with its
    page, and a guard on every answer path (field shortcut, reader, rules) declines an answer that is one of the
    page's field names. Look-alike values ("Name Holdings") and labels wrapped over two lines still answer;
  - **several candidates**: two tables with the same headings, two pages or two documents carrying the field are
    listed with where each is (label path, table path and field shortcut); a question naming one ("Beta Ltd",
    "Supplier 2") gets that one; colon-less column headings over a row of cells are read as a table;
  - **explicit scope**: documents the user chose are kept unless the request restricts them ("only", "فقط").
- `a7ec8ee` rotated pages ([frames.py](../src/inklight/frames.py)): turned pages are given to Docling upright, one
  coordinate transform (0/90/180/270, Indra's convention measured) links stored boxes, Docling's cells and the page
  as shown, and the viewer draws citations on the page as shown. Synthetic geometry tests
  ([test_frames.py](../tests/test_frames.py), no models) and real-model tests
  ([test_structure_rotation.py](../tests/test_structure_rotation.py): Indra and Docling on a scanned card turned
  90/180/270; the page is structured with all its lines, answers come from table cells, and the cited box on the
  page as shown re-reads as the value). On three real rotated documents: all 22 turned pages structured, every line
  delivered (822/822, 408/408).
- `d9e0496` the CLI path (`inklight ask FILE FILE "…"`) also keeps the files as the user's choice; found in the
  rerun, after which the 26 structure-off runs already made on `a7ec8ee` were set aside and redone.

### Rerun on the same workload

All documents are now development data. The corrected build (`d9e0496`, wheel `b3e7ff25…`) was installed in its own
environment with dependencies identical to the baseline's, into fresh libraries; arms **A2** (structure off) and
**B2** (Docling, accurate), other settings unchanged. The same 38 tasks went through the same bounded user-agent
workflow (4 actions, the same brief, no answer keys or diagnoses). Baseline and rerun cases were then judged
**together**, arm names removed and cases mixed, under a stricter brief
([judge_brief_v2.md](../bench/agent_eval/briefs/judge_brief_v2.md): anything the person read off the page is manual
rescue; the exact claim is checked on the page). A separate reviewer re-checked 92 cases (every uncertain or
disputed judgment, every apparent change between builds, every wrong outcome) and made identical tool behaviour
carry identical labels. AI review, not human validation.

| Same 38 tasks, judged together (v2, reviewed) | A | **A2** | B | **B2** |
|---|---|---|---|---|
| Completed by the tool, first action | 1 | 1 | 0 | 0 |
| Completed by the tool after follow-up or clarification | 0 | 0 | 0 | 0 |
| Correct only by manual rescue | 36 | 35 | 37 | 37 |
| Correct abstention | 1 | 1 | 0 | 0 |
| Silent wrong as handed over (all with the person's own misreading) | 1 | 2 | 1 | 1 |
| Wrong abstention / overstated / technical failure | 0 | 0 | 0 | 0 |
| First answer correct · wrong · abstained · failed | 0 · 15 · 10 · 6 | 0 · 16 · 10 · 4 | 0 · 16 · 7 · 6 | 0 · 17 · 6 · 4 |
| Citations fully / partly supporting | 2 / 15 | 2 / 20 | 2 / 18 | 2 / 20 |
| Warnings describing the actual problem | 8 | 7 | 8 | 5 |
| Usable tool-written export (of 4) | 0 | 0 | 0 | 0 |
| Reviewer disagreed with the judge · still uncertain | 1 · 2 | 0 · 4 | 2 · 6 | 3 · 6 |

Under v2 the baseline grades slightly stricter than in the original judging (B: 1 → 0 completions, A2-12 is manual
rescue). By language and task type no slice has more than one completion in any arm
([summary-v2.md](../bench/results/agent_eval/amendment-1/summary-v2.md)).

What the changes did, task by task:

- **Improved first answers, not completions**: the false "needs at least two documents" is gone (stage "document
  selection" 4 → 0); A3-04's comparison now answers partly instead of failing (both arms), A2-04's returns a text
  comparison that does not answer the question. With structure on, A2-05's first answer now quotes the page-7
  "fully paid" entry (a rotated page that had no structure before), but the asked amount and percentage were the
  person's arithmetic, so it is not a completion. In the exact replay, reference values in the first answer rose
  from 19 to 27 (structure off) and 28 to 46 (on); first answers changed in 5 and 8 of 38 tasks.
- **Safer, not more accurate**: on the known tax-card control (structure off) the company-name and
  registration-number questions now decline and point at the field on page 2 instead of returning a label
  (silent wrong → wrong abstention: the values are on the page). On the Alpha/Beta control (structure on) "What is
  the company name?" now lists both companies; "the second supplier" is now a flagged list of "1" and "2" instead
  of a silent "registration summary" — still not an answer.
- **Not fixed**: with structure on, the known tax-card control still answers with field names: Docling merges
  several numbered field names into one long block, which the guard (built for single field names) does not
  recognise. With two VAT certificates in scope the tool still answers from the wrong company's (A1-10). Follow-ups
  are often misread as calculations ("avg of tax"). OCR losses are unchanged.
- **Regressions**: none in what the tool completed (A3-08 stays a correct abstention). The outcome changes on A2-05
  (A2), A1-02 (B2) and A1-03 (B2) come from the person's own reading (e.g. using the founding capital of page 2),
  reviewed as such.

**Does structure help now?** It reaches the pages it skipped: all 40 turned pages are structured, cells handed to
Docling rose from 2,988 to 5,250, and Docling's own time fell from 112 s to 65 s (fewer spurious tables on sideways
images: 24 → 18). It still completes no task on this workload (B2 0 of 38 vs A2 1 of 38). Docling's text has 11 tokens
not in Indra's lines (6 before); each is two adjacent Indra words joined without a space, not a second OCR.

| Speed and memory (26 files, 103 pages) | A2 | B2 | (baseline A / B) |
|---|---|---|---|
| Ingest, cold / warm | 35.6 s / 33.4 s | 121.8 s / 102.2 s | 37.3 / 32.0 s · 182.5 / 146.3 s |
| Peak memory (ingest) | 655 MB | 2,614 MB | 655 MB · 3,072 MB |
| Question: CLI call median · Inklight's own time median | 0.57 s · 68 ms | 1.10 s · 503 ms | 0.55 s · 56 ms / 1.08 s · 505 ms |
| Model calls | none (rules) | none (rules) | none |

The small models were not retested: nothing in the diagnosis involved them (their earlier result, 10 of 10 answers
identical, stands).

### What remains unsuitable for unattended use

All of this workload. The tool completed one task in 38 in the best arm, a "not in the document" answer; every other
correct result needed a person reading the page. In particular: reading scanned Egyptian registers, tax cards and
VAT certificates (OCR loses values; the answer step loses most of the rest), choosing between several certificates
or companies, current vs original values in amended registers, exports of such documents, and multi-step requests
whose wording is misparsed. The fixes made failures safer and more honest on the controls; they did not make the
tool complete these tasks.

### Commands and provenance (cycle)

```bash
python bench/agent_eval/ledger.py WORKSPACE OUT_DIR [--judging judging2]           # the per-run ledger and every count
EVAL_PYTHON bench/agent_eval/diagnose.py WORKSPACE ARM OUT.jsonl --ingest INGEST.json [--from-arm A]
python bench/agent_eval/stages.py STAGES_A.jsonl STAGES_B.jsonl LEDGER.jsonl OUT.md OUT.json --arms A2,B2
python bench/agent_eval/bundle.py WORKSPACE A,B,A2,B2 TASKS.json --judging judging2 --blind --corrected
EVAL_PYTHON bench/agent_eval/visualize.py WORKSPACE OUT_DIR --judging judging2   # boxes through frames.to_original
```

Rerun provenance: [`provenance-rerun.json`](../bench/results/agent_eval/amendment-1/provenance-rerun.json) (commit,
wheel hash, superseded build, identical dependencies, models, settings, cache conditions, judging). Harness changes
and failures: [`harness_log.txt`](../bench/results/agent_eval/amendment-1/harness_log.txt).

## Reproduce

```bash
python bench/agent_eval/prepare_docs.py SOURCE_DIR WORKSPACE      # copies, hashes, page images, near-duplicates
python bench/agent_eval/provenance.py WORKSPACE                     # wheel, packages, model snapshots, hardware
python bench/agent_eval/make_controls.py WORKSPACE/controls         # synthetic Alpha/Beta control
EVAL_PYTHON bench/agent_eval/ingest.py CONFIG DOCS...               # cold and warm ingest, peak memory
python bench/agent_eval/ik.py --arm A --task ID ask DOCS... "request"   # the user agent's only tool access
python bench/agent_eval/bundle.py WORKSPACE A,B TASKS.json          # blinded judging cases + deterministic checks
python bench/agent_eval/single_shot.py WORKSPACE controls A,B
python bench/agent_eval/aggregate.py WORKSPACE OUT.json --md OUT.md
python bench/agent_eval/visualize.py WORKSPACE OUT_DIR              # page images with cited regions, per run
```

Agent briefs: [`bench/agent_eval/briefs/`](../bench/agent_eval/briefs/). Documents, tasks, references, transcripts
and judgments stay in the private workspace.
