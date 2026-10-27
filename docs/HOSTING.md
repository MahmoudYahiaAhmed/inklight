# Hosting Inklight on a machine

`inklight serve` has three modes:

| Mode | Command | Who uses it | Documents |
|---|---|---|---|
| **Local** (default) | `inklight serve` | you, on this computer | your library (`~/.inklight`) |
| **Private workspace** | `inklight serve --host 0.0.0.0` with `INKLIGHT_SERVER_TOKEN` set | you or a trusted team | **one library shared by everyone who has the token** |
| **Public demo** | `inklight serve --host 0.0.0.0 --demo` | anyone with the link | a temporary library per visitor, deleted after 60 minutes |

A token does not separate users: everyone with it sees, adds and deletes the same documents. To let strangers try
Inklight, use the public demo, never a private workspace with a published token.

## Private workspace

```bash
pip install "inklight[structure]"
export INKLIGHT_SERVER_TOKEN="$(python -c "import secrets; print(secrets.token_urlsafe(24))")"
inklight serve --host 0.0.0.0 --port 8765
```

(On Windows PowerShell: `$env:INKLIGHT_SERVER_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(24))"`.)

- `0.0.0.0` is where the server listens (every network interface). It is not an address to open in a browser. The
  start-up summary prints this machine's addresses as links instead; it does not check they are reachable from
  elsewhere.
- Visitors open the server by any of its IP addresses, `http://203.0.113.7:8765`, including a cloud server's public
  IP, which the machine itself does not see. Domain names are refused unless listed: give the one visitors use with
  `--public-url https://docs.example.org/` (or `--allowed-host`). A DNS-rebinding attack always arrives with a domain
  name, never an IP address, so this keeps that protection. A refused name gets a message saying how to add it.
- Visitors open the address and type the token when the page asks for it (or open `…/#token=<token>` once; the
  page removes it from the address bar). The token is sent in a header; the server answers with a cookie holding a
  value derived from it, so the token never appears in a URL or a log. The server never prints it.
- Other machines can connect only if TCP 8765 is allowed inbound by the machine's firewall and, on a cloud server, its
  security group. Better: keep the port closed to the internet and put an HTTPS reverse proxy in front (below);
  without HTTPS the token and documents cross the network unencrypted.
- `--no-token` serves a private workspace without a token. Only for a network you trust completely: anyone who can
  reach the port can read and delete your documents.
- A browser is never opened for a network bind.

## Public demo

```bash
inklight serve --host 0.0.0.0 --port 8765 --demo
```

(add `--public-url https://demo.example.org/` to serve it under a domain, behind HTTPS)

- Each visitor gets a session (an HttpOnly cookie) with a library of its own in a temporary folder: their documents,
  index, questions, reviews, exports and import jobs. Ids from another session are unknown (404), whatever the
  endpoint: documents, page previews, downloads, jobs and their progress streams, reviews, questions.
- The owner's library is never opened. `--demo-dir` sets the folder for the temporary libraries; by default it is a
  new temporary folder, removed when the server stops. It may not be inside the owner's library.
- A session and its files are deleted 60 minutes after it starts (`--demo-minutes`), or when the server stops. The page
  tells the visitor the time. A session still importing or answering is removed once that finishes.
- Limits per visitor: 15 documents (files still waiting count), 10 MB and 15 pages each, 5 files per upload, one
  import and one question at a time, 90 changes and 600 requests per minute. For the server: one file is read at a
  time for everyone, at most 6 imports waiting (a full queue is refused with "The demo is busy", never left waiting),
  two page renders or questions at once, at most 40 sessions, 12 new sessions per address (an IPv6 /64) per hour.
  A request body must declare its size, so an upload is bounded before it is stored.
- Model weights are loaded once and shared by every visitor; documents never are. Optional Ask models, a remote
  model, saved outputs and settings changes are off in the demo.
- Serve it over HTTPS. Behind a proxy, pass `--trusted-proxy <proxy address>` so the visitor's own address (not the
  proxy's) counts for the per-address limit, and so cookies are marked Secure.

## Behind an HTTPS reverse proxy

The workspace's requests are relative to its page, so it works at a prefix such as `https://example.org/inklight/`.
The proxy must strip the prefix, pass the original `Host` header, and set `X-Forwarded-For` and `X-Forwarded-Proto`.
Start Inklight with the public URL and the proxy's address:

```bash
inklight serve --host 127.0.0.1 --port 8765 --public-url https://example.org/inklight/ --trusted-proxy 127.0.0.1
```

Forwarded headers are ignored unless they come from an address given to `--trusted-proxy`. Host checking is never
switched off.

[deploy/](deploy/) holds a tested Docker Compose example: Caddy (automatic HTTPS) in front of a private workspace at
`/inklight/` (its library and the models in volumes) and a public demo at `/demo/` (its libraries in a memory-backed
`/tmp`), both sharing one model cache:

```bash
cd docs/deploy
export INKLIGHT_SITE=docs.example.org
export INKLIGHT_SERVER_TOKEN="$(python -c "import secrets; print(secrets.token_urlsafe(24))")"
docker compose up -d --build
```

The domain's DNS must point to the machine, and TCP 80 and 443 must be open to it, for Caddy to get a certificate.
Without `INKLIGHT_SITE` the example serves `https://localhost:8443/` with a certificate from Caddy's own local
authority, for a test on one machine.

## Google Colab

Not supported in 0.3.x. Colab shows a server from the notebook inside an iframe through its own proxy domain, and
Inklight answers only for host names it was given and refuses to be framed, so `serve_kernel_port_as_iframe` shows
"Host not allowed". Run Inklight on a machine you can open by IP address instead (above).

## First use and offline

The OCR models (76 MB) are downloaded the first time a PDF or an image is read, and the document structure models
(384 MB) the first time tables are extracted; text files need no model. Each file is checked against a pinned SHA-256
and kept in `~/.cache/inklight` (`INKLIGHT_MODEL_CACHE`), shared by every installation and, on a server, by every
visitor. `inklight models pull --structure` fetches everything ahead of time; after that, `INKLIGHT_OFFLINE=1` makes
sure nothing is fetched.
