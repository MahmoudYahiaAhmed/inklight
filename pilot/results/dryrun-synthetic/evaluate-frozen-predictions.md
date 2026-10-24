# Pilot evaluation: synthetic-invoice / dev

Documents reviewed: 60 · manual entry: 15 · baselines: dry-run

Predictions: predictions frozen when each review opened

| Metric | Value |
|---|---|
| Field accuracy | 99.4% (358/360; 95% CI 98–100%) |
| Coverage without review | 93.1% (335/360; 95% CI 90–95%) |
| Precision, unflagged | 99.7% (335/336; 95% CI 98–100%) |
| Silent error rate | 0.3% (1/360; 95% CI 0–2%) |
| Predicted values flagged | 0.067 |
| Predicted values corrected | 0.006 |
| Active seconds per document, review | {'n': 60, 'median': 0.0, 'mean': 0.0} |
| Active seconds per document, manual entry | {'n': 15, 'median': 0.0, 'mean': 0.0} |
| Time ratio review / manual (medians) | None |
| Documents entered both ways · agreement | 15 · {'agree': 90} |

Counts: {'correct_unflagged': 335, 'correct_flagged': 23, 'wrong_unflagged': 1, 'wrong_flagged': 1, 'missing': 0, 'both_absent': 0}
