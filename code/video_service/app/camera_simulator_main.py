import argparse
import logging
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import List

from .config import load_simulator_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish local video files to RTSP URLs with FFmpeg.")
    parser.add_argument("--config", default="config.yaml", help="Path to Video Service YAML config.")
    return parser.parse_args()


def _build_ffmpeg_command(ffmpeg_path: str, video_path: str, rtsp_url: str) -> List[str]:
    return [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-re",
        "-stream_loop",
        "-1",
        "-i",
        video_path,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        rtsp_url,
    ]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    config = load_simulator_config(args.config)

    if shutil.which(config.ffmpeg_path) is None:
        print("FFmpeg was not found in PATH. Install FFmpeg before running Camera Simulator.", file=sys.stderr)
        sys.exit(2)

    processes: List[subprocess.Popen] = []

    def stop_all(signum=None, frame=None) -> None:
        logging.info("Stopping camera simulator")
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            if process.poll() is None:
                process.wait(timeout=5)

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    try:
        for camera in config.cameras:
            if not camera.simulator_video_path:
                logging.warning("Camera %s has no simulator_video_path; skipping", camera.camera_id)
                continue
            video_path = Path(camera.simulator_video_path)
            if not video_path.exists():
                raise FileNotFoundError("Video file not found: {}".format(video_path))
            command = _build_ffmpeg_command(config.ffmpeg_path, str(video_path), camera.source_url)
            logging.info("Publishing %s to %s", video_path, camera.source_url)
            processes.append(subprocess.Popen(command))

        if not processes:
            raise RuntimeError("No camera simulator process was started")

        for process in processes:
            process.wait()
    finally:
        stop_all()


if __name__ == "__main__":
    main()
