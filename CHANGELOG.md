# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.3.2] — 2026-10-28

### Added
- **`inklight serve --share`: a public `https://` link from anywhere**, Colab and machines behind NAT included,
  without opening a port. The server listens on 127.0.0.1; a Cloudflare quick tunnel (no account) gives a random
  `trycloudflare.com` address, and Cloudflare carries the traffic. The link is printed only once the workspace has
  answered through it. A private workspace keeps its token (16+ characters; never in the link, the tunnel's command
  or the output); `--share --demo` gives each visitor a temporary library. The server accepts only the tunnel's exact
  host name, and trusts forwarded addresses only from the tunnel on this machine. Cloudflare's `cloudflared` 2026.10.0
  is downloaded on the first `--share` only, checked against pinned SHA-256 values, and kept in the model cache.
  Ctrl+C stops the server and the tunnel; a killed Inklight takes the tunnel with it. A plain
  `inklight serve` is unchanged.
- Import progress falls back to asking every second when a proxy or tunnel holds the progress stream back.

## [0.3.1] — 2026-10-27

### Fixed
- **Opening a server by its IP address said "Host not allowed".** `inklight serve --host 0.0.0.0` accepted only
  localhost unless `--public-url` named the address, so `http://<server IP>:8765` was refused. On a network bind,
  any IP address is now an accepted host, a cloud server's public IP included, and the start-up summary prints this
  machine's addresses as links. Domain names still have to be given (`--public-url`, `--allowed-host`): DNS
  rebinding arrives with a domain name, never an IP address. A refused host name now gets a message naming it and
  saying how to allow it. A local workspace (`127.0.0.1`) and the private workspace's token are unchanged.
- The Colab section of docs/HOSTING.md showed an untested example; it now says Colab's in-notebook view is not
  supported in 0.3.x.

## [0.3.0] — 2026-10-27

The 0.3 line as a normal release: `pip install inklight` now installs it. Nothing in it is new accuracy work; results
are proposals to check against the page, and Inklight is not suited to unattended processing (README, Limitations).

### Hosting
- **Accurate start-up summary.** A network bind no longer advertises `http://127.0.0.1:8765`. `inklight serve` shows
  where it listens (`0.0.0.0` is reported as a bind address, not a browser address), the address visitors use (only
  the one given with the new `--public-url`, marked as not checked), which host names it accepts, the library it opens
  and the firewall/security-group rule other machines need. A browser is never opened for a network bind or on a
  machine without a display.
- **Private workspace.** A network bind now requires `INKLIGHT_SERVER_TOKEN` (or an explicit `--no-token`). The page
  asks for the token, sends it in a header and gets an `HttpOnly` cookie derived from it for previews and progress
  streams; the token is no longer accepted in URLs (`?token=`), so it stays out of proxy and server logs. It is never
  printed. The summary and the workspace say that everyone with the token shares one library.
- **Public demo** (`--demo`). Each visitor gets a session with a temporary library of their own (documents, index,
  questions, reviews, exports, import jobs); ids from another session are unknown on every endpoint, and the owner's
  library is never opened. Sessions and their files are deleted after 60 minutes (`--demo-minutes`) and when the
  server stops; the page tells visitors when. Limits: 10 MB, 15 pages and 5 files per upload, 15 documents per
  visitor (waiting files count), one import and one question at a time per visitor, one import read at a time for
  everyone with at most 6 waiting ("The demo is busy" otherwise), two page renders or questions at once, 90 changes
  and 600 requests a minute per visitor, 40 sessions, 12 new sessions per address (IPv6: per /64) per hour. The OCR engine and its models are
  loaded once for all visitors. Settings, saved outputs, optional models and remote models are off.
- **Reverse proxies.** The workspace's requests are relative to its page, so it works at a prefix
  (`https://example.org/inklight/`). Forwarded headers are trusted only from `--trusted-proxy` addresses. Host checks
  stay on: `--public-url` and `--allowed-host` name the accepted hosts.
- **Deployment.** [docs/HOSTING.md](docs/HOSTING.md) covers the three modes, HTTPS, Docker and Google Colab;
  [docs/deploy/](docs/deploy/) is a tested Docker Compose example with Caddy (automatic HTTPS) in front of a private
  workspace (persistent volumes) and a public demo (memory-backed temporary storage), sharing one model cache. The
  Docker image now needs a token for its default private workspace.

## [0.3.0b3] — 2026-10-27 — Developer beta

A small patch to 0.3.0b2. Still a pre-release: install it with `pip install --pre "inklight[structure]"` or pin
`inklight==0.3.0b3`; a plain `pip install inklight` still gets 0.1.0.

### Fixed
- **Text files needed the OCR models.** `inklight process` (and the other commands that read files) downloaded the
  OCR models, and the structure models when structure is on, before reading anything, even when every file was
  plain text; importing a batch of text files also loaded the structure models. Models are now fetched and loaded
  only for files that need them (PDFs and images), so `.txt` and `.md` files are imported, shown and searched with
  no model downloaded. A fresh container or a machine without a model cache can now read text files offline.
- **README links on PyPI.** Links to the docs, examples, evaluation report, licenses and README sections were
  relative to the repository and broke on PyPI; they now point at GitHub.
- The Docker image records its source commit (`docker build --build-arg INKLIGHT_COMMIT=$(git rev-parse HEAD)`).

## [0.3.0b2] — 2026-10-27 — Developer beta (first beta on PyPI)

A beta for developers and careful users: check every value against its page. Install it with
`pip install --pre "inklight[structure]"` or pin `inklight==0.3.0b2`; a plain `pip install inklight` still gets 0.1.0.

