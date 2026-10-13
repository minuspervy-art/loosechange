# loosechange Telegram bot (long-polling: no webhook, no open ports).
#   docker build -t loosechange .
#   docker run -d --restart unless-stopped --env-file .env --name loosechange loosechange
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    LOOSECHANGE_DATA=/app/data/models.json \
    LOOSECHANGE_SELF_COLLECT_HOURS=3

RUN pip install --no-cache-dir uv==0.11.32 \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --extra bot
COPY data ./data
RUN chown -R app:app /app/data

USER app
# Data source: the bundled snapshot, refreshed in-process every
# LOOSECHANGE_SELF_COLLECT_HOURS; or set LOOSECHANGE_DATA_URL to the raw GitHub
# URL of data/models.json kept fresh by .github/workflows/collect.yml.
CMD ["loosechange-bot"]
