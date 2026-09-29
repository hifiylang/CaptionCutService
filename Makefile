.PHONY: install install-dev run format lint check docker-config

install:
	python -m pip install -e .

install-dev:
	python -m pip install -e ".[dev]"

run:
	PYTHONPATH=src python -m caption_cut_service.main

format:
	python -m ruff check --fix src tests
	python -m ruff format src tests

lint:
	python -m ruff format --check src tests
	python -m ruff check src tests

check: lint
	python -m compileall -q src
	PYTHONPATH=src python -m unittest discover -s tests -v
	PYTHONPATH=src python -c "from caption_cut_service.main import app; assert app.openapi()['info']['title']"

docker-config:
	docker compose config --quiet