### Packaging and repository
- **Installed files.** The wheel holds only the `inklight` package: code, the workspace's static files and license
  files. The sdist now holds only what builds that wheel; it used to ship tests that needed `bench/` and `pilot/`
  helpers it did not include, plus docs and screenshots. CI fails a build that lets anything else in
  (`.github/scripts/check_dist.py`).
- **Build provenance.** A wheel built from the sdist (as `python -m build` does) said "commit unknown". The sdist
  now records the source commit, and every wheel built from it keeps it; CI and the release check the exact commit.
- **Your library is not part of the installation.** It lives in `~/.inklight` (or `INKLIGHT_HOME`), shared by every
  installation, which is why a fresh install could open documents read earlier. `inklight serve` now says which
  library it opens.
- **Docker.** The image could not build: the Dockerfile did not copy the build hook or `NOTICE`. The build context
  is now an allow-list of what the install needs.
- **Repository.** Superseded evaluation runs, the 0.2 notebook and the unstarted invoice pilot moved out of the
  active tree (13.6 MiB); they stay in Git at `146d275`, listed in [evaluation/ARCHIVE.md](evaluation/ARCHIVE.md).
  The reports keep every result and failure. README examples now say how to get the sample files when installed
  from PyPI; `examples/README.md` describes them.
- `inklight process` shows how each document was read, as `inklight docs` does.

### Workspace
- **Redesigned** as a light-table for documents: graphite (or paper, in the light theme) panels, one cyan accent for
  what is active, a framed page canvas, a readout of the marked box's page coordinates, and a theme switch (system,
  light, dark).
- **Import timeline** per file, built only from the states the server reports: upload, waiting, OCR (page n of m),
  structure (shown only once the server reports it), stored, or the stage where it failed.
- **Opening and ticking look different**: the name opens a document (accent bar, "open"); the box puts it in the scope
  of an operation (counted above the list).
- **Guided start**: an empty workspace explains the three steps, and each operation says what to do when nothing is
  open yet.
- Motion: a scan line only while OCR runs, a quiet frame while structuring (no per-region progress exists), regions and
  table rows appearing as they arrive, a source mark locking onto its box. The panel eases in only when the operation
  changes. Reduced motion keeps every state without movement.

### Fixed
- Approving or deciding a review opened from the list could send an empty reviewer name with no field to type one.
  The review card now shows the reviewer field and blocks decisions until it is filled; the name typed works even
  when the browser blocks storage.
- Opening a review whose document was removed from the library did nothing; it now opens and says why the page is
  not shown.
- *Text with boxes (.json)* failed: the page parsed the JSON download and then asked it for its bytes.
- An upload to a server started before Inklight was updated crashed the page; it now reports what that server read.
- A type word ("receipts") dropped documents the classifier could not type; they now stay in scope, with a warning,
  and the result is partial.
- A file without a preview (a broken PDF) no longer shows the start guide while it is being read.
- **Incomplete scope.** Asking about a selection that includes a document whose import failed, is still being read
  or was removed answered from the others as if complete. Every selected document is now checked first: the
  result is partial, starts with what it covers ("covers 1 of the 2 selected documents"), names each unreadable
  document and why, and lists them in a new `scope` field (requested, used, unavailable). A comparison marks them
  "not available" and cannot conclude; nothing is concluded when no selected document can be read. Asking never
  retries an import. `inklight ask --doc NAME` asks about library documents as they are.
