.PHONY: install dev lint format type test check

install:
	uv sync

dev:
	uv run uvicorn polis.main:app --reload --host 0.0.0.0 --port 8000

lint:
	uv run ruff check .

format:
	uv run ruff format .

type:
	uv run mypy src

test:
	uv run pytest

check: lint type test
