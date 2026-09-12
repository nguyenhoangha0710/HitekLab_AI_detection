VIEWER_HTML = """
<!doctype html>
<html>
  <head>
    <title>Modal YOLOv11 Result Viewer</title>
    <style>
      body { margin: 0; font-family: Arial, sans-serif; background: #111; color: #eee; }
      h1 { margin: 16px; font-size: 20px; }
      main { padding: 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }
      h2 { margin: 0 0 6px; font-size: 14px; }
      p { margin: 0 0 8px; color: #bbb; font-size: 12px; }
      img { width: 100%; aspect-ratio: 16 / 9; object-fit: contain; background: #000; border: 1px solid #333; }
    </style>
  </head>
  <body>
    <h1>Modal YOLOv11 Live Result Viewer</h1>
    <p id="status" style="margin: -8px 16px 0; color: #7dd3fc; font-size: 13px;">Connecting result WebSocket...</p>
    <main id="grid"></main>
    <script>
      const grid = document.getElementById("grid");
      const status = document.getElementById("status");
      const sections = new Map();
      let connectedShards = 0;

      async function loadShardCount() {
        try {
          const response = await fetch("/health", { cache: "no-store" });
          const health = await response.json();
          return Number(health.num_shards || 1);
        } catch {
          return 1;
        }
      }

      function ensure(frame) {
        let state = sections.get(frame.camera_id);
        if (state) return state;
        const section = document.createElement("section");
        const title = document.createElement("h2");
        const meta = document.createElement("p");
        const img = document.createElement("img");
        section.append(title, meta, img);
        grid.append(section);
        state = { title, meta, img };
        sections.set(frame.camera_id, state);
        return state;
      }
      function render(frame) {
        const s = ensure(frame);
        s.title.textContent = frame.camera_id;
        const shard = frame.shard_id ?? "n/a";
        const worker = frame.worker_id ?? "n/a";
        s.meta.textContent = `seq ${frame.sequence_number} | shard ${shard} | ${worker} | detections ${frame.detection_count} | inference ${frame.inference_ms}ms | ${frame.modal_processed_at}`;
        if (frame.image_b64) s.img.src = "data:image/jpeg;base64," + frame.image_b64;
      }
      function connectShardResults(shardId, shardCount) {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const socket = new WebSocket(`${protocol}//${window.location.host}/ws/results/shards/${shardId}`);
        socket.onopen = () => {
          connectedShards += 1;
          status.textContent = `Result WebSocket connected ${connectedShards}/${shardCount}. Waiting for processed frames...`;
        };
        socket.onmessage = (event) => {
          const message = JSON.parse(event.data);
          if (message.type === "frame") {
            status.textContent = `Receiving live processed frames - ${message.timestamp}`;
            render(message.frame);
          }
        };
        socket.onclose = () => {
          connectedShards = Math.max(0, connectedShards - 1);
          status.textContent = `Shard ${shardId} result WebSocket disconnected. Reconnecting...`;
          setTimeout(() => connectShardResults(shardId, shardCount), 1000);
        };
        socket.onerror = () => {
          status.textContent = `Shard ${shardId} result WebSocket error.`;
          socket.close();
        };
      }
      async function startViewer() {
        const shardCount = await loadShardCount();
        for (let shardId = 0; shardId < shardCount; shardId += 1) {
          connectShardResults(shardId, shardCount);
        }
      }
      startViewer();
    </script>
  </body>
</html>
"""
