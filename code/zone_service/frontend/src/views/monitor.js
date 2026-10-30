// Man hinh Giam sat: tuong camera co lop phu AI + cot vi pham dang dien ra.
import { withToken } from "../core/api.js";
import { countBy, escapeHtml, formatDuration, motionArrow, objectLabel, ruleLabel, trackLabel, zoneTypeInfo } from "../core/format.js";
import { drawOverlay } from "../core/overlay.js";
import { activeViolations, average, cameraName, loadZones, on, store } from "../core/store.js";

const MODE_KEY = "hitek_monitor_mode";

function readMode() {
  try {
    return localStorage.getItem(MODE_KEY) || "sync";
  } catch (error) {
    return "sync";
  }
}

function saveMode(mode) {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch (error) {
    // bo qua
  }
}

export function createMonitorView(root) {
  let mode = readMode(); // "sync": khung AI khop dung frame | "live": video truc tiep + khung moi nhat
  let focusedId = null;
  const renderedFrame = {};
  const unsubscribers = [];

  function tileTemplate(camera) {
    return `
      <article class="tile" data-camera="${escapeHtml(camera.id)}">
        <header class="tile-head">
          <button type="button" class="tile-title" data-focus title="Phóng to / thu nhỏ">${escapeHtml(camera.name)}</button>
          <span class="tile-state" data-state>Đang chờ AI</span>
        </header>
        <div class="stage">
          <img data-frame alt="Hình camera ${escapeHtml(camera.name)}">
          <canvas data-overlay aria-hidden="true"></canvas>
          <div class="stage-empty" data-empty>Chưa nhận được hình từ camera này.</div>
        </div>
        <footer class="tile-foot" data-foot></footer>
      </article>`;
  }

  function render() {
    root.innerHTML = `
      <div class="monitor">
        <section class="wall-wrap">
          <div class="toolbar">
            <h1 class="page-title">Giám sát camera</h1>
            <div class="segmented" role="group" aria-label="Cách hiển thị">
              <button type="button" data-mode="sync" aria-pressed="${mode === "sync"}" title="Hiện đúng khung hình AI đã xử lý; khung và hình luôn khớp nhau">Khớp khung AI</button>
              <button type="button" data-mode="live" aria-pressed="${mode === "live"}" title="Video trực tiếp mượt; khung AI vẽ theo kết quả mới nhất nên có thể lệch một nhịp">Video trực tiếp</button>
            </div>
          </div>
          <div class="wall ${focusedId ? "has-focus" : ""}" data-wall>
            ${store.cameras.length ? store.cameras.map(tileTemplate).join("") : `<p class="empty-note">Tài khoản này chưa được giao camera nào.</p>`}
          </div>
        </section>
        <aside class="rail" aria-label="Vi phạm đang diễn ra">
          <h2 class="rail-title">Đang vi phạm <span class="count" data-violation-count>0</span></h2>
          <ol class="violations" data-violations></ol>
          <p class="rail-note">Danh sách tự cập nhật theo kết quả AI. Một vi phạm biến mất khi đối tượng rời vùng quá 4 giây.</p>
        </aside>
      </div>`;

    root.querySelectorAll("[data-mode]").forEach((button) =>
      button.addEventListener("click", () => {
        mode = button.dataset.mode;
        saveMode(mode);
        root.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
        store.cameras.forEach((camera) => setupStage(camera));
      })
    );
    root.querySelectorAll("[data-focus]").forEach((button) =>
      button.addEventListener("click", () => {
        const id = button.closest("[data-camera]").dataset.camera;
        focusedId = focusedId === id ? null : id;
        applyFocus();
      })
    );
    store.cameras.forEach((camera) => {
      setupStage(camera);
      if (!store.zonesByCamera[camera.id]) loadZones(camera.id).catch(() => {});
      paintResult(camera.id);
    });
    applyFocus();
    renderViolations(activeViolations());
  }

  function applyFocus() {
    const wall = root.querySelector("[data-wall]");
    if (!wall) return;
    wall.classList.toggle("has-focus", Boolean(focusedId));
    wall.querySelectorAll("[data-camera]").forEach((tile) => {
      tile.classList.toggle("focused", tile.dataset.camera === focusedId);
      tile.hidden = Boolean(focusedId) && tile.dataset.camera !== focusedId;
    });
    store.cameras.forEach((camera) => redraw(camera.id));
  }

  function tile(cameraId) {
    return root.querySelector(`[data-camera="${CSS.escape(cameraId)}"]`);
  }

  function setupStage(camera) {
    const el = tile(camera.id);
    if (!el) return;
    const img = el.querySelector("[data-frame]");
    renderedFrame[camera.id] = null;
    img.onload = () => {
      el.querySelector("[data-empty]").hidden = true;
      redraw(camera.id);
    };
    img.onerror = () => {
      if (mode === "live") el.querySelector("[data-empty]").hidden = false;
    };
    if (mode === "live") {
      img.src = withToken(camera.live_stream_url);
    } else {
      img.removeAttribute("src");
      paintResult(camera.id);
    }
  }

  function paintResult(cameraId) {
    const el = tile(cameraId);
    const result = store.results[cameraId];
    if (!el || !result) return;
    if (mode === "sync" && result.frame_id && renderedFrame[cameraId] !== result.frame_id) {
      const img = el.querySelector("[data-frame]");
      const frameId = result.frame_id;
      const next = new Image();
      next.onload = () => {
        renderedFrame[cameraId] = frameId;
        img.src = next.src;
      };
      next.src = withToken(`/api/cameras/${encodeURIComponent(cameraId)}/frames/${encodeURIComponent(frameId)}.jpg`);
    } else {
      redraw(cameraId);
    }
    updateFoot(cameraId);
  }

  function redraw(cameraId) {
    const el = tile(cameraId);
    if (!el || el.hidden) return;
    const img = el.querySelector("[data-frame]");
    const result = store.results[cameraId] || null;
    const hotZones = new Set(activeViolations().filter((v) => v.cameraId === cameraId).map((v) => v.zone_id));
    drawOverlay(
      el.querySelector("[data-overlay]"),
      { width: img.naturalWidth, height: img.naturalHeight },
      store.zonesByCamera[cameraId] || [],
      result,
      hotZones
    );
  }

  function updateFoot(cameraId) {
    const el = tile(cameraId);
    const result = store.results[cameraId];
    if (!el || !result) return;
    const stats = store.resultStats[cameraId] || {};
    const counts = countBy(result.detections || [], (d) => d.class_name);
    const objects = Object.entries(counts)
      .map(([type, n]) => `${n} ${objectLabel(type).toLowerCase()}`)
      .join(", ");
    const inference = average(stats.inferenceMs);
    const latency = average(stats.latencyMs);
    const rt = result.ai_runtime;
    const device = rt ? (rt.accelerator === "gpu" ? `GPU ${rt.device_name}` : "CPU") : "";
    el.querySelector("[data-foot]").innerHTML = `
      <span>${objects ? escapeHtml(objects) : "Không có đối tượng"}</span>
      <span class="foot-metrics">
        ${inference !== null ? `<span title="Thời gian AI xử lý 1 khung hình">AI ${Math.round(inference)} ms</span>` : ""}
        ${latency !== null ? `<span title="Từ lúc chụp khung hình tới lúc trình duyệt nhận kết quả">trễ ${(latency / 1000).toFixed(1)} s</span>` : ""}
        ${rt ? `<span class="device ${rt.accelerator}" title="Nơi AI Service đang chạy">${escapeHtml(device)} @ ${escapeHtml(rt.host)}</span>` : ""}
      </span>`;
    const hot = activeViolations().some((v) => v.cameraId === cameraId);
    el.classList.toggle("alarm", hot);
    el.querySelector("[data-state]").textContent = hot ? "Có vi phạm" : "Đang theo dõi";
  }

  function renderViolations(list) {
    const container = root.querySelector("[data-violations]");
    if (!container) return;
    root.querySelector("[data-violation-count]").textContent = String(list.length);
    if (!list.length) {
      container.innerHTML = `<li class="violation-empty">Không có vi phạm nào lúc này.</li>`;
      return;
    }
    container.innerHTML = list
      .map((v) => {
        const zone = (store.zonesByCamera[v.cameraId] || []).find((z) => z.id === v.zone_id);
        const color = zoneTypeInfo(zone?.zone_type).color;
        const subject = v.rule_type === "crowd_limit" ? `${v.object_count || ""} người` : `${objectLabel(v.object_type)} ${trackLabel(v.track_id)}`;
        return `
          <li class="violation" style="--zone:${color}">
            <button type="button" data-goto="${escapeHtml(v.cameraId)}">
              <span class="v-rule">${escapeHtml(ruleLabel(v.rule_type))}</span>
              <span class="v-time">${escapeHtml(formatDuration(v.elapsed_seconds))}</span>
              <span class="v-where">${escapeHtml(v.zone_name || "")}, ${escapeHtml(cameraName(v.cameraId))}</span>
              <span class="v-who">${escapeHtml(subject.trim())} ${escapeHtml(motionArrow(v.direction))}</span>
            </button>
          </li>`;
      })
      .join("");
    container.querySelectorAll("[data-goto]").forEach((button) =>
      button.addEventListener("click", () => {
        focusedId = button.dataset.goto;
        applyFocus();
      })
    );
  }

  return {
    mount() {
      render();
      unsubscribers.push(
        on("result", ({ cameraId }) => paintResult(cameraId)),
        on("violations", (list) => {
          renderViolations(list);
          store.cameras.forEach((camera) => updateFoot(camera.id));
        }),
        on("zones", ({ cameraId }) => redraw(cameraId))
      );
      window.addEventListener("resize", onResize);
    },
    unmount() {
      unsubscribers.splice(0).forEach((off) => off());
      window.removeEventListener("resize", onResize);
      root.querySelectorAll("[data-frame]").forEach((img) => img.removeAttribute("src")); // dong MJPEG
    },
  };

  function onResize() {
    store.cameras.forEach((camera) => redraw(camera.id));
  }
}
