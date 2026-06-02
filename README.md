# findbrokenlinks

[![CI](https://github.com/as-mnt/findbrokenlinks/actions/workflows/ci.yml/badge.svg)](https://github.com/as-mnt/findbrokenlinks/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Async crawler that finds links on a website whose behavior in a browser would
**not match user expectations**: 404s, network failures, redirects to weird
places, "soft 404" pages where a CMS returns 200 but says "not found".

Built around pluggable **checks** and **reporters** — adding a new control or
output format means dropping a file with an `@register` decorator. No core
edits needed.

## Features

- **Crawl modes**: `page` (single page), `internal` (same domain), or
  `internal+external` (recurse internal, validate external) — `--mode`.
- **Seven built-in checks** — flag HTTP errors, network failures, redirect
  chains, redirects to the home page, two soft-404 detectors (regex patterns +
  baseline probing), and an anti-bot block detector so WAF challenges from
  Cloudflare / DataDome / PerimeterX / Imperva / Akamai / DDoS-Guard
  and login walls (401) don't masquerade as broken links.
- **Polite-but-well-formed HTTP**: keeps an honest `User-Agent`, but pairs
  it with standard `Accept` and `Accept-Language` headers so WAFs don't
  treat us as malformed traffic.
- **Doesn't parse JS as HTML**: bodies are only HTML/plaintext; JS, CSS,
  JSON aren't read, and HTMLExtractor double-checks `Content-Type` before
  invoking bs4 — so JavaScript string literals can't become fake findings.
- **Nine output formats**: `csv`, `tsv`, `json`, `jsonl`, `html`, `markdown`,
  `junit` (XML), `sarif`, `grouped-json`. Emit multiple at once with `--format a,b,c`.
- **`grouped-json` reporter** collapses findings by `final_url` — one record
  per distinct broken target with the source-page list preserved as a count
  plus a small sample. On a real crawl of a 7800-page site, a single broken
  footer link generated 7800 findings; grouped-json compresses that to one
  record (97% reduction in our test case).
- **Incremental report writing**: when a single streamable format is selected
  (`csv`, `tsv`, `jsonl`), each finding is appended to the output as soon as it
  is discovered — you can `tail -f` the report while the crawl runs.
- **Polite by default**: respects `robots.txt`, rate-limited (token bucket),
  bounded concurrency, configurable timeouts and redirect caps.
- **Bandwidth-efficient**: streams responses — binary content (PDFs, archives,
  images) is never downloaded, only its status code is checked. Text bodies
  are capped (default 1 MB) so a runaway HTML page can't exhaust memory.
- **HTML coverage** beyond `<a href>`: also checks `<img src>`,
  `<script src>`, `<link href>`.
- **Extensible**: new check = one file + `@register`. Same for report formats.
- **CI-friendly**: exits non-zero if any `error`-severity finding; JUnit and
  SARIF outputs slot into GitHub Code Scanning / GitLab / Jenkins.

## Installation

Requires Python **3.11+**.

```bash
git clone https://github.com/as-mnt/findbrokenlinks
cd findbrokenlinks
make install            # runtime only
# or
make install-dev        # + pytest, ruff, mypy, starlette (for integration tests)
```

This creates a `.venv/` and installs the package in editable mode. After
`make install` you have `.venv/bin/findbrokenlinks` available.

## Quick start

```bash
# Crawl a site, internal pages + validate external links, TSV to stdout
.venv/bin/findbrokenlinks https://example.com

# Single page mode, HTML report
.venv/bin/findbrokenlinks https://example.com --mode page \
    --format html -o report.html

# Streaming JSONL — findings appear in the file as soon as they are discovered
.venv/bin/findbrokenlinks https://example.com --format jsonl -o report.jsonl &
tail -f report.jsonl | jq .

# Emit several formats at once
.venv/bin/findbrokenlinks https://example.com \
    --format csv,json,html,markdown --output-dir reports/

# Run as a Python module
python -m findbrokenlinks https://example.com --mode internal
```

Or via Makefile shortcuts (override `URL=…` on the command line):

```bash
make run URL=https://example.com
make run-page URL=https://example.com
make run-internal URL=https://example.com
make run-html URL=https://example.com OUT_DIR=reports
make run-jsonl URL=https://example.com OUT_DIR=reports     # streaming JSONL
make run-multi URL=https://example.com OUT_DIR=reports
```

## CLI reference

```
findbrokenlinks <URL> [options]

Scope:
  --mode {page,internal,internal+external}   default: internal+external
  --depth N                                  default: 0 (unlimited)
  --max-pages N                              default: 10000 (0 = unlimited);
                                             safety cap against unbounded URL spaces
                                             (session IDs, calendars, search facets)
  --use-sitemap                              seed from /sitemap.xml

Network:
  --rate-limit RPS               default: 5
  --concurrency N                default: 10
  --timeout SECONDS              default: 15
  --max-redirects N              default: 10
  --max-body-bytes N             default: 1048576 (1 MB) — cap on text bodies;
                                 non-text responses are never downloaded
  --user-agent UA
  --ignore-robots

Checks:
  --enable-checks code1,code2
  --disable-checks code1,code2
  --redirect-chain-threshold N   default: 3
  --patterns PATH                user soft-404 patterns YAML
  --no-soft404-probe

Output:
  --format fmt[,fmt...]          csv|tsv|json|jsonl|html|markdown|junit|sarif|grouped-json
                                 (default: tsv); streaming formats: csv, tsv, jsonl
  --output PATH, -o PATH         default: stdout (single format only). Supports
                                 placeholders {host}, {date}, {time}, {ts}, {format}, {ext}.
  --output-dir DIR               directory for multi-format output. Defaults to
                                 reports/{host}_{date}_{time}/ when omitted. Files
                                 inside the dir are named {format}.{ext}.

Misc:
  -v / --verbose
  --log-file PATH
```

## Built-in checks

| Code | Severity | Triggers when |
|---|---|---|
| `HTTP_ERROR` | error | response status ≥ 400 |
| `NETWORK_ERROR` | error | DNS / TCP / TLS / timeout failure |
| `REDIRECT_TO_HOME` | warning | redirect terminates at `/` (common soft-404 pattern) |
| `REDIRECT_CHAIN` | warning | redirect chain length >= `--redirect-chain-threshold` |
| `SOFT_404_PATTERN` | warning | 200 OK but page matches a "not found" regex |
| `SOFT_404_PROBE` | warning | 200 OK but body matches the host's known 404 baseline |
| `ANTIBOT_BLOCKED` | warning | 4xx/5xx response matches a known WAF / anti-bot signature (DataDome, PerimeterX, Cloudflare interstitial, Imperva, Akamai, generic "not a bot" / captcha text). Fires alongside `HTTP_ERROR` — disable one or the other to suit your triage. |

The probe-based detector requests a random nonexistent URL per host at startup
and remembers the response (status, normalized text, hash). Any 2xx response
whose body matches the baseline is flagged.

## Output

Every reporter produces the same fields per finding:

- `source_page` — page where the link was found
- `link_url` — the link's target URL
- `final_url` — where the request actually ended up after redirects
- `anchor` — link text or alt attribute
- `tag` — `a` / `img` / `script` / `link` / `seed`
- `status` — HTTP status (empty on network error)
- `redirect_chain` — list of intermediate URLs
- `issue_codes` — which checks fired
- `severity` — `error` / `warning` / `info`
- `details` — human-readable explanation

HTML and Markdown reports additionally **group findings by source page**.

## Extending: add a new check

No core edits required. Create `src/findbrokenlinks/checks/my_check.py`:

```python
from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


@register
class SlowResponseCheck(Check):
    code = "SLOW_RESPONSE"
    severity = "warning"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if fetch.elapsed_ms > 5_000:
            return Issue(self.code, self.severity, f"slow: {fetch.elapsed_ms:.0f}ms",
                         {"ms": fetch.elapsed_ms})
        return None
```

That's it. The package auto-discovers every submodule under `checks/` on
import, so dropping the file is enough — no `__init__.py` edits required.
Your check is now available everywhere, and can be toggled via
`--enable-checks SLOW_RESPONSE` / `--disable-checks SLOW_RESPONSE`.

## Extending: add a new output format

Same pattern. Create `src/findbrokenlinks/reporters/my_reporter.py`:

```python
from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register


@register
class MyReporter(Reporter):
    name = "myfmt"
    file_ext = "myx"

    def render(self, findings: list[Finding]) -> str:
        ...
```

Drop the file under `reporters/` — same auto-discovery applies — and you
can now pass `--format myfmt`.

## Extending: custom soft-404 patterns

Built-in patterns live in `src/findbrokenlinks/patterns/builtin.yaml`. Add your
own without forking — pass `--patterns my_patterns.yaml`:

```yaml
- name: my_cms_404
  target: title           # title | h1 | body | raw
  regex: '(?i)not here'
```

`target` picks the search surface:

- `title` / `h1` — text of those elements
- `body` — full page text after BeautifulSoup `get_text()` — markup stripped
- `raw` — the unaltered HTML body, including tags, attributes, and server
  signatures that text extraction would erase

User patterns are merged with the built-in set (Composite).

## Architecture

```
seed URL ──► Crawler (asyncio.Queue + N workers)
                │
                ├─► Fetcher  ──► httpx.AsyncClient (rate-limited, robots-aware)
                ├─► HTMLExtractor (bs4 + lxml)
                ├─► Checks  (Strategy + Registry, per-finding evaluation)
                └─► Reporter (Strategy + Registry, multiple formats)
```

Design patterns used:

- **Strategy + Registry** — `Check` and `Reporter` ABCs with `@register`-driven
  plug-in collections
- **Producer–Consumer / Worker Pool** — `asyncio.Queue` + N workers
- **Composite** — built-in + user soft-404 patterns merged
- **Factory** — `get_reporter(name)` resolves a format string
- **Pipeline** — Fetcher → Extractor → Checks → Reporter
- **Observer** — `on_finding` callback drives incremental report writing for
  streaming formats (csv, tsv, jsonl)

See `docs/context.md` for the up-to-date design and rationale. `docs/plan.md` is
the day-0 approved plan, kept as a baseline against which to read the change log.

## Development

```bash
make install-dev          # set up dev environment
make check                # ← run before pushing: lint + typecheck + tests
                          #   (mirrors the GitHub Actions pipeline)
make test                 # run all 106 tests (~7s)
make test-unit            # unit tests only (skip live-server integration)
make test-integration     # only the live-server integration test
make lint                 # ruff
make typecheck            # mypy
make clean                # nuke venv, caches, generated reports
```

Tests run against a local Starlette server with known-broken routes — no
network access required for CI.

## CI integration

The CLI returns exit code `1` whenever an `error`-severity finding is present,
so a basic GitHub Actions step is enough:

```yaml
- run: pip install -e .
- run: findbrokenlinks https://your-site.example --mode internal+external \
       --format junit -o link-check.xml
- uses: mikepenz/action-junit-report@v4
  if: always()
  with:
    report_paths: link-check.xml
```

For GitHub Code Scanning, swap `--format junit` for `--format sarif` and
upload via `github/codeql-action/upload-sarif`.

## Documentation

- [`docs/task.md`](docs/task.md) — original problem statement and decisions
- [`docs/plan.md`](docs/plan.md) — the implementation plan **as approved on day 0**
  (historical snapshot — see `docs/context.md` for what actually ships)
- [`docs/context.md`](docs/context.md) — implementation snapshot, file layout,
  how to extend each subsystem

## License

MIT — see [LICENSE](LICENSE).
