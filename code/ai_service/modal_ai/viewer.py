VIEWER_HTML = """
<!doctype html>
<html>
  <head>
    <title>Modal YOLOv11 Multi Camera Viewer</title>
    <style>
      body { margin: 0; font-family: Arial, sans-serif; background: #101010; color: #eee; }
      header { padding: 14px 16px 8px; }
      h1 { margin: 0 0 6px; font-size: 20px; }
      p { margin: 0; color: #7dd3fc; font-size: 13px; }
      main { padding: 14px 16px 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 14px; }
      iframe { width: 100%; aspect-ratio: 16 / 10; border: 1px solid #333; background: #000; border-radius: 6px; }
    </style>
  </head>
  <body>
    <header>
      <h1>Modal YOLOv11 Multi Camera Viewer</h1>
      <p id="status">Loading camera iframes...</p>
    </header>
    <main id="grid"></main>
    <script>
      const grid = document.getElementById("grid");
      const status = document.getElementById("status");

      async function loadCameras() {
        const response = await fetch("/viewer/cameras", { cache: "no-store" });
        if (!response.ok) throw new Error(`Cannot load cameras: ${response.status}`);
        return await response.json();
      }

      async function start() {
        try {
          const body = await loadCameras();
          grid.innerHTML = "";
          body.cameras.forEach((camera) => {
            const frame = document.createElement("iframe");
            frame.loading = "eager";
            frame.src = `/viewer/camera/${encodeURIComponent(camera.camera_id)}?shard_id=${camera.shard_id}`;
            frame.title = camera.camera_id;
            grid.append(frame);
          });
          status.textContent = `Running ${body.cameras.length} isolated camera viewers.`;
        } catch (error) {
          status.textContent = error.message;
        }
      }

      start();
    </script>
  </body>
</html>
"""


CAMERA_VIEWER_HTML = """
<!doctype html>
<html>
  <head>
    <title>Modal YOLOv11 Camera Viewer</title>
    <style>
      html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; }
      body { font-family: Arial, sans-serif; background: #050505; color: #eee; }
      .wrap { height: 100%; display: grid; grid-template-rows: auto 1fr; }
      header { padding: 8px 10px; background: #111; border-bottom: 1px solid #2a2a2a; }
      h2 { margin: 0 0 4px; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      p { margin: 0; color: #b8b8b8; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      img { width: 100%; height: 100%; object-fit: contain; background: #000; display: block; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <header>
        <h2 id="title">Camera</h2>
        <p id="meta">Connecting result WebSocket...</p>
      </header>
      <img id="image" alt="processed camera frame" />
    </div>
    <script>
      const cameraId = window.location.pathname.split("/").pop();
      const params = new URLSearchParams(window.location.search);
      const shardId = Number(params.get("shard_id") || 0);
      const title = document.getElementById("title");
      const meta = document.getElementById("meta");
      const image = document.getElementById("image");

      title.textContent = cameraId;

      function render(frame, timestamp) {
        if (frame.camera_id !== cameraId) return;
        const worker = frame.worker_id ?? "n/a";
        meta.textContent = `seq ${frame.sequence_number} | shard ${frame.shard_id ?? shardId} | ${worker} | detections ${frame.detection_count} | ${timestamp}`;
        if (frame.image_b64) {
          image.src = "data:image/jpeg;base64," + frame.image_b64;
        }
      }

      function connect() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const socket = new WebSocket(`${protocol}//${window.location.host}/ws/results/shards/${shardId}`);
        socket.onopen = () => {
          meta.textContent = `Connected shard ${shardId}. Waiting for ${cameraId}...`;
        };
        socket.onmessage = (event) => {
          const message = JSON.parse(event.data);
          if (message.type === "frame") {
            render(message.frame, message.timestamp);
          }
        };
        socket.onclose = () => {
          meta.textContent = `Disconnected shard ${shardId}. Reconnecting...`;
          setTimeout(connect, 1000);
        };
        socket.onerror = () => {
          meta.textContent = `WebSocket error on shard ${shardId}.`;
          socket.close();
        };
      }

      connect();
    </script>
  </body>
</html>
"""