- **Model download from two processes.** Two Inklight processes sharing the model cache (a second server, the CLI)
  wrote to the same `<file>.part`; one could fail with `FileNotFoundError: …lm_cjk.npz.part` after the other moved
  the finished file into place. A set is now downloaded under an OS file lock: the other process waits ("another
  Inklight process is downloading them") and then uses the verified copy. The lock is released if its holder dies,
  and the next download resumes the partial file.
- **Step labels** in the operation panel were cut off with an ellipsis on narrower panels; they now wrap, and move
  onto a second row with large text.
- **How a document was read.** A `.txt` file was labelled "read by OCR": every page that was not a PDF text layer was
  called OCR. The workspace (library, viewer, text and field panels, raw CSV), `inklight docs` and `/api/documents`
  (`read_as`) now name the page sources: plain text, PDF text layer, OCR, or mixed.
- **Field extraction and questions agreed less than they should.** Extraction read printed labels, not table cells,
  so "registration number" came back empty where "What is the registration number?" read 47319 in a table. A field
  is now read with the same routine a question and a comparison use: an empty field is read at its label or table
  cell (cited, type-checked, never from a passage); a value read from the line layout across lines yields to the
  table's own cell; several cells under one heading are listed as candidates, none chosen; any other difference
  from a table cell is flagged. On the Voxel51 and CORD holdout splits the field results are unchanged (no
  structure there).

### Evaluation
- [Technical report](evaluation/REPORT.md) with current reruns, the 0.2 → 0.3 equivalence check and a sourced
  comparison with five document parsers.

## [0.3.0b1] — Developer beta (GitHub only, not on PyPI)

One product to install and run: the OCR and document structure models run inside Inklight. The workspace is
redesigned around operations, and the repository is cleaned up.

### Internal model backends
- **Inklight OCR** (`inklight/backends/ocr`) runs the OCR models with ONNX Runtime, through Inklight's own code:
  detection, recognition (Latin, Arabic and other scripts), page orientation, reading order, the PDF text-layer
  checks. The code is taken from indra-ocr 1.1.2, without its CLI, viewer and process pool.
- **Inklight document structure** (`inklight/backends/structure`) runs the Heron layout model (ONNX) and TableFormer
  (PyTorch), with layout post-processing, table cell matching, page assembly and rule-based reading order. The code
  is taken from Docling 2.142.1 and docling-ibm-models 4.0.4, cut down to the path Inklight uses. The RT-DETR image
  preprocessing is reproduced exactly (same tensor, checked bit for bit) without transformers.
- `indra-ocr`, `docling`, `docling-ibm-models`, `docling-parse` and `transformers` are no longer installed or
  imported. `docling-core` stays in `[structure]`: it is the data model of the stored structure and its exporters.
- **Model files are managed by Inklight** (`inklight/modelstore.py`):
  - Exact revisions (until now, Docling fetched `main`), and every file checked by SHA-256.
  - A persistent cache (`~/.cache/inklight`, or `INKLIGHT_MODEL_CACHE`). A Hugging Face cache copy of the same
    revision is used in place.
  - Downloads show their progress and resume after an interruption. A corrupt file is reported and fetched again.
  - With `INKLIGHT_OFFLINE=1` nothing is downloaded.
  - `inklight models status` shows where each set is, and `inklight models pull --structure` fetches everything.
- **PDFium calls are serialised** across threads (`inklight/pdfium_lock.py`). The structure worker, the OCR and the
  workspace's previews could call it at once, failing a page or crashing the process.
- **Old versus new, same model files and settings, real models.** The subset was 17 documents: Arabic, English
  and mixed text; scans, digital PDFs and images; rotated pages; tables; Arabic-Indic digits; and a broken file.
  - OCR: identical on every page (text, boxes, confidences, orientation).
  - The 3 image files: identical end to end, structure included.
  - Tables: identical on all 17 (rows, columns, cells, header flags).
  - Layout on PDFs differs on all 13 readable PDFs: on 5 only box positions moved (at most 1.4 px), on 8 some
    blocks are labelled, merged or ordered differently. Docling rendered PDF pages with its own C++
    rasteriser (docling-parse), which is not reproduced bit for bit; the page images are prepared as before (a
    144 dpi render stored as JPEG, an area-average 72 dpi view) to stay as close as possible.
  - Text: no OCR line is lost or added by structure on any document, and the broken file fails the same way.
  - The synthetic structure benchmark (`bench/structure/compare.py`) gives the same answer, score and citation on
    every question, with ingest 11.4 s instead of 18.1 s.
  - The baseline itself was deterministic: two runs, identical output.
  - A clean environment without the old packages gave the same output as the development environment.
- Settings: `[ocr] engine = "inklight"` and `[structure] engine = "inklight"`; `"indra"` and `"docling"` are still
  accepted. Removed: `structure.table_model` (TableFormer V2), `structure.layout_runtime` (the PyTorch layout
  runtime) and `structure.artifacts_path` (models live in the model cache).

### Workspace
- **Operations first.** The top bar offers Extract text, Extract tables, Extract fields, Search, and Review & export;
  Ask is secondary and marked experimental.
- **Layout.** A library on the left, a large viewer in the middle, the operation and its result on the right. Each
  operation shows its steps, its scope (the open document or the ticked ones) and one main next action.
- **Imports run in the background** and the workspace follows them over server-sent events: each file waits, is
  read (page by page, as the OCR reports), is structured, then is read or not read (with the reason). A reloaded page
  finds a running import, which can be stopped before its next file.
- **First-use downloads** show the bytes received.
- **Extract tables** offers to read a document again with structure when it was read without.
- **Marks on the page** distinguish detected regions, search matches, the source of a value and values to check.
- **Motion is short and tied to real events**, paused in a hidden tab, and replaced by static states under
  `prefers-reduced-motion`.
- **Accessibility.** Keyboard focus is visible and status changes are announced. Light and dark themes and narrow
  screens are supported.

### Usage
- **Direct operations.** `inklight text FILE` and `inklight tables FILE` print or save a document's text or tables.
  In Python, `DocumentAgent.text()` and `.tables()` do the same.
- `inklight extract` asks for the fields to read; it no longer assumes an invoice schema.
- `inklight --help` groups the commands.
- **A document read before structure was turned on** is read again with its structure when it is next added with
  structure on.

### Repository
- Old showcase scripts, images and outputs are removed, along with an unused screenshot, the landing-page export,
  and the one-time publishing guide.
- Evaluation reports and raw results move to `evaluation/`, with an index. Local user folders in stored results are
  shortened to `~` and `<scratch>`.
- Two small synthetic samples are added to `examples/documents` (a registration card scanned sideways, a two-table
  suppliers sheet).

## [0.2.0b1] — Developer beta (GitHub only, not on PyPI)

A local document workspace built from the existing components (Indra OCR, optional Docling structure, review).
No new models, datasets or benchmarks. Answering questions remains experimental.

### Added
- **Document tab** in the workspace: each page's OCR text (right to left for Arabic, per-line direction for mixed
  text), the tables Docling recovered, and the structure status per page, including pages turned and structured
  upright, or the reason structure is unavailable.
- **Raw exports** of a document: text, JSON with boxes and tables, tables CSV. Each starts with a note that it is the
  raw reading, not reviewed. Approved review exports now include the source page.
- **Outcomes on every result** (API `outcome`, CLI "Outcome:" line, first line of each workspace card): extracted
  text, proposed answer, supported answer, partial result, missing evidence, several candidates, unsupported, failed.
- **Candidates to choose from** when several values match, each with its page and box; the choice is shown as a
  proposed value, not an answer.
- **Field comparison** across documents ("compare the registration number in these documents"): each document's
  value and evidence, then matches / differs / cannot determine. A comparison without a named field is labelled a
  text comparison.
- `inklight --version` and the workspace footer show the build's source commit (stamped into the wheel).

### Changed
- A run of field names merged into one block (as Docling can do on registers) is declined instead of returned as a
  value.
