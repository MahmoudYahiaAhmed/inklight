# Brief for the independent judge (rerun, v2)

This is the brief of the original evaluation (judge_brief.md) with stricter checking. Everything there still applies:
read it first, then these rules, which take precedence.

## What counts as the tool's work

- The person could open the page images at any time. Anything in the final answer that the tool did not show
  (in an answer, a cited passage, or a file it wrote) and the person read off the page is **manual rescue**: the
  outcome is `correct_after_manual_correction`, never `correct_complete` or `correct_after_clarification`.
- `correct_after_clarification`: the tool asked which item was meant, or listed the candidates, the person
  answered with the task's `user_intent`, and the tool then gave the complete correct answer itself.
- `correct_complete`: the tool's own answer (any action) is complete and correct; the person only copied it. A
  trivial step the request itself asks for (a percentage of two figures the tool gave) is NOT the tool's work:
  if the request asks for it and the tool did not do it, the result is manual.
- Judge correctness independently of the tool's "succeeded" / "partial" state.

## Check the exact claim on the page

For every value the outcome depends on, open the page image and check:
1. the right **entity** (company, person, document) — a value of another company is wrong;
2. the right **field** (registration vs tax number, issue vs expiry date, type vs name);
3. the right **date or amendment** — the current value where the request asks for the current one (registers
   record later amendments after the founding entry);
4. the right **row and column** of a table;
5. the **complete scope** requested (every document, every item asked for).

A citation that merely contains the expected string is not enough: the cited passage must state the claim (the
value as the value of that field, for that entity).

## Safety outcomes

- A tool answer that is a form label or heading (a field name, not its value) is wrong.
- A wrong answer the tool flagged with a warning describing the actual problem: `wrong_with_relevant_warning`.
- Turning a wrong answer into an honest "not found, check page N" is safer, but it is an abstention: judge it as
  `correct_abstention` only when the value is truly absent; otherwise `wrong_abstention`.

## Uncertainty

Do not force a pass. If you are unsure between two outcomes, give the stricter one, set `uncertain: true`, and
say why. The reference can be wrong: say so with `reference_disputed: true` and the page evidence.
Write judgment.json exactly in the format of judge_brief.md, plus `"brief": "v2"`.
