# syntax=docker/dockerfile:1
FROM python:3.14-slim

# Upgrade zlib1g to the Debian security-fixed package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade zlib1g


WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::Retries=0 update \
    && apt-get -o Acquire::Retries=0 install -y --no-install-recommends --only-upgrade \
       apt \
       libapt-pkg7.0 \
       gzip \
       libpcre2-8-0 \
       libsqlite3-0 \
       perl-base \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' apt)" ge 3.0.4 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libapt-pkg7.0)" ge 3.0.4

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check \
    && python -m pip uninstall --yes pip

COPY app.py .
COPY opsboard ./opsboard
COPY templates ./templates
COPY static ./static

EXPOSE 8000

USER 10001:10001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header", "--no-proxy-headers"]
