#!/usr/bin/env bash
# Chay AI Service tren server GPU (vd khoa-gpu). Dung cung SSH tunnel cua VS Code:
#   ~/.ssh/config (tren may Windows), khoi Host khoa-gpu:
#       LocalForward 8003 localhost:18003
#       RemoteForward 18010 localhost:8010
# Tren may Windows: .\scripts\use-ai.ps1 remote
#
# Cach dung (tren server, nen chay trong tmux):
#   tmux new -s hitek-ai
#   bash scripts/run_ai_remote.sh
# Doi tham so bang bien moi truong, vd:  CUDA_VISIBLE_DEVICES=1 AI_PORT=18103 bash scripts/run_ai_remote.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR/code/ai_service"

CONDA_ENV="${CONDA_ENV:-hitek}"
if [[ "${CONDA_DEFAULT_ENV:-}" != "$CONDA_ENV" ]] && command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  eval "$(conda shell.bash hook)"
  conda activate "$CONDA_ENV" || echo "Khong activate duoc conda env '$CONDA_ENV' - dung python hien tai"
fi

export AI_PORT="${AI_PORT:-18003}"
export ZONE_SERVICE_URL="${ZONE_SERVICE_URL:-http://localhost:18010}"
export SERVICE_API_KEY="${SERVICE_API_KEY:-hitek-dev-service-key}"   # phai trung voi .env tren may Windows
export LOCAL_YOLO_DEVICE="${LOCAL_YOLO_DEVICE:-0}"
export AI_HOST_LABEL="${AI_HOST_LABEL:-khoa-gpu}"

# Tu chon GPU dang dung it bo nho nhat neu chua chi dinh (server dung chung).
if [[ -z "${CUDA_VISIBLE_DEVICES:-}" ]] && command -v nvidia-smi >/dev/null 2>&1; then
  CUDA_VISIBLE_DEVICES="$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
    | sort -t, -k2 -n | head -n1 | cut -d, -f1 | tr -d ' ')"
  export CUDA_VISIBLE_DEVICES
fi

echo "== HITEK AI Service =="
echo "  repo            : $REPO_DIR"
echo "  python          : $(command -v python)"
echo "  GPU duoc cap    : CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<tat ca>}"
echo "  lang nghe       : 127.0.0.1:${AI_PORT}  (may Windows goi qua localhost:8003)"
echo "  Zone Service    : ${ZONE_SERVICE_URL}  (qua RemoteForward ve may Windows)"
python - <<'PY'
import torch
ok = torch.cuda.is_available()
print("  CUDA            :", ok, "-", torch.cuda.get_device_name(0) if ok else "KHONG CO GPU -> AI se chay CPU")
PY
if ! curl -fsS -m 3 "${ZONE_SERVICE_URL}/health" >/dev/null 2>&1; then
  echo "  Canh bao: chua goi duoc ${ZONE_SERVICE_URL}/health. Kiem tra RemoteForward + Docker tren may Windows."
  echo "            AI van chay va tra bbox, nhung chua tai duoc zone/rule va chua gui duoc su kien."
fi

exec uvicorn local_bbox_service:app --host 127.0.0.1 --port "$AI_PORT"
