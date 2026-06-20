.PHONY: install dev lint format type test check migrate makemigration downgrade worker temporal

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

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m polis.seed

makemigration:
	uv run alembic revision --autogenerate -m "$(m)"

downgrade:
	uv run alembic downgrade -1

worker:
	uv run python -m polis.modules.planner.worker

temporal:
	cd ../infra && docker compose --env-file .env up -d temporal temporal-ui
