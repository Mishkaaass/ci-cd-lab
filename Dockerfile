FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade \
       gzip \
       libpcre2-8-0 \
       libsqlite3-0 \
       perl-base \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install \
    --no-cache-dir \
    -r requirements.txt

COPY app.py .
COPY opsboard ./opsboard
COPY templates ./templates
COPY static ./static

EXPOSE 8000

USER 10001:10001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
