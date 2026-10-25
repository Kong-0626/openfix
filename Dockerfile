FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENFIX_DB_PATH=/app/data/runtime/openfix.db

WORKDIR /app
COPY app.py ./
COPY openfix ./openfix
COPY web ./web
COPY data ./data

RUN useradd --create-home --uid 10001 openfix \
    && mkdir -p /app/data/runtime \
    && chown -R openfix:openfix /app

USER openfix
EXPOSE 8765
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "8765"]
