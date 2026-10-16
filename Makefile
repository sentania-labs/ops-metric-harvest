.PHONY: lint test check build-linux clean

lint:
	ruff check ops_metric_harvest tests

test:
	pytest -v

check: lint test

build-linux:
	python3 -m PyInstaller --clean --noconfirm packaging/ops-metric-harvest.spec

clean:
	rm -rf build dist .pytest_cache .ruff_cache *.egg-info
