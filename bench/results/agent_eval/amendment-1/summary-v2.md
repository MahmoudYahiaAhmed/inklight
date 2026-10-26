# Ledger summary (baseline A/B and rerun A2/B2, judged together under brief v2, reviewed, corrected references)

## Runs

| kind | runs |
|---|---|
| single_shot_judged | 20 |
| single_shot_scored | 16 |
| single_shot_subset | 10 |
| user_agent | 152 |
| **total** | 198 |

## Scored runs

| | A | A2 | B | B2 |
|---|---|---|---|---|
| completed by the tool on the first action | 1/38 | 1/38 | 0/38 | 0/38 |
| completed by the tool after follow-up (incl. clarification) | 0/38 | 0/38 | 0/38 | 0/38 |
| correct only after the person read the pages (manual rescue) | 36/38 | 35/38 | 37/38 | 37/38 |
| correct abstention by the tool | 1/38 | 1/38 | 0/38 | 0/38 |
| wrong abstention | 0/38 | 0/38 | 0/38 | 0/38 |
| silent wrong (as handed over) | 1/38 | 2/38 | 1/38 | 1/38 |
|   of which the person's reading was wrong too (reviewed: person or both) | 1/38 | 2/38 | 1/38 | 1/38 |
| overstated completion | 0/38 | 0/38 | 0/38 | 0/38 |
| honest partial / wrong with relevant warning | 0/38 | 0/38 | 0/38 | 0/38 |
| technical failure | 0/38 | 0/38 | 0/38 | 0/38 |
| first answer judged correct | 0/38 | 0/38 | 0/38 | 0/38 |
| first answer wrong | 15/38 | 16/38 | 16/38 | 17/38 |
| first answer abstained | 10/38 | 10/38 | 7/38 | 6/38 |
| first answer failed (error/empty) | 6/38 | 4/38 | 6/38 | 4/38 |
| citations fully support the claim | 2/38 | 2/38 | 2/38 | 2/38 |
| citations partly support | 15/38 | 20/38 | 18/38 | 20/38 |
| warnings describe the actual problem | 8/38 | 7/38 | 8/38 | 5/38 |
| export tasks with a usable tool-written file | 0/38 | 0/38 | 0/38 | 0/38 |
| judgment amended | 0/38 | 0/38 | 0/38 | 0/38 |
| reviewed by a separate reviewer | 16/38 | 16/38 | 20/38 | 20/38 |
|   reviewer disagreed with the judge | 1/38 | 0/38 | 2/38 | 3/38 |
|   still uncertain after review | 2/38 | 4/38 | 6/38 | 6/38 |

- A: 87 actions, mean 2.29 per run; CLI seconds median 0.55; Inklight ms median 56; brains ['rules (planner: rules)']
- A2: 98 actions, mean 2.58 per run; CLI seconds median 0.57; Inklight ms median 68; brains ['rules (planner: rules)']
- B: 92 actions, mean 2.42 per run; CLI seconds median 1.08; Inklight ms median 505; brains ['rules (planner: rules)']
- B2: 101 actions, mean 2.66 per run; CLI seconds median 1.10; Inklight ms median 503; brains ['rules (planner: rules)']

## By slice (completed by the tool / manual rescue / n)

| language | A | A2 | B | B2 |
|---|---|---|---|---|
| ar | 0 / 11 / 11 | 0 / 10 / 11 | 0 / 11 / 11 | 0 / 11 / 11 |
| en | 1 / 2 / 3 | 1 / 2 / 3 | 0 / 3 / 3 | 0 / 3 / 3 |
| mixed | 0 / 23 / 24 | 0 / 23 / 24 | 0 / 23 / 24 | 0 / 23 / 24 |

| task_type | A | A2 | B | B2 |
|---|---|---|---|---|
| absent | 1 / 2 / 3 | 1 / 2 / 3 | 0 / 3 / 3 | 0 / 3 / 3 |
| ambiguous | 0 / 3 / 3 | 0 / 3 / 3 | 0 / 3 / 3 | 0 / 3 / 3 |
| calculate | 0 / 4 / 4 | 0 / 3 / 4 | 0 / 4 / 4 | 0 / 4 / 4 |
| compare | 0 / 7 / 7 | 0 / 7 / 7 | 0 / 7 / 7 | 0 / 6 / 7 |
| export | 0 / 3 / 4 | 0 / 3 / 4 | 0 / 3 / 4 | 0 / 4 / 4 |
| field | 0 / 4 / 4 | 0 / 4 / 4 | 0 / 4 / 4 | 0 / 4 / 4 |
| search | 0 / 3 / 3 | 0 / 3 / 3 | 0 / 3 / 3 | 0 / 3 / 3 |
| summary | 0 / 3 / 3 | 0 / 3 / 3 | 0 / 3 / 3 | 0 / 3 / 3 |
| table | 0 / 7 / 7 | 0 / 7 / 7 | 0 / 7 / 7 | 0 / 7 / 7 |

## Controls (outside the score)

- A: pair control 0/4 pass; known control {'silent_wrong': 5}
- A2: pair control 0/4 pass; known control {'wrong_abstention': 2, 'silent_wrong': 3}
- B: pair control 2/4 pass; known control {'silent_wrong': 5}
- B2: pair control 3/4 pass; known control {'silent_wrong': 5}

Small-models subset: 10/10 first answers identical to arm B.

## Deterministic checks under original vs corrected references

| run | original | corrected |
|---|---|---|
| A:A1-06 | 0/4 | 4/4 |
| A:A1-12 | 4/4 | 4/4 |
| A:A2-05 | 5/5 | 5/5 |
| A:A2-07 | 5/5 | 5/5 |
| A2:A1-06 | 0/4 | 4/4 |
| A2:A1-12 | 3/4 | 3/4 |
| A2:A2-05 | 5/5 | 4/5 |
| A2:A2-07 | 5/5 | 5/5 |
| B:A1-06 | 0/4 | 4/4 |
| B:A1-12 | 2/4 | 3/4 |
| B:A2-05 | 5/5 | 5/5 |
| B:A2-07 | 5/5 | 5/5 |
| B2:A1-06 | 0/4 | 4/4 |
| B2:A1-12 | 2/4 | 3/4 |
| B2:A2-05 | 3/5 | 5/5 |
| B2:A2-07 | 5/5 | 5/5 |
