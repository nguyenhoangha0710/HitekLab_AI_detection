import modal

from .settings import APP_NAME, FRAME_QUEUE_NAME, RESULT_QUEUE_NAME, STATE_DICT_NAME


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("fastapi[standard]", "opencv-python-headless", "numpy", "ultralytics")
    .env({"YOLO_CONFIG_DIR": "/tmp/Ultralytics"})
    .add_local_python_source("modal_ai")
)

app = modal.App(APP_NAME)
frame_queue = modal.Queue.from_name(FRAME_QUEUE_NAME, create_if_missing=True)
result_queue = modal.Queue.from_name(RESULT_QUEUE_NAME, create_if_missing=True)
state_store = modal.Dict.from_name(STATE_DICT_NAME, create_if_missing=True)
