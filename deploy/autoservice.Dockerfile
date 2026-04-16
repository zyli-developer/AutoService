FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY socialware/ socialware/
COPY autoservice/ autoservice/
COPY channels/ channels/
COPY plugins/ plugins/
COPY templates/ templates/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "channels.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
