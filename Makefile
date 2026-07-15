UV ?= uv
UV_CACHE_DIR ?= .uv-cache
TEST_DATABASE_URL ?= postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test
RUN = UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run

.PHONY: format lint typecheck test-unit test-integration check-fast check postgres-up postgres-down

format:
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

lint:
	$(RUN) ruff format --check .
	$(RUN) ruff check .

typecheck:
	$(RUN) mypy src

test-unit:
	$(RUN) pytest tests/unit

postgres-up:
	docker compose -f compose.test.yaml up -d --wait

postgres-down:
	docker compose -f compose.test.yaml down -v

test-integration: postgres-up
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(RUN) pytest tests/integration
	DATABASE_URL=$(TEST_DATABASE_URL) $(RUN) alembic check

check-fast: lint typecheck test-unit

check: check-fast test-integration
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(RUN) pytest
	docker compose -f compose.test.yaml config --quiet
