# Makefile — GNOME Handwriting Overlay
# Targets: run, test, lint, type-check, install-deps, clean

PYTHON      ?= python3
CONFIG      ?= config.yaml

.PHONY: run test lint typecheck install-deps install-deps-ocr clean help

## ── Main ──────────────────────────────────────────────────────────────── ##

run:                         ## Launch the overlay application
	$(PYTHON) main.py

run-debug:                   ## Launch with verbose logging
	LOG_LEVELS="input.stylus_handler=DEBUG,core.state_machine=DEBUG" \
	    $(PYTHON) main.py

## ── Quality ───────────────────────────────────────────────────────────── ##

test:                        ## Run the test suite
	$(PYTHON) -m pytest tests/ -v

test-cov:                    ## Run tests with coverage report
	$(PYTHON) -m pytest tests/ --cov=. --cov-report=term-missing --cov-report=html

lint:                        ## Run ruff linter
	$(PYTHON) -m ruff check .

lint-fix:                    ## Run ruff with auto-fix
	$(PYTHON) -m ruff check --fix .

typecheck:                   ## Run mypy static type checks
	$(PYTHON) -m mypy core/ input/ recognition/ utils/ ui/

## ── Installation ──────────────────────────────────────────────────────── ##

install-deps:                ## Install Python dependencies via pip
	pip install pyyaml pytest pytest-cov ruff mypy

install-deps-ocr:            ## Install optional OCR dependencies
	pip install pytesseract Pillow

install-system-deps:         ## Print the apt packages needed
	@echo "Run the following as root / with sudo:"
	@echo ""
	@echo "  apt install python3-gi python3-gi-cairo \\"
	@echo "              gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdk-4.0 \\"
	@echo "              libgtk4-layer-shell-dev \\"
	@echo "              tesseract-ocr tesseract-ocr-deu"

## ── Maintenance ───────────────────────────────────────────────────────── ##

clean:                       ## Remove __pycache__ and coverage artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete
	rm -rf .coverage htmlcov/ .mypy_cache/ .ruff_cache/ .pytest_cache/

help:                        ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	    | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
