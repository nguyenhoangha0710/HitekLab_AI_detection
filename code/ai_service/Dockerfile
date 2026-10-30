# Multi-stage Dockerfile cho thu muc code/ai_service.
#   target edge-gateway : doc RTSP, live viewer, gui frame sang AI Service (nhe, khong co torch)
#   target ai-service   : YOLOv11 + ByteTrack + Rule Engine (co torch/ultralytics)
#
#   docker compose build edge-gateway ai-service

# ---------------------------------------------------------------- base
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY common ./common

# --------------------------------------------------------- edge-gateway
FROM base AS edge-gateway

COPY edge_gateway ./edge_gateway
COPY config.yaml config.docker.yaml ./

EXPOSE 8002
CMD ["python", "-m", "edge_gateway.main", "--config", "config.docker.yaml"]

# ----------------------------------------------------------- ai-service
FROM base AS ai-service

# Mac dinh cai torch ban CPU (image nho hon ~2GB). Ban GPU: xem docker-compose.gpu.yml
# (TORCH_INDEX_URL=https://download.pytorch.org/whl/cu121).
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install torch torchvision --index-url ${TORCH_INDEX_URL} \
    && pip install ultralytics "lap>=0.5.12"

COPY local_ai ./local_ai
COPY rule_engine ./rule_engine
COPY local_bbox_service.py ./

# Model YOLO duoc mount tu code/ai_service/models. Neu chua co file, Ultralytics
# tu tai yolo11n.pt vao day o lan chay dau tien (can Internet).
ENV LOCAL_YOLO_MODEL=models/yolo11n.pt \
    YOLO_CONFIG_DIR=/tmp/Ultralytics
RUN mkdir -p models

EXPOSE 8003
CMD ["uvicorn", "local_bbox_service:app", "--host", "0.0.0.0", "--port", "8003"]
