# Brief for a task author / reference reviewer

You write realistic document tasks and their frozen reference answers for an evaluation of a document-question tool.
You work ONLY from the original rendered pages. Never run any document tool, never read any tool output, never look at
source code. You are not told which system will be tested.

## Your material

- Page images: `~/inklight-eval-private/work/pages/<doc_id>/p<N>.png` (150 dpi). Read them with the Read
  tool (it shows images). If a page is too small to read, render a crop at higher resolution with Python + PyMuPDF from
  the original in `~/inklight-eval-private/work/docs/<doc_id>.<ext>` (images: crop with Pillow).
- `~/inklight-eval-private/work/manifest.json` lists every document (doc_id, group, page count, original file
  name). Documents of one group come from one organisation or source.
- These are private business documents. Do not copy their content anywhere except the two output files below.

## What to write

Write tasks a real person would ask (an accountant onboarding a supplier, a paralegal, an analyst), in the language
they would use. Cover, where your documents allow:

- finding fields (registration number, company name, tax ID, dates, addresses, activity, capital, owners/managers);
- multi-page documents and tables (keep the relationship between entity, label and value: who owns which share, which
  date belongs to which entry);
- comparing two documents (e.g. two expiry dates, two names of the same company);
- an export: "export X, Y, Z for these documents as CSV" (the person will check the file);
- a calculation, saying what to do with missing values or different currencies;
- cross-language search (ask in English for information printed in Arabic, or the reverse);
- a question whose answer is NOT in the documents (correct behaviour: say it is not there);
- an ambiguous question (two companies, two dates, two people fit) where the correct behaviour is to ask which one or
  to present both clearly; and a follow-up that resolves it (the person's intended meaning, e.g. "I mean the second
  company").

Write requests in natural language, the way people talk; do NOT phrase them to suit any tool. Mix Arabic and English
requests. About 12 tasks for your documents (a task may involve 1–3 documents of your groups). Prefer variety over
repetition (not twelve "what is the registration number").

## Output files (JSON, UTF-8)

1. `~/inklight-eval-private/frozen/tasks_<AUTHOR>.json` — what the USER sees (no answers!):
```json
[{"task_id": "<AUTHOR>-01", "docs": ["g02-01", "g02-03"], "request": "…natural request…",
  "request_language": "ar|en", "doc_languages": ["ar"], "task_type": "field|table|compare|export|calculate|search|summary|absent|ambiguous",
  "deliverable": "answer|csv|json",
  "user_intent": "what the person means if the tool asks (e.g. 'the second company, X'); otherwise empty"}]
```
2. `~/inklight-eval-private/frozen/refs_<AUTHOR>.json` — the frozen REFERENCE (hidden from the user):
```json
[{"task_id": "<AUTHOR>-01",
  "expected_behaviour": "answer|abstain|clarify_or_present_all|partial",
  "answer": {"<field or item>": {"value": "…exactly as printed…", "alternatives": ["…other acceptable forms…"],
             "doc": "g02-01", "page": 1, "region": "short description of where on the page (e.g. 'top right box, line 3')"}},
  "relationships": "for tables/entities: which value belongs to which entity, in words",
  "export_columns": ["only for csv/json deliverables"],
  "notes": "how to judge partial answers, what must NOT be said, etc.",
  "uncertain": false, "uncertain_reason": ""}]
```
Values: copy them exactly as printed (Arabic-Indic or Latin digits as on the page); add the other digit form and
reasonable spellings as alternatives. If you cannot read something with certainty, set `uncertain: true` and say why
— never guess silently. For absent-answer tasks, explain why the information is not in the documents.

When done, reply with a short summary: number of tasks per type and language, and any uncertain references.
