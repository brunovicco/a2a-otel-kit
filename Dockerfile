# syntax=docker/dockerfile:1
#
# Build from the committed lock file and keep uv and build tools out of the runtime image.

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Cache dependencies independently from source changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.13-slim

RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

# Replace this framework-neutral placeholder with the project's entrypoint, for example:
#   CMD ["uvicorn", "a2a_otel_kit.entrypoints.http:app", "--host", "0.0.0.0", "--port", "8000"]
#   CMD ["python", "-m", "a2a_otel_kit"]
CMD ["python", "-c", "import a2a_otel_kit; print(a2a_otel_kit.__doc__)"]
