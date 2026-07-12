# syntax=docker/dockerfile:1
# mcp-stepik: FastMCP HTTP + Rust TaskStore/StateStore (maturin)

FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

# rustup respects rust-toolchain.toml (1.95.0)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain none
ENV PATH="/root/.cargo/bin:${PATH}" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_EDITABLE=1

WORKDIR /app

COPY rust-toolchain.toml ./
RUN rustup show

COPY pyproject.toml uv.lock Cargo.toml Cargo.lock ./
COPY python ./python
COPY src ./src
COPY packages/mcp-stepik-state ./packages/mcp-stepik-state
COPY README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    MCP_STEPIK_HOST=0.0.0.0 \
    MCP_STEPIK_PORT=8000 \
    MCP_STEPIK_STATE=/data/state \
    MCP_STEPIK_PROJECTS=/data/projects \
    MCP_STEPIK_WORKSPACES=/data/workspaces \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data/state /data/projects /data/workspaces \
    && chown -R appuser:appuser /data

USER appuser
EXPOSE 8000
VOLUME ["/data"]

CMD ["mcp-stepik"]
