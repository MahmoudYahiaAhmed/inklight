# Ledger summary (original runs, amendment AM-1 applied)

## Runs

| kind | runs |
|---|---|
| single_shot_judged | 10 |
| single_shot_scored | 8 |
| single_shot_subset | 10 |
| user_agent | 76 |
| **total** | 104 |

## Scored runs

| | A | B |
|---|---|---|
| completed by the tool on the first action | 1/38 | 0/38 |
| completed by the tool after follow-up (incl. clarification) | 0/38 | 1/38 |
| correct only after the person read the pages (manual rescue) | 35/38 | 35/38 |
| correct abstention by the tool | 1/38 | 0/38 |
| wrong abstention | 1/38 | 1/38 |
| silent wrong (as handed over) | 0/38 | 0/38 |
| overstated completion | 0/38 | 0/38 |
| honest partial / wrong with relevant warning | 1/38 | 1/38 |
| technical failure | 0/38 | 0/38 |
| first answer judged correct | 0/38 | 0/38 |
| first answer wrong | 14/38 | 15/38 |
| first answer abstained | 10/38 | 8/38 |
| first answer failed (error/empty) | 6/38 | 5/38 |
| citations fully support the claim | 2/38 | 1/38 |
| citations partly support | 15/38 | 20/38 |
| warnings describe the actual problem | 6/38 | 16/38 |
| export tasks with a usable tool-written file | 0/38 | 0/38 |
| judgment amended | 1/38 | 0/38 |

- A: 87 actions, mean 2.29 per run; CLI seconds median 0.55; Inklight ms median 56; brains ['rules (planner: rules)']
- B: 92 actions, mean 2.42 per run; CLI seconds median 1.08; Inklight ms median 505; brains ['rules (planner: rules)']

## By slice (completed by the tool / manual rescue / n)

| language | A | B |
|---|---|---|
| ar | 0 / 10 / 11 | 0 / 10 / 11 |
| en | 1 / 2 / 3 | 0 / 3 / 3 |
| mixed | 0 / 23 / 24 | 1 / 22 / 24 |

| task_type | A | B |
|---|---|---|
| absent | 1 / 2 / 3 | 1 / 2 / 3 |
| ambiguous | 0 / 3 / 3 | 0 / 3 / 3 |
| calculate | 0 / 4 / 4 | 0 / 4 / 4 |
| compare | 0 / 6 / 7 | 0 / 6 / 7 |
| export | 0 / 3 / 4 | 0 / 3 / 4 |
| field | 0 / 4 / 4 | 0 / 4 / 4 |
| search | 0 / 3 / 3 | 0 / 3 / 3 |
| summary | 0 / 3 / 3 | 0 / 3 / 3 |
| table | 0 / 7 / 7 | 0 / 7 / 7 |

## Controls (outside the score)

- A: pair control 0/4 pass; known control {'silent_wrong': 2, 'wrong_with_relevant_warning': 2, 'wrong_abstention': 1}
- B: pair control 2/4 pass; known control {'silent_wrong': 2, 'wrong_with_relevant_warning': 3}

Small-models subset: 10/10 first answers identical to arm B.

## Deterministic checks under original vs corrected references

| run | original | corrected |
|---|---|---|
| A:A1-06 | 0/4 | 4/4 |
| A:A1-12 | 4/4 | 4/4 |
| A:A2-05 | 5/5 | 5/5 |
| A:A2-07 | 5/5 | 5/5 |
| B:A1-06 | 0/4 | 4/4 |
| B:A1-12 | 2/4 | 3/4 |
| B:A2-05 | 5/5 | 5/5 |
| B:A2-07 | 5/5 | 5/5 |
