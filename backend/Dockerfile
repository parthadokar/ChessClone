FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (layer cache)
COPY pyproject.toml .
RUN uv pip install --system -e .

COPY . .

EXPOSE 8000
