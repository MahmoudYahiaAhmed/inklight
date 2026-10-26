# Pilot evaluation: synthetic-invoice / dev

Documents reviewed: 60 · manual entry: 15 · baselines: re-predicted with 0.1.1.dev0

Predictions: re-predicted by the installed build {'inklight_version': '0.1.1.dev0', 'inklight_file': '~\\inklight-pilot\\venv\\Lib\\site-packages\\inklight\\__init__.py'}

| Metric | Value |
|---|---|
| Field accuracy | 99.4% (358/360; 95% CI 98–100%) |
| Coverage without review | 93.1% (335/360; 95% CI 90–95%) |
| Precision, unflagged | 99.7% (335/336; 95% CI 98–100%) |
| Silent error rate | 0.3% (1/360; 95% CI 0–2%) |
| Predicted values flagged | – |
| Predicted values corrected | – |
| Active seconds per document, review | – |
| Active seconds per document, manual entry | {'n': 15, 'median': 0.0, 'mean': 0.0} |
| Time ratio review / manual (medians) | – |
| Documents entered both ways · agreement | 15 · {'agree': 90} |

Counts: {'correct_unflagged': 335, 'correct_flagged': 23, 'wrong_unflagged': 1, 'wrong_flagged': 1, 'missing': 0, 'both_absent': 0}
