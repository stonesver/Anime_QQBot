# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.28
COPY pyproject.toml uv.lock README.md NOTICE ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 animebot && useradd --uid 10001 --gid animebot --create-home animebot
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY scripts/container-entrypoint.sh /usr/local/bin/anime-qqbot
RUN chmod 0755 /usr/local/bin/anime-qqbot && chown -R animebot:animebot /app
USER animebot
EXPOSE 8080 8081
ENTRYPOINT ["anime-qqbot"]
CMD ["bot"]
