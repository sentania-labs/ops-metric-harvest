.PHONY: lint test check build-linux build-windows gui smoke-gui clean

PYTHON ?= python3

lint:
	$(PYTHON) -m ruff check ops_metric_harvest tests

test:
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m pytest -v

check: lint test

gui:
	$(PYTHON) -m ops_metric_harvest.cli gui

smoke-gui:
	xvfb-run -a $(PYTHON) -m ops_metric_harvest.cli gui --screenshot "$${GUI_SCREENSHOT:-/tmp/omh-connection.png}"

build-linux build-windows:
	$(PYTHON) packaging/build.py

clean:
	rm -rf build dist .pytest_cache .ruff_cache *.egg-info
