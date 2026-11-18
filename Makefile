PYTHON ?= python

.PHONY: demo demo-json test lint typecheck validate ci

demo:
	$(PYTHON) demo/run_demo.py

demo-json:
	$(PYTHON) demo/run_demo.py --json

test:
	$(PYTHON) -m pytest -q -p no:cacheprovider

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

validate:
	$(PYTHON) ops/scripts/validate_project_structure.py

ci: test validate lint typecheck demo-json
