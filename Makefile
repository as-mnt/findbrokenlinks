.PHONY: help venv install install-dev test test-unit test-integration lint typecheck clean \
        run run-page run-internal run-all run-html run-json run-jsonl run-multi smoke

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

# ---------- run examples ----------
# All run targets accept URL=... and RATE=... overrides.

run: install ## Default crawl (internal+external, tsv to stdout). URL=...
	$(FBL) $(URL) --rate-limit $(RATE)

run-page: install ## Single page mode (no recursion). URL=...
	$(FBL) $(URL) --mode page --rate-limit $(RATE) --format tsv

run-internal: install ## Crawl internal pages only, validate links inside the domain. URL=...
	$(FBL) $(URL) --mode internal --rate-limit $(RATE) --format tsv

run-all: install ## Recurse internal + validate external links. URL=...
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) --format tsv

run-html: install ## HTML report → $(OUT_DIR)/report.html. URL=...
	mkdir -p $(OUT_DIR)
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) \
	    --format html -o $(OUT_DIR)/report.html

run-json: install ## JSON report → $(OUT_DIR)/report.json (written at the end). URL=...
	mkdir -p $(OUT_DIR)
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) \
	    --format json -o $(OUT_DIR)/report.json

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
	    --format jsonl -o $(OUT_DIR)/report.jsonl

run-multi: install ## Emit csv/json/html/markdown into $(OUT_DIR)/. URL=...
	$(FBL) $(URL) --mode internal+external --rate-limit $(RATE) \
	    --format csv,json,html,markdown --output-dir $(OUT_DIR)

smoke: install ## Quick local smoke run against example.com in page mode
	$(FBL) https://example.com --mode page --rate-limit 0 --format tsv

# ---------- housekeeping ----------

clean: ## Remove venv, caches, and generated reports
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache $(OUT_DIR)
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
