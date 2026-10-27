# Security

## Reporting

Please report vulnerabilities privately through the repository's security advisory page
("Report a vulnerability"). Do not open a public issue. We aim to acknowledge reports within 3 working days.

## Threat model

Inklight reads documents from people you may not trust. It assumes:

| Threat | Defence |
|---|---|
| **Prompt injection in documents** ("ignore previous instructions…") | Plans are built **only from the user's request**, never from document text. Tools come from a fixed allow-list. Document text reaches models only inside a fenced data block. Instruction-like text is detected at index time and reported to the user as a warning. |
| **Unauthorised tool use** | No shell, code-execution, network, or delete tool exists. The only side-effecting tool, `write_output`, needs an explicit grant (`--out`, `--yes`, an interactive confirm, or `allow_write=True`). It writes one new file inside the output folder and never overwrites by default. |
| **Path traversal / unsafe writes** | Output names must be plain file names (no `/`, `\`, `:` or `..`). They are sanitised (including Windows reserved names), resolved, and checked to stay inside the output folder. The HTTP `outputs` and `delete` endpoints apply the same containment checks. Doc ids must match `^[0-9a-f]{16}$`. |
| **Malicious or hostile files** | Magic-byte sniffing (a `.pdf` must start `%PDF-`, an image must match its signature), size limit (`limits.max_file_mb`), page limit (`limits.max_pages`), per-task file limit, and per-page failure isolation. Preview renders are capped at 40 MP. |
| **Resource exhaustion** | Step limit, per-step and per-task time budgets with cooperative cancellation (including inside model loops), bounded retries, a request-body cap on the server, a context budget for every model call, and a 1,536-token prompt cap on the writer. |
| **Spreadsheet formula injection** | CSV cells starting with `= + - @ \| \t \r` are prefixed with `'`, both in Python exports and in the browser's CSV download. Markdown cells are escaped. |
| **XSS in the web UI** | All document text is inserted with `textContent` (no `innerHTML`). A strict CSP sets `default-src 'self'` and `script-src 'self'`. `X-Frame-Options: DENY` and `nosniff` are set. |
| **CSRF / DNS rebinding** | The server binds to `127.0.0.1` by default. A Host-header allow-list blocks rebinding: besides localhost it accepts only the host of `--public-url` and those given to `--allowed-host` (or `INKLIGHT_ALLOWED_HOSTS`), and it is never switched off. Every non-GET request needs the `X-Inklight: 1` header, which cross-site pages cannot send because no CORS is enabled. Cookies are `HttpOnly` and `SameSite=Strict`. |
| **Network exposure** | `inklight serve` refuses a network bind without `INKLIGHT_SERVER_TOKEN` unless `--no-token` is given. The page sends the token in a header (typed when asked, or read once from `/#token=…` and removed from the address bar); the server answers with an `HttpOnly` cookie holding a value derived from it, so no URL and no log holds the token, and the server never prints it. The comparison is constant-time. A token gives access to one shared library: it does not separate users. Forwarded headers count only from `--trusted-proxy` addresses. `--share` binds 127.0.0.1 and opens a Cloudflare quick tunnel only when asked: the tunnel client is a pinned release checked against pinned SHA-256 values, the server accepts only the tunnel's exact host name, the token stays required (at least 16 characters; `--no-token` is refused), and Cloudflare carries the traffic. See [docs/HOSTING.md](docs/HOSTING.md). |
| **Public demo visitors** | `--demo` gives each visitor a session (a random `HttpOnly` cookie) with a temporary library of its own: documents, index, questions, reviews, exports and import jobs. Ids from another session are unknown on every endpoint. The owner's library is never opened. Sessions and their files are deleted after a fixed time (60 minutes by default) and when the server stops. Uploads (which must declare their size), pages, documents per visitor, one import and one question at a time per visitor, the shared import queue (places taken atomically), concurrent renders and questions, requests per minute and sessions per address are limited; settings, saved outputs, optional models and remote models are off. |
| **Data leakage** | Processing is local by default. A remote model is used only when you configure `models.remote_base_url` (https only, except localhost). Only the question plus a bounded evidence excerpt is sent. API keys are read from an environment variable and never echoed in errors. Document text is not logged unless `privacy.log_document_text = true`. Error messages show file names, not full paths. |
| **Hallucinated answers** | Answers come from labelled fields, extractive spans (the reader can only copy text), or quoted sentences. Generated wording (writer or remote) is accepted only if it is grounded in the evidence: numbers and names must appear there, and a remote quote must match the document. Remote wording is labelled "unverified". Citations that cannot be found in the stored text are dropped. These checks establish *provenance*, not semantic correctness: "Bob owes Acme" and "Acme owes Bob" share every word, so generated wording must also keep the evidence's order of names and numbers, and is otherwise discarded. |
| **Answering a different question** | Conditions form one typed Boolean expression. The same object is executed and shown in "Understood as". `validate_plan()` refuses any plan whose steps do not filter with exactly that expression before the records are used or exported. If the filter fails, no records are returned. Each condition records the words it came from. Leftover constraint words ("paid late", "last month", an unattached name, a dangling "or X", an amount with an unknown unit) are reported as *Not applied*: the task is `partial` and nothing is exported. A mix of `and`/`or` across different fields is `unsupported` and not guessed. Amounts in different currencies are never compared or summed together. These are pattern-based checks: they catch the listed forms, not every way a request can be phrased. |

## Residual risks (known, accepted for a local-first tool)

- Without `INKLIGHT_SERVER_TOKEN`, any local process or user on the machine can call the local API.
- A public demo runs visitors' files through the OCR on your server. Its limits bound the work, but a determined
  visitor can still use the share of the server those limits allow; put a demo behind HTTPS and watch its load.
- OCR can misread text. Values carry confidence and provenance, but OCR output is never ground truth.
- The prompt-injection detector is a heuristic. It informs the user; it is not what keeps the system
  safe (the architecture is).
- Python cannot kill threads: a step that ignores cancellation (a stuck native call) keeps running in the
  background after its task returns `cancelled`. Its late writes are discarded.
