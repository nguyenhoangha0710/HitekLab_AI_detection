FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY code/zone_service/requirements.txt /tmp/zone-requirements.txt
RUN pip install --no-cache-dir -r /tmp/zone-requirements.txt

COPY code/zone_service ./code/zone_service
COPY code/ai_service/config.docker.yaml ./code/ai_service/config.docker.yaml

EXPOSE 8010

CMD ["uvicorn", "backend.app.main:app", "--app-dir", "code/zone_service", "--host", "0.0.0.0", "--port", "8010"]
