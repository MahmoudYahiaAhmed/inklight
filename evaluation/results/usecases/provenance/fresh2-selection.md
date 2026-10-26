# How the fresh2 documents were chosen

fresh2 has **15 documents**. It never had more. In the working session, one message described the set as
"19 genuine documents"; that count was wrong. The script that first wrote the expectations listed the same 15
entries. It failed on a shell quoting error before writing anything, and the committed corpus (`6c1659c`) has
held 15 entries from its first version.

"19" in README.md and EVALUATION.md is a count of **questions**: the 19 unanswerable questions whose subject the
document never mentions. It does not count documents.

## Candidates downloaded but not used

All candidates were downloaded on 2026-10-25 between 04:26 and 04:30 UTC, and narrowed in the next few minutes.
That was before the expectations were committed (`6c1659c`, 04:33 UTC) and before any Inklight build read them.
They were looked at only with `pypdfium2` (text and rendered pages) or as images. No Inklight build ever read an
excluded file.

| Candidate | Source | Why excluded |
|---|---|---|
| S/2025/140, English and Arabic | UN documents | 5-page letter on the same subject as S/2025/160; the set kept four UN pairs to stay small |
| S/2025/160, English and Arabic | UN documents | Same subject as S/2025/140; not needed for the four pairs |
| S/16300, English and Arabic | UN documents | 31 pages, far longer than anything else in the set |
| CORU `016dee86…` (Metro) | CORU QA test | Tiny receipt, photographed sideways on fabric; dropped to keep the set to three receipts |
| CORU `0066b300…`, `00be10a0…` (LC Waikiki) | CORU QA test, annotations only | The company is already in the reserved split (receipts are grouped by company) |
| CORU `00770d47…` (Abu Auf) | CORU QA test, annotations only | The company is already in the dev split |
| CORU `00bcc1af…` (Breadfast) | CORU QA test, annotations only | Not needed once three receipts from new companies were chosen; image never downloaded |

The choice was made by the session itself, not by a rule fixed in advance. These exclusions are why the split is
15 documents, and they are recorded so the selection can be checked.
