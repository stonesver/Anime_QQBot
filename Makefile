.PHONY: format lint typecheck test-unit check-fast check

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy src

test-unit:
	uv run pytest tests/unit

check-fast: lint typecheck test-unit

check: check-fast
	uv run pytest
	uv run alembic check
	docker compose -f compose.test.yaml config --quiet

