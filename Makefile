PYTHON ?= python

.PHONY: demo demo-json test validate ci

demo:
	$(PYTHON) demo/run_demo.py

demo-json:
	$(PYTHON) demo/run_demo.py --json

test:
	$(PYTHON) -m pytest -q --basetemp=.pytest-tmp

validate:
	$(PYTHON) ops/scripts/validate_project_structure.py

ci: test validate demo-json
