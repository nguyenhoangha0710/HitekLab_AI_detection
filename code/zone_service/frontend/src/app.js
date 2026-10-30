// Khoi dong console AI Vision: dang nhap, tai camera, ket noi ket qua AI, dieu huong 4 man hinh.
import { fetchMe, getAuthConfig, renderLoginScreen, renderUserChip } from "./core/auth.js";
import { escapeHtml } from "./core/format.js";
import { activeViolations, connectResults, latestRuntime, loadCameras, on, store } from "./core/store.js";
import { createEventsView } from "./views/events.js";
import { createMonitorView } from "./views/monitor.js";
import { createSystemView } from "./views/system.js";
import { createZonesView } from "./views/zones.js";

const viewRoot = document.getElementById("view");
const toastsEl = document.querySelector("[data-toasts]");
const runtimeEl = document.querySelector("[data-runtime]");
const cameraStatusEl = document.querySelector("[data-camera-status]");

function toast(message, kind = "info") {
  const item = document.createElement("div");
  item.className = `toast ${kind}`;
  item.textContent = message;
  toastsEl.appendChild(item);
  window.setTimeout(() => item.remove(), kind === "error" ? 7000 : 3500);
}

const views = {
  monitor: () => createMonitorView(viewRoot),
  zones: () => createZonesView(viewRoot, { toast }),
  events: () => createEventsView(viewRoot, { toast }),
  system: () => createSystemView(viewRoot),
};
let current = null;

function routeName() {
  const name = window.location.hash.replace(/^#\/?/, "");
  return views[name] ? name : "monitor";
}

function navigate() {
  const name = routeName();
  current?.unmount();
  current = views[name]();
  current.mount();
  document.querySelectorAll("[data-route]").forEach((link) => {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function renderRuntime() {
  const rt = latestRuntime();
  if (!rt) return;
  runtimeEl.className = `runtime ${rt.accelerator}`;
  runtimeEl.textContent = rt.accelerator === "gpu" ? `AI: GPU ${rt.device_name} @ ${rt.host}` : `AI: CPU @ ${rt.host}`;
}

function renderCameraStatus() {
  const hot = new Set(activeViolations().map((v) => v.cameraId));
  const now = Date.now();
  cameraStatusEl.innerHTML = store.cameras
    .map((camera) => {
      const last = store.resultStats[camera.id]?.lastAt;
      const status = hot.has(camera.id) ? "alarm" : last && now - last < 10000 ? "ok" : "idle";
      const label = { alarm: "có vi phạm", ok: "AI đang xử lý", idle: "chưa có kết quả AI" }[status];
      return `<li class="cam cam-${status}" title="${escapeHtml(label)}"><span class="dot" aria-hidden="true"></span>${escapeHtml(camera.name)}<span class="sr-only">, ${escapeHtml(label)}</span></li>`;
    })
    .join("");
}

async function start() {
  store.authConfig = await getAuthConfig();
  const me = await fetchMe(store.authConfig);
  if (!me) {
    document.querySelector(".app").classList.add("signed-out");
    await renderLoginScreen(viewRoot, store.authConfig);
    return;
  }
  store.me = me;
  renderUserChip(document.querySelector("[data-user]"), me, store.authConfig);
  window.addEventListener("auth-required", () => toast("Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục.", "error"));

  try {
    await loadCameras();
  } catch (error) {
    toast(`Không tải được danh sách camera: ${error.message}`, "error");
  }
  connectResults();
  on("result", renderRuntime);
  on("violations", renderCameraStatus);
  window.setInterval(renderCameraStatus, 3000);
  renderCameraStatus();

  window.addEventListener("hashchange", navigate);
  navigate();
}

start().catch((error) => toast(`Lỗi khởi động: ${error.message}`, "error"));
