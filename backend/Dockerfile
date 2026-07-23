# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.2 AS uv

FROM python:3.13.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src

ARG INSTALL_EXTRACTION=false

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /app/artifacts /app/run \
    && chown -R app:app /app

USER app

RUN if [ "$INSTALL_EXTRACTION" = "true" ]; then \
        uv sync --frozen --no-dev --group extraction --no-editable; \
    else \
        uv sync --frozen --no-dev --no-editable; \
    fi

EXPOSE 8000
CMD ["sh", "-c", "fastapi run src/tnpsc_book_rag/main.py --host 0.0.0.0 --port ${PORT:-8000}"]
