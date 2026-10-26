# Brief for the separate reviewer (judgments under judge_brief_v2.md)

You review other judges' decisions. You are not one of them. Read judge_brief.md and judge_brief_v2.md first: those
are the rules the judges applied, and you apply the same rules.

You get groups of cases. Each group holds the cases of ONE task (the same request and reference, handled in
different runs; you are not told which run produced which case, and it does not matter). For every case:

1. Read task.json, reference.json, transcript.md, final.json (if any), export/, the judge's judgment.json, and open
   the page images needed to check the claim yourself (entity, field, date/amendment, row/column, complete scope).
2. Decide whether you AGREE with the judge's outcome and first_attempt. If not, give yours, with page evidence.
3. Consistency: where two cases of a group show the same tool behaviour (same answer, same warning), they must get
   the same label. Say which cases you made consistent and why.
4. Attribute what went wrong in the handed-over result: "tool" (the tool's own answer or file was wrong, or the
   tool did not answer and the person rescued it), "person" (the tool's output was not the cause: the person
   transcribed or concluded wrongly), "both", or "none" (the hand-over is correct).
5. Is the tool's FIRST answer better, worse or equal to the other cases of the group? (describe, do not guess)

Do not change judgment.json. Write review.json in the case folder:
{"case_id": "...", "agree": true, "reviewed_outcome": "...", "reviewed_first_attempt": "...",
 "error_source": "tool|person|both|none", "consistency_note": "", "evidence": "page refs and what they show",
 "uncertain": false, "uncertain_reason": ""}
Preserve disagreement and uncertainty: if you are not sure, say so rather than forcing agreement. This is AI review,
not human validation.