- Review proposes a value for an empty field only when it is a supported answer at a printed label or table cell.
- Upload reports per-file success, failure and warnings; uploads keep their original names.
- "OCR" confidence is shown as "OCR estimate" and never presented as a guarantee.
- The CLI reports a missing file by name; the first-run model notice no longer repeats after the models are cached.
- Ask is labelled experimental in the workspace.
- After an independent review of the beta: a "number" field is never proposed from text without digits (a
  bilingual table's label); a value taken from a row of several cells, or mixing Arabic and Latin text, is flagged;
  Arabic field names work in review and extraction; a number or date question answered by a passage without digits
  is *missing evidence*; a comparison shows each document's warnings and does not report "differs" on a doubtful
  reading; approved exports mark superseded reviews and include the source box; the raw tables CSV starts with its
  header and the raw JSON leaves out the local path.

### Known limitations of this beta
- Arabic-Indic digits are often misread by OCR; the Document tab and table view do not mark doubtful cells.
- A table on a turned page can be split differently from the upright scan.
- *Proposed* answers can be wrong without a specific warning (a registration date offered for an expiry date).

### Checked and not adopted
- A local 4B multilingual instruction model as planner/answerer: 0 of 8 workflow tasks, the same as without it. Not
  integrated; the remote-model option stays off by default.

## [0.1.1] — Unreleased

Fixes from a second external review of `914d321`. **0.1.0 (already on PyPI) is affected by the three
defects below.** Upgrade once 0.1.1 is published.

### Fixed
- **Conditions on extraction were not applied.** "Extract totals from Acme" showed the Acme condition under
  "Understood as" but returned every document: the extraction plan had no filter step. Conditions are now
  enforced first for every workflow (extract, filter, count, aggregate, inconsistencies, summarize,
  compare, find, ask, export). The document scope narrows to the matches before the operation runs.
- **Boolean grouping was flattened.** "between $100 and $6,000 or above $10,000" became
  `>=100 OR <=6000 OR >10000`. Conditions are now a typed expression (`Cond | All[...] | Any[...]`).
  Ranges, years and months are grouped operands, and `or` between alternatives on the same field forms one
  group. The same expression is executed and rendered in "Understood as", so the two cannot drift apart.
- **Coordinated names were dropped.** "from Acme or Globex" silently lost Globex. Vendor lists
  ("Acme or Globex", "Acme, Globex and Initech") are one group, and a shared amount condition applies to the
  whole group. "not from Acme or Globex" excludes both.
- **Dropped fragments are reported.** A connector left after a condition ("… above $5,000 or Globex"), an
  unconsumed proper noun ("List Acme's invoices"), a month without a year, a time span such as
  "under 30 days", and an amount with an unknown unit ("over 5 bucks") make the result `partial` and are
  listed under Not applied.
- **Partial selections are never exported.** `write_output` refuses while any part of the request is not
  applied. Partial previews are labelled "PARTIAL RESULT, not the complete answer to your request".
- **Ambiguous `and`/`or` mixes are not guessed.** For example "from Acme or above $10,000 in 2026". Nothing
  runs, and the result state is the new `unsupported`.
- **Filtering failures cannot leak unfiltered rows.** If the filter step fails, or `max_steps` would cut it
  off, no records are returned and the state is `failed`.
- A filter that could not evaluate some documents (missing value, incompatible currency) is now `partial`,
  not `succeeded`.
- Added "N grand" (×1000) and month-year ranges ("in March 2026").

### Changed
- `validate_plan()` refuses any plan whose steps do not filter with exactly the stated expression, after
  extracting every field it reads, and before any step that uses records or the document scope.
- Requested output columns are kept separate from fields read only to evaluate conditions. Records,
  tables, CSV and JSON exports show only the requested columns.
- The optional 135M writer can no longer replace an answer. Its wording is appended under an explicit
  "not verified" label. `grounded()` is documented as a surface check (entity order and negation count),
  not semantic verification.
- Results carry `checks`, which keeps provenance, interpretation and evidence separate. The confidence fields
  are documented as heuristics, not calibrated probabilities.
- The `TaskState` enum gained `unsupported`.

### Layout-aware answers (`bcd4752`, `915be7b`)
Measured in [evaluation/EVALUATION.md](evaluation/EVALUATION.md#labels-and-values-on-the-page-915be7b).
- **Labels paired with values across OCR columns.** Visual rows group lines by bounding box, ordered by the
  script's direction (Arabic right to left).
  - *Extraction.* A money or date field whose label has no value in reading direction tries the other side
    of its row. Several values on one row are flagged.
  - *Answers.* Date, amount and count answers can be supported by a row as well as a sentence. Answers keep
    their page and box.
- **Questions that name a printed label** ("What is the product?", "ما هي الكثافة؟") are answered with the
  value beside or below that label, with page and box, and without a model call.
  - Titles, document-noun headings and prose are not labels.
  - Several candidate values, or several matching labels, are flagged.
  - A label left blank on a form is declined.
- **Every line of a reader answer is checked.** A multi-line span must sit in one sentence or one visual row.
  A continuation that adds its own date, amount or "Label:" is cut, and the sentence that holds the rest is
  cited.
- **Evaluation**:
  - Each answer is also scored for the same entity, allowing Arabic particles such as "لتركيا" for "تركيا";
    exact transcription is still reported.
  - Pairing accuracy, page and box are reported per field.
  - New splits fresh4 (12 documents) and fresh5 (10), each with expectations written before first access.
    - fresh4: no change.
    - fresh5: answerable questions correct 27 → 32 of 44, silent wrong 9 → 8, one incorrect decline.
- **README lead image**: real screenshots of the latest build, covering an English letter, an Arabic letter,
  an English form and a mixed receipt (labelled as a development example).

### Fixed: a label's qualifier and section
Three answers reproduced on `2a628c1`, each returned without a warning:
- the shipping address taken from "Billing Address:";
- the delivery date taken from "Invoice Date:";
- Alice's salary taken from the "Salary:" printed under Bob.

The fixes:
- **A label naming a different field is not used.** This holds when the label has a word the question lacks
  ("billing") and the question has one the label lacks ("shipping"). Such a value is declined, as is a bare
  label returned as an answer ("Invoice Date:"). A qualifying document word is kept, so "the invoice date" is
  not answered from "Due Date:".
- **Copies of a repeated label are told apart by the section above each.** A section runs from the label that
  opens it ("Employee: Bob Turner") or from the person's heading.
  - A question naming no one, or someone under none of the copies, gets each copy listed with its section. None
    is picked.
  - A single label outside the named section is flagged on a page divided into sections.
  - Any answer to a question naming something the document never prints is flagged.
- **The other answering paths are checked the same way.** This covers the field shortcut, the reader, the
  rules, and plain-text documents (laid out as one column for the check). Only the first cited source is checked.
- **What counts as a name.** A run of capitalised words is a name when the document prints any of it outside its
  labels ("Bob Turner", "Security Council"). Otherwise it is the field asked for ("What's the Shipping
  address?"). "The company's address" names no one; "globex’s invoice" names the vendor the document prints.
- **Development data only.** On the dev, reserved and fresh–fresh4 splits (473 questions, models on), no answer
  was lost.
  - Five changed for the better: two Aswan infobox answers and a receipt number became correct, a flagged total
    became unflagged, and an unanswerable bank-account question was declined.
  - In rules mode, two more silent errors became declines.
- **Not handled:**
  - "What is the date?" on a page with both an invoice and a delivery date gives the invoice date.
  - Arabic names are not detected, so Arabic copies of a label are listed, not chosen between.
  - In plain text, a value cited beside another field's label is flagged, not corrected.

### Fixed after the agent-run evaluation (amendment AM-1)
- **A form label is no longer returned as a value.** A register's numbered field names ("١- نوع الشركة" over
  "(ب) ٢- عنوان الشركة") were read as each other's values. List markers are stripped from labels, a numbered field
  name or "Label: value" line is never another label's value, a field with no readable value is declined with its
  page, and every answer path declines an answer that is one of the page's field names.
- **Several candidates are listed, not silently chosen**: the same heading in two tables, the same field on two
  pages or in two documents (label path, table path, field shortcut). A question naming one gets that one.
- **The documents you pass are kept**: a type word in the request ("the contract", "the letters") no longer drops
  files the user chose (`DocumentAgent.ask` and `inklight ask FILE FILE ...`); "only the contracts" still narrows.
  Fixes the false "Comparison needs at least two documents".
- **Rotated pages get structure**: Docling is given pages Indra read turned (90/180/270) turned upright; one
  coordinate transform (`inklight.frames`) links stored boxes, table cells and citations shown on the page.
- Measured on the same workload: failures safer, task completion unchanged (evaluation/AGENT_EVALUATION.md, AM-1).

### Evaluated: agent-run workflows on real documents (no code change)
- 38 tasks on 25 documents (mostly scanned Egyptian registers, tax cards and VAT certificates), run by a user agent
  through the CLI with structure off and on, judged blind. The tool completed 2 of 76 runs; Docling and the small
  models changed nothing material. Failures, three proposed fixes with reproductions, and the harness:
  [evaluation/AGENT_EVALUATION.md](evaluation/AGENT_EVALUATION.md), `bench/agent_eval/`, `evaluation/results/agent_eval/`.

### Added: document structure from Docling on Indra's OCR (optional)
- **`[structure] engine = "docling"`** (extra: `pip install "inklight[structure]"`) runs Docling's existing components
  on each document Indra has read: the Heron layout model, reading order and TableFormer, through Docling's
  supported OCR-engine extension point. The engine hands Docling Indra's stored lines; Docling does no OCR of its own
  (`OcrMode.FULL_PAGE`, and PDFs passed as page images). Details: [docs/STRUCTURE.md](docs/STRUCTURE.md).
  - Each document records cells delivered, foreign tokens (0) and orphan lines; lines no Docling item holds are
    kept as blocks.
  - The DoclingDocument is stored per document (new `structures` table, `blocks.ref`). It is exported by
    `inklight structure DOC --format md|json|html|meta` and `GET /api/documents/{id}/structure`.
  - Original OCR lines are unchanged. Tables are searched as rows of "header: value"; text inside pictures is
    kept and searchable.
- **Answers from table cells:**
  - the value under the heading that names the field, never the heading;
  - the row named by the question's other words; several rows with nothing to choose are listed;
  - "who" lookups, and field/value tables;
  - blank cells and unreadable dates are declined; cells OCR read with low confidence are flagged.
- **Measured on synthetic registration cards** (Arabic, English, mixed; fixed Indra OCR; rules mode), correct
  answers, `030dd41` → this build with Docling:
  - Arabic 0 → 10 of 18 (the 6 wrong are flagged Indra misreads);
  - English 2 → 18 of 18;
  - mixed 6 → 10 of 10;
  - silent wrong 17 → 0.

  Cost: about 1.1 GB peak memory and 1.4 s for a one-page card with three tables. A one-time model load of
  4.6 s overlaps Indra's OCR.
- **Faster structure, same answers:**
  - All CPU cores are used; the Heron layout model runs as Docling's ONNX export.
  - The models load during Indra's OCR, and documents are structured while the next one is read.
  - Results: 3.0 s → 1.4 s for a one-page card; 15.5 s → 10.1 s for 9 pages.
  - TableFormer remains most of the time.
  - Faster options with a measured accuracy cost are off by default: `table_mode = "fast"`, `table_model =
    "tableformer_v2"` and `pages = "tables"`. Details: [docs/STRUCTURE.md](docs/STRUCTURE.md#speed).

### Fixed: headings and citations (with or without structure)
- An answer that only repeats the question's words, or equals a table heading, is declined. "اسم الشركة" was
  returned for "ما اسم الشركة؟", and "Company name" for "What is the company name?".
- **Citations are verified line by line.** A label-and-value citation of two separate lines was being dropped.
- **An answer whose every citation fails verification is marked "Unverified".** It is flagged and its confidence
  capped at 0.2; it is no longer presented as supported.
- **Choosing labels and values:**
  - Generic question words break ties between labels ("company type" vs "company name").
  - The value under a label is the line most squarely under it among value-like lines, not the neighbouring
    column's.
  - A label's value OCR read with confidence below 0.85 is flagged.
- **Search folds the Persian yeh and keheh (ی ک) into Arabic ي and ك.** OCR writes "مدیر" for "مدير". Schema
  version 4; existing libraries are re-indexed when opened, and the shown text is unchanged. After that, an
  older Inklight version can still read the library, but cannot add documents to it (blocks gained a `ref`
  column).
- **Classification:** commercial-register certificates and tax cards are certificates, not contracts, even when
  they cite the company's articles ("عقد التأسيس").
- On the 473 development questions, `030dd41` → this build (structure off): no correct answer lost, and silent
  errors became declined or flagged (3 silent errors with models on, 5 in rules mode).

### Fixed after evaluating on external documents (third review)
Found by running real OCR on Voxel51 invoices and CORD receipts (dev splits; see
[evaluation/BENCHMARKS.md](evaluation/BENCHMARKS.md#external-datasets)). Holdout field accuracy, 0.1.0 → this release:
synthetic invoices 41.7% → 99.7% (silent errors 30.8% → 0.3%), genuine receipts 3.2% → 68.5%.
- **Two-column layouts took the wrong value.** In a "Seller: / Client:" block, the line after a label in
  reading order belongs to the other column, so an IBAN or the seller's name was returned as the customer.
  When lines have boxes, a lone label now takes the value to its right on the same row, or else the value
  below it in the same column.
- **Summary rows** ("Total  $ 2 205,34  $ 220,53  $ 2 425,87") are resolved by their column titles (Net worth →
  subtotal, VAT → tax, Gross worth → total). A row without titles is flagged, not guessed.
- **Amounts**: `$ 2 425,87` (spaces after a currency symbol), `16,363` / `7.000` / `Rp. 28.636`
  (thousands-grouped amounts without cents, IDR), an amount OCR split into `177` `870`, and a label followed
  by a rate ("Tax 10%"). A money cell must account for every digit in it.
- Cash tendered and change are never the inferred total.
- **Amounts OCR may have misread are flagged, on agreeing evidence only.**
  - *When:* an amount is flagged only when independent signals agree. The signals are: the document's
    number format (no cents, or a zero-decimal currency) against an amount with cents; an
    order-of-magnitude break against other non-payment amounts; low OCR confidence; and a second OCR
    reading of the enlarged image region that disagrees.
  - *What a flag does:* the value and its OCR text are kept. The warning gives the reasons, the second
    reading and the source box. Confidence is halved, and the value is no longer marked verified.
  - *Result:* on a fresh, de-duplicated split, silent receipt errors went from 6 to 4 of 127, with 0 correct
    values flagged out of 887 across dev and fresh.
  - *What it replaces:* an interim rule (`e61a8d6`) that flagged any total under half its subtotal, which a
    discount or deposit trips.
- **"The total of invoices above $X" computes a sum.** It used to return the matching invoices, report
  success and compute no total. `AgentResult.calculation` now exposes the sum: op, result, unit, values used
  and values left out.
- Rupiah amounts in requests ("above Rp 50.000", "50,000 IDR").
- **Human review** (Review tab, `/api/reviews`, `inklight review list|export`):
  - Each prediction is frozen when the review opens, and the database refuses any change to it.
  - Reviewers accept, correct, enter or mark each field absent, then approve.
  - The history is append-only, and manual-entry mode hides the predictions for timing.
  - Export includes approved reviews only.
- **Pilot tooling** in `pilot/`: permission-checked intake with a vendor-grouped reserved split, a frozen
  baseline with `verify`, evaluation with confidence intervals and a logged reserved group, latency with and
  without the second reading, and a dry run. No genuine invoices have been collected yet.
- Model revisions can be pinned (`models.*_revision`), and `extraction.second_reading` can be switched off.
- **Strict parsing of typed amounts** (`inklight.entered`). "100 + 20", "1e3", "12abc 34" and irregular groups
  are refused with the reason; they are no longer turned into numbers by deleting characters. Accounting
  parentheses keep their sign. The reviewer's exact input is stored and exported next to the parsed value.
- **Typed dates follow the same rule** (`parse_entered_date`). A date can be typed the way the invoice prints
  it ("JAN04/00", "04-JAN-00", "Jan. 4, 2000"), which the review form used to refuse. Input with extra words
  ("01/31/82 approx") or two dates is now refused, where the first date used to be taken.
- **Names in every script are compared correctly** (`inklight.textnorm`): different Arabic names were equal
  in the inconsistency check, because every non-ASCII letter was deleted.
- Pilot evaluation:
  - The cohort and split are selected before any reprediction, and reserved access is logged first.
  - `--predictions frozen|cached|full` separates re-extraction from stored OCR from a full pipeline run in an
    isolated library, and records the provenance of each.
  - `check_rehearsal.py` and `REHEARSAL.md` cover the 5–10 invoice human rehearsal, which has not run yet.
- **The English-only models no longer touch Arabic.** Measured on identical documents and passages:
  - The reader turned correct Arabic passages into wrong spans (Arabic answers 17/36 → 3/36).
  - The embedder ranked the right Arabic document lower (top 3: 29/36 → 20/36).
  - Both still help English (answers 16/53 → 20/53, top 3: 37/53 → 42/53).

  Arabic queries now use keyword search, and the reader is not asked about Arabic. Each skip is stated in the
  result's `checks`. OCR is unaffected by the models: stored text was identical with them on or off. See
  [evaluation/EVALUATION.md](evaluation/EVALUATION.md).
- **Arabic requests are understood:** summarise, compare, count, extract and find. On the reserved split, Arabic
  summaries went from 0/9 recognised to 9/9, covering 17/27 key facts, every sentence quoted verbatim.
- **Arabic questions** are answered from the best-matching sentence: words, light stems, sentences and question
  types in Arabic. These answers are always flagged for review. On reserved: 11/23 right, 0 silently wrong (P0:
  1/23).
- **Answers must be connected to what was asked, not merely near it.** Sender, recipient and signer come from
  the letter's title, From/To lines or the signature line (English and Arabic, OCR damage tolerated). A date,
  amount or count must come from a sentence holding that value and the question's own words; a letter's heading
  date does not answer a question about an event; "Total (incl Tax)" is not the tax; otherwise the answer says no
  supporting evidence was found. On 11 new genuine documents, run once: correct 26 -> 30 of 44 answerable
  questions, silent wrong 7 -> 6, one answerable question declined; unanswerable questions about a mentioned
  subject answered silently 4 -> 1 of 8. One receipt answer regressed ("VAT-Inclusive" is not read as a
  qualifier).
- **Questions about something the documents never mention** ("What is the IBAN?" over a letter) are answered
  "I couldn't find supporting evidence for “IBAN” in the processed text of this document." instead of with the
  nearest sentence (it does not claim the fact is absent: OCR can miss words). On 15 new genuine
  documents, run once on the frozen build: 18 of 19 such questions declined (before: 0). Questions whose subject is
  mentioned but whose value is not are not covered: 6 of 11 are still answered silently. No answerable question
  was declined (0 of 42).
- **Evaluation runs keep complete answers and cited passages**, so they can be rescored exactly. The first-access
  source of the reserved and fresh runs is reconstructed; its re-run reproduces the stored results
  (`evaluation/results/usecases/provenance/`), which shows the same behaviour but is not a byte-exact recovery.
- **Requests Inklight cannot carry out** ("translate this", "email it", "sign it") are `unsupported` with the reason,
  instead of `succeeded`.
- **Questions about a document's content** stay questions: "Which city was hit…?" used to become an invoice filter.
  Letters, reports and forms no longer get invoice fields. "Compare the letter dates" compares dates. "Export the
  number, date and total of the invoices" is an export, not a sum.
- **Extraction:**
  - right-to-left label/value layouts
  - Arabic labels in the invoice preset
  - Arabic month names (Gregorian and Levantine)
  - Egyptian, Saudi and UAE currency forms
  - "Total Tendered" is not the total
  - parentheses restating a written amount are not negative
  - "Letter dated" dates a document only when it is a letter
- **Classification:** English and Arabic cues for letters, reports, receipts, invoices, contracts and forms, plus a
  certificate type (12 → 28 of 35 dev documents).
- **Search:** the index also strips the Arabic article ("بالنزاع" finds "النزاع"); library schema 3, re-indexed on
  open. A question about one or two documents with no keyword match reads their passages instead of answering
  "nothing found".
- **Review:** fields follow the document type unless given, the Review tab has a field box, and Arabic and mixed
  text lays out right to left in the workspace.
- **Evaluation:** `bench/usecases/` holds 75 documents in dev, reserved and fresh splits, expected results written
  before running, logged reserved access, a full pipeline per run, the model ablations and synthetic Arabic
  documents (labelled). Results are in `evaluation/results/usecases/`.
- **Broken Arabic PDF text layers are OCR'd instead of indexed.** The UN's Arabic PDFs carry a text layer in
  Arabic letters, but the wrong ones ("األمم" for "الأمم", "امرساااااا" for "المرسلة"). Indra's own checks
  accept it, so the broken text was indexed, searched and quoted.
  - *How it is detected:* `inklight.ocr.textcheck`. A page whose Arabic words show a split lam-alef or an
    alef run in at least 1.5% of words, judged on 20 or more Arabic words, is read by OCR instead, and the
    page and document say so.
  - *Diagnostic, default `auto` mode:* key phrases on the two Arabic digital documents went 0/3 → 3/3 and
    1/3 → 3/3, and QA 0/6 → 2/6. 18 pages were OCR'd again; ingest time for the 26 documents went 56 → 60 s.
  - *False positives:* none on 124 pages of correct Arabic (65 OCR'd pages, 59 Wikipedia text-layer pages).
  - If OCR of such a page fails or reads nothing, the layer is kept and the page says so. One page never
    ends the document.
  - Mode `text` still uses the layer as it is.
- **Arabic search no longer depends on optional marks or letter variants.** The full-text index and every
  query use `textnorm.search_form`:
  - harakat and tatweel removed
  - alef forms → ا, ى → ي, ة → ه
  - Unicode digits → ASCII

  "المستحق" now finds "المُستحق", "القاهره" finds "القاهرة", and "2023" finds "٢٠٢٣": 4/10 → 10/10 test
  queries. Queries are no longer split at a vowel mark. Excerpts still show the original text. Library
  schema version 2: a version 1 library is re-indexed when it is opened.
- **Extraction reads month-name dates as invoices print them**: "JAN04/00", "04-JAN-00", "19Jun'22",
  "Sept 30, 82". Before, only 4-digit years with spaces were read. On 80 INV-CDIP invoices and 60 Voxel51
  invoices with date labels, correct dates went from 131 to 136 of 151 and missing from 13 to 7. No value
  changed on any of the 180 Voxel51 and CORD documents, so earlier benchmark results stand. A year followed
  by ".5" or ":30" is not read as a year ("QTY 2 MAY 15.00"). Measured with `bench/compare_dates.py`.
- An issue date more than a year in the future is flagged ("check the year"); due, expiry and end dates are
  not. OCR had read "08-OCT-85" on a 1985 invoice scan as "08-OCT-35".
- The document viewer can be closed on narrow screens; below 1100 px it used to cover the tabs.
- **A sum or average that leaves documents out is `partial`, not `succeeded`.** Documents without a value
  were left out with only a warning. The answer now also says how many were left out.
- Indonesian tax labels (`pajak`, `ppn`, `pb1`, `p.rest`), plus `net worth` and `gross worth`.
- **Possessive requests**: "Show acme's invoices", curly apostrophes, the name first ("Acme's invoices above
  $5,000"), and coordinated owners. A possessive owner stops at a preposition ("terms on Acme's" → Acme) unless
  the preposition joins capitalised words ("Bank of America's").
- **Questions that name their document** ("What are the payment terms on the Acme invoice?") are answered
  only from documents matching that name. Before, the answer could come from another vendor's invoice.
  Such a question is no longer turned into a list of records.
- "from March" (a month without a year, after from/for/since/before/after/until) is reported as not
  applied. Before, it returned every document as a success.
- Words a request contains but no condition used are reported (a closed vocabulary), not ignored.

### Changed (third review)
- **Explicit, idempotent cleanup.** `DocumentAgent`, `Library` and `Store` have `close()` and are context
  managers. Each closes only what it created. `close()` cancels running tasks and waits for them, and using
  a closed store raises `StoreClosed`. The CLI closes its agents when a command ends. The server closes the
  agents it owns at shutdown, but not one passed in. Tests open and close resources with no
  `ResourceWarning`, and no warnings are filtered globally.
- `Brain.usage()` reports, per component, whether its model loaded, its inference calls and any fallback reason.
- New `bench/prepare_external.py`, `bench/external.py` and `bench/summarize_external.py`: external
  evaluation with provenance (commit, wheel hash, `inklight.__file__`), ONNX call counts per model, and
  four-way scoring (correct / abstained / wrong flagged / wrong silent).
- Documentation states measured results instead of general reliability claims.

## [0.1.0] — 2026-10-23

First public release candidate.

### Added
- Document library: incremental ingest (unchanged files skipped, identical content reuses OCR), SQLite +
  FTS5 index, layout-aware chunks, classification, prompt-injection scan, re-index and delete.
- Indra OCR backend (PDF text layer first, OCR where needed; PNG/JPEG/TIFF/BMP/WebP), plain-text and
  Markdown reader, pluggable engine registry.
- Typed field extraction with page/box provenance, confidence, warnings and `subtotal + tax = total`
  checks; schema files in three formats.
- Bounded agent: rule planner, 11 allow-listed tools, step limits, time budgets, cancellation, retries, trace.
- Small local models on ONNX Runtime: 66M extractive reader, 33M embedder (hybrid search), optional
  135M writer with grounding checks. Optional OpenAI-compatible remote model with quote verification.
- CLI (`process, ask, extract, search, docs, show, remove, reindex, history, watch, serve, tools, doctor, models`).
- Local web workspace: upload, library, page preview with evidence highlighting, agent, extraction, search, history, settings.
- Folder watcher automation.
- Benchmarks (`bench/`), 128 tests, CI and release workflows, Dockerfile.

### Fixed before release (external review of 478fc3d)
- Vendor and customer constraints ("invoices from Acme above $5,000") were silently dropped. They are now
  conditions (`vendor contains "Acme"`), including negation ("not from", "except").
- `or` between conditions was applied as AND. It now means any. A mix of `and`/`or` is reported instead of guessed.
- Added `between X and Y` and year conditions ("in 2026").
- Amounts in different currencies were summed into one number. Money values now carry a `unit`, sums are
  reported per currency, and filters never compare € amounts with a $ threshold.
- Requests with words no tool can apply ("paid late", "last month", "top 3", a stray amount) used to return
  `succeeded`. They now return `partial` and list the words under **Not applied**.
- Counting with conditions ("how many invoices above $8,000") ignored the conditions.
- Ambiguous numeric dates (`03/04/2026`) were read silently. They are now flagged, and `[extraction] day_first`
  sets the order.
- The currency is read from a label ("TOTAL DUE (USD)") when the amount has no symbol. Added EGP / E£.
- `grounded()` accepted "Acme owes Bob" against "Bob owes Acme". It now also requires the evidence's order of
  names and numbers, and is documented as a necessary check, not proof of correctness.
- Reader answers whose surroundings share no word with the question are penalised.

### Changed
- Results report confidence twice: `interpretation_confidence` (was the request understood) and
  `evidence_confidence` (do the documents support it). `confidence` is the lower of the two. Results also
  carry `interpretation` and `not_understood`, shown in the CLI and the web workspace.
- Docs: "verified" now explicitly means provenance (the text exists where cited), not semantic correctness.
- Benchmarks: three invoice layouts instead of one, plus a request-handling score.

### Configuration
- Config schema version `1`. Configs declaring a newer version are rejected with a clear message.
  Future migrations will run oldest-first in `config._migrate`.
- Library database schema version `1` (`meta.schema_version`).
