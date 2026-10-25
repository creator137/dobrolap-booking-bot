FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY assets ./assets

RUN pip install --no-cache-dir ".[sheets]"

ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/app/data/app.db
ENV CONFIG_DIR=/app/config
ENV ASSETS_DIR=/app/assets

VOLUME ["/app/data"]

CMD ["python", "-m", "dobrolap_bot"]
