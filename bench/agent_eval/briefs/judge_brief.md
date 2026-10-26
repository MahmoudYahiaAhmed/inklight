# Brief for the independent judge

You judge whether a person, using a document tool, completed a document task correctly. You are given, for each case,
a folder `C:/Users/pc/inklight-eval-private/judging/<case_id>/` containing:

- `task.json` — the request as the person received it (and what they meant if asked: `user_intent`);
- `reference.json` — the frozen reference, written from the original pages before any run (expected behaviour,
  values, page and region, entity relationships, judging notes; `uncertain` marks references needing adjudication);
- `transcript.md` — every action the person took with the tool, and exactly what the tool showed (answer, sources,
  warnings, state);
- `final.json` — what the person handed over; `export/` — the exported file(s) they handed over, if any;
- `pages.txt` — paths of the original page images; open them (Read tool) to check values and citations yourself.

You do not know which system or configuration produced a case, and no case is expected to be better than another.
Judge each case on its own evidence. The reference can be wrong: if the page clearly shows otherwise, say so and mark
`reference_disputed: true` (do not silently change the outcome to match either side).

## For each case decide

1. Is the final answer correct? complete? does it answer the question that was asked?
2. Does each citation support the exact claim, including the entity/value relationship? (A citation showing
   "Alpha Ltd" does not support an answer about Beta Ltd.)
3. Was clarification needed, and was it handled? Was a refusal/abstention justified?
4. Did the warnings describe the actual problem? (A warning unrelated to the real error does not make it safe.)
5. If an export was required: is the file itself correct (right rows, columns, values)? Open it.

Then assign exactly one outcome:
`correct_complete` · `correct_after_clarification` · `correct_after_manual_correction` · `honest_partial` ·
`correct_abstention` · `correct_clarification_request` · `wrong_abstention` · `wrong_with_relevant_warning` ·
`silent_wrong` · `overstated_completion` (claims success while omitting required work/documents) ·
`technical_failure`.

"First attempt" = the tool's response to the person's first action. Judge it separately:
`first_attempt`: `correct` | `partially_correct` | `wrong` | `abstained` | `asked_clarification` | `failed`.

## Write `C:/Users/pc/inklight-eval-private/judging/<case_id>/judgment.json`
```json
{"case_id": "...", "outcome": "...", "first_attempt": "...",
 "answer_correct": true, "answer_complete": true, "citations_support_claims": "yes|partly|no|none_given",
 "warnings_accurate": "yes|no|none_given|not_applicable", "export_correct": "yes|partly|no|not_applicable",
 "clarification_needed": false, "actions_used": 1,
 "explanation": "2-4 sentences of evidence: what was right/wrong, with page references",
 "reference_disputed": false, "uncertain": false, "uncertain_reason": ""}
```
Be strict and specific. Do not reward confident wording; reward correct, supported, honest results.
