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

COPY common ./common
COPY edge_gateway ./edge_gateway
COPY local_ai ./local_ai
COPY modal_ai ./modal_ai
COPY modal_yolo11_service.py .
COPY modal_bbox_service.py .
COPY config.yaml .
COPY config.docker.yaml .

EXPOSE 8001 8002
