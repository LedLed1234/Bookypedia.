FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/readmore.db

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /data && chown -R 1000:1000 /app /data

FROM base AS development
RUN pip install --no-cache-dir pytest==8.4.2

USER 1000:1000
EXPOSE 5000

CMD ["flask", "--app", "run.py", "run", "--debug", "--host=0.0.0.0", "--port=5000"]

FROM base AS production
USER 1000:1000
EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--error-logfile", "-", "run:app"]

