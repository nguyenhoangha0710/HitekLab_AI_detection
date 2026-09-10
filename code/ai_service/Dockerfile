FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-yolo.txt ./
ARG INSTALL_YOLO=false
RUN if [ "$INSTALL_YOLO" = "true" ]; then \
        pip install --no-cache-dir -r requirements-yolo.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY app ./app
COPY config.yaml .
COPY config.docker.yaml .

EXPOSE 8001
