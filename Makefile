.PHONY: help venv install install-dev test test-unit test-integration lint typecheck check clean \
        run run-page run-internal run-all run-html run-json run-jsonl run-grouped run-multi smoke

PY      ?= python3
VENV    ?= .venv
BIN      = $(VENV)/bin
PIP      = $(BIN)/pip
PYTHON   = $(BIN)/python
PYTEST   = $(BIN)/pytest
FBL      = $(BIN)/findbrokenlinks

# Default URL for `make run*` targets — override on the command line:
#   make run URL=https://example.com
URL     ?= https://example.com
RATE    ?= 50
OUT_DIR ?= reports
# Extra flags forwarded verbatim to every run target, e.g.
#   make run-json URL=https://site FLAGS=--insecure
FLAGS   ?=

help: ## Show available targets
	@awk 'BEGIN{FS=":.*##"; printf "Usage: make <target>\n\nTargets:\n"} \
	      /^[a-zA-Z_-]+:.*##/ {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------- setup ----------

$(VENV)/pyvenv.cfg:
	$(PY) -m venv $(VENV)
	$(PIP) install --upgrade pip

venv: $(VENV)/pyvenv.cfg ## Create virtualenv at .venv

install: venv ## Install runtime dependencies
	$(PIP) install -e .

install-dev: venv ## Install package + dev dependencies (tests, lint, typecheck)
	$(PIP) install -e ".[dev]"

# ---------- quality ----------

test: install-dev ## Run the full test suite
	$(PYTEST)

test-unit: install-dev ## Run only unit tests (skip integration)
	$(PYTEST) --ignore=tests/test_crawler_integration.py

test-integration: install-dev ## Run only the live-server integration test
	$(PYTEST) tests/test_crawler_integration.py

lint: install-dev ## Lint with ruff
	$(BIN)/ruff check src tests

typecheck: install-dev ## Static typecheck with mypy
	$(BIN)/mypy src/findbrokenlinks

# Mirrors the GitHub Actions CI pipeline (.github/workflows/ci.yml): same three
# gates that block merges remotely run locally in the same order. Run this
# before pushing to catch what CI would catch — cheaper checks first so a
# trivial lint slip fails fast without waiting for the test suite.
check: lint typecheck test ## Run lint + typecheck + tests — the full CI gate locally

# ---------- run examples ----------
# All run targets accept URL=... and RATE=... overrides.

run: install ## Default crawl (internal+external, tsv to stdout). URL=...
	$(FBL) $(URL) --rate-limit $(RATE) $(FLAGS)

run-page: install ## Single page mode (no recursion). URL=...
	$(FBL) $(URL) --mode page --rate-limit $(RATE) --format tsv $(FLAGS)

run-internal: install ## Crawl internal pages only, validate links inside the domain. URL=...
	$(FBL) $(URL) --mode internal --rate-limit $(RATE) --format tsv $(FLAGS)

run-all: install ## Recurse internal + validate external links. URL=...
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) --format tsv $(FLAGS)

run-html: install ## HTML report → $(OUT_DIR)/report.html. URL=...
	mkdir -p $(OUT_DIR)
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) \
	    --format html -o $(OUT_DIR)/report.html $(FLAGS)

run-json: install ## JSON report → $(OUT_DIR)/report.json (written at the end). URL=...
	mkdir -p $(OUT_DIR)
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) \
	    --format json -o $(OUT_DIR)/report.json $(FLAGS)

# JSONL = JSON Lines: one finding per line as a self-contained JSON object.
# Unlike `run-json` (which buffers everything and writes a single document at
# the end of the crawl), JSONL streams — each finding is appended to the file
# the moment it is discovered. Use this for long crawls when you want to
# `tail -f $(OUT_DIR)/report.jsonl` and see findings appear in real time, or
# when you want partial output preserved if the crawl is interrupted.
# Easy to post-process: `jq` reads it line-by-line, no array wrapper needed.
run-jsonl: install ## Streaming JSONL report → $(OUT_DIR)/report.jsonl (tail-able live). URL=...
	mkdir -p $(OUT_DIR)
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) \
	    --format jsonl -o $(OUT_DIR)/report.jsonl $(FLAGS)

# Grouped JSON: aggregates findings by `final_url` so a broken link that lives
# in a site-wide template (header/footer/menu) collapses from N findings (one
# per page that includes the template) to a single record with occurrences
# count and source-page samples. On real-world crawls this is a 30–100×
# size reduction and makes the report navigable. Same data shape as JSON,
# different aggregation — pick this for first-pass triage of large sites,
# use `run-json`/`run-jsonl` when you need every (link, source_page) pair.
run-grouped: install ## Findings grouped by final_url → $(OUT_DIR)/report.grouped.json. URL=...
	mkdir -p $(OUT_DIR)
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) \
	    --format grouped-json -o $(OUT_DIR)/report.grouped.json $(FLAGS)

run-multi: install ## Emit csv/json/html/markdown into $(OUT_DIR)/. URL=...
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) \
	    --format csv,json,html,markdown --output-dir $(OUT_DIR) $(FLAGS)

smoke: install ## Quick local smoke run against example.com in page mode
	$(FBL) https://example.com --mode page --rate-limit 0 --format tsv

# ---------- housekeeping ----------

clean: ## Remove venv, caches, and generated reports
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache $(OUT_DIR)
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
