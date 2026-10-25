# Source used by the first-access runs

The first-access runs (`first-access-res-auto.json`, `first-access-res-rules.json`,
`first-access-fresh-auto.json`) were made from an uncommitted working tree. Their `build` field records the Git
HEAD of that tree, `6b4cc12`, but the code that ran was not `6b4cc12`.

## Recovered source

The source was rebuilt from the session transcript. It holds every edit, with timestamps, made between the
runs and the commits that followed. Apply a patch here to a checkout of `8c54921` to get the code a run used:

| Runs | Started (UTC, from `reserved-access.log`) | Source | Patch hash (`git hash-object`) |
|---|---|---|---|
| `first-access-res-auto`, `first-access-res-rules` | 2026-10-24 22:56:59, 22:57:50 | `8c54921` + [`first-access-reserved.patch`](first-access-reserved.patch) | `fbd12f4b…` |
| `first-access-fresh-auto` | 2026-10-24 23:03:43 | `8c54921` + [`first-access-fresh.patch`](first-access-fresh.patch) | `ba673164…` |

The patches only remove the fixes made after those runs:

- **Reserved patch.** Removes four fixes:
  - flagging rule answers that share under half the question's words
  - reading parentheses after a written amount as a restatement
  - "Letter dated" dating only a letter's own title line
  - the Arabic report cue
- **Fresh patch.** Removes the last two of these, which came after the fresh run.

```bash
git worktree add ../first-access 8c54921
git -C ../first-access apply bench/results/usecases/provenance/first-access-reserved.patch
```

## Check

The rebuilt trees were run again with the same documents, models and harness (`bench/usecases/evaluate.py`,
unchanged since `bb38313`; the reserved run used it before the `fresh` split option was added, an argument-parsing
change only). Ignoring timing and model-call counts, the outputs match the stored first-access files exactly:

- **Ingestion.** Every document's text hash, type and pages match.
- **Answers.** Every answer, state, confidence, outcome and cited page matches.
- **Library tasks.** These match too, except the export task's answer, which embeds the export file's local path.

These re-runs are logged in `reserved-access.log` with `"purpose": "provenance check"`. They are not evaluations,
and the documents were not used to change anything.

## What cannot be recovered

- **Python bytecode and the environment.** There is no record of either beyond what the run files hold. The
  editable install and model files were the same as for the `8c54921` runs.
- **Formatting.** `ruff format` ran between the reserved run and the commit, so the reserved patch restores
  behaviour, not the exact original whitespace.
