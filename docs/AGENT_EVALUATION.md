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

Chosen for harm prevented first, then frequency; none was applied during this evaluation.

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
