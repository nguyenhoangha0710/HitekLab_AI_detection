// Man hinh He thong: AI chay o dau, hieu nang tung camera, ket noi Backend, quyen cua nguoi dang nhap.
import { api } from "../core/api.js";
import { LEVEL_LABELS, ROLE_LABELS, escapeHtml, formatAgo } from "../core/format.js";
import { average, latestRuntime, on, store } from "../core/store.js";

const ERROR_HINTS = {
  BACKEND_UNREACHABLE: "Không gọi được Backend. Kiểm tra Backend đang chạy và BACKEND_BASE_URL.",
  AUTH_FAILED: "Không lấy được token từ Backend. Kiểm tra BACKEND_CLIENT_ID và BACKEND_CLIENT_SECRET.",
  CAMERA_NOT_FOUND: "Backend chưa có camera này. Hai bên cần dùng chung bảng camera.",
  AREA_NOT_FOUND: "Backend không nhận ra khu vực (location) của camera.",
  AI_EVENT_NOT_FOUND: "Backend không đọc được sự kiện. Hai bên phải dùng chung database.",
  AI_EVENT_CAMERA_MISMATCH: "Camera trong sự kiện không khớp dữ liệu Backend.",
};

export function createSystemView(root) {
  let backend = null;
  let timer = null;
  const unsubscribers = [];

  function render() {
    const runtime = latestRuntime();
    const me = store.me || {};
    root.innerHTML = `
      <div class="system">
        <div class="toolbar"><h1 class="page-title">Hệ thống</h1></div>
        <div class="system-grid">
          <section class="sys-block">
            <h2>AI đang chạy ở đâu</h2>
            <div data-runtime-block>${runtimeTemplate(runtime)}</div>
          </section>
          <section class="sys-block">
            <h2>Kết nối Backend</h2>
            <div data-backend>${backendTemplate()}</div>
          </section>
          <section class="sys-block wide">
            <h2>Hiệu năng theo camera</h2>
            <table class="plain-table">
              <thead><tr><th scope="col">Camera</th><th scope="col">Kết quả AI cuối</th><th scope="col">Khung/giây</th><th scope="col">AI xử lý</th><th scope="col">Trễ đầu-cuối</th></tr></thead>
              <tbody data-perf>${perfRows()}</tbody>
            </table>
            <p class="help">Trễ đầu-cuối tính từ lúc camera chụp khung hình tới lúc trình duyệt nhận kết quả, trung bình 30 khung gần nhất.</p>
          </section>
          <section class="sys-block wide">
            <h2>Tài khoản và quyền</h2>
            ${
              store.authConfig.auth_mode === "jwt"
                ? `<p>${escapeHtml(me.full_name || me.email || "–")}, ${escapeHtml(ROLE_LABELS[me.role] || me.role || "")}</p>
                   <table class="plain-table">
                     <thead><tr><th scope="col">Khu vực</th><th scope="col">Quyền</th></tr></thead>
                     <tbody>${(me.locations || []).map((l) => `<tr><td>${escapeHtml(l.name)}</td><td>${escapeHtml(LEVEL_LABELS[l.level] || l.level)}</td></tr>`).join("") || `<tr><td colspan="2">Chưa được giao khu vực nào.</td></tr>`}</tbody>
                   </table>`
                : `<p class="muted">Đăng nhập đang tắt (AUTH_MODE=off): mọi người dùng đều thấy toàn bộ camera.</p>`
            }
          </section>
        </div>
      </div>`;
  }

  function runtimeTemplate(runtime) {
    if (!runtime) {
      return `<p class="muted">Chưa nhận được kết quả nào từ AI. Kiểm tra AI Service đang chạy và Edge Gateway đang gửi khung hình.</p>`;
    }
    const gpu = runtime.accelerator === "gpu";
    return `<p class="big-line ${runtime.accelerator}">${gpu ? `GPU ${escapeHtml(runtime.device_name)}` : "CPU"}</p>
      <p class="muted">Máy ${escapeHtml(runtime.host)}.${gpu ? "" : " Chạy CPU sẽ chậm; xem HUONG_DAN_CHAY.md để chuyển sang GPU."}</p>`;
  }

  let lastLive = 0;
  function liveUpdate() {
    const now = Date.now();
    if (now - lastLive < 1000) return;
    lastLive = now;
    const block = root.querySelector("[data-runtime-block]");
    if (block) block.innerHTML = runtimeTemplate(latestRuntime());
    const perf = root.querySelector("[data-perf]");
    if (perf) perf.innerHTML = perfRows();
  }

  function perfRows() {
    if (!store.cameras.length) return `<tr><td colspan="5">Không có camera.</td></tr>`;
    return store.cameras
      .map((camera) => {
        const stats = store.resultStats[camera.id];
        if (!stats) return `<tr><td>${escapeHtml(camera.name)}</td><td colspan="4" class="muted">Chưa có kết quả</td></tr>`;
        const seconds = Math.max(1, (stats.lastAt - stats.firstAt) / 1000);
        const fps = stats.count > 1 ? (stats.count - 1) / seconds : 0;
        const inference = average(stats.inferenceMs);
        const latency = average(stats.latencyMs);
        return `<tr>
          <td>${escapeHtml(camera.name)}</td>
          <td>${escapeHtml(formatAgo(new Date(stats.lastAt)))}</td>
          <td>${fps.toFixed(1)}</td>
          <td>${inference !== null ? `${Math.round(inference)} ms` : "–"}</td>
          <td>${latency !== null ? `${(latency / 1000).toFixed(2)} s` : "–"}</td>
        </tr>`;
      })
      .join("");
  }

  function backendTemplate() {
    if (!backend) return `<p class="muted">Đang kiểm tra…</p>`;
    if (backend.forbidden) return `<p class="muted">Chỉ chủ hoặc quản trị tenant xem được mục này.</p>`;
    if (backend.error) return `<p class="muted">Không đọc được trạng thái: ${escapeHtml(backend.error)}</p>`;
    if (!backend.enabled) return `<p class="big-line">Tự gom cảnh báo</p><p class="muted">ALERT_MODE=local: Zone Service tự tạo cảnh báo, không gửi sang Backend.</p>`;
    const healthy = backend.failed === 0 || (backend.accepted > 0 && backend.last_status_code && backend.last_status_code < 300);
    return `
      <p class="big-line ${healthy ? "gpu" : "bad"}">${healthy ? "Đang gửi được" : "Đang lỗi"}</p>
      <p class="muted">${escapeHtml(backend.base_url || "")}</p>
      <dl class="facts">
        <dt>Đã gửi</dt><dd>${backend.sent}</dd>
        <dt>Backend nhận</dt><dd>${backend.accepted}</dd>
        <dt>Thành cảnh báo</dt><dd>${backend.alerts_returned}</dd>
        <dt>Lỗi</dt><dd>${backend.failed}</dd>
      </dl>
      ${backend.last_error_code ? `<p class="notice">${escapeHtml(ERROR_HINTS[backend.last_error_code] || backend.last_error_message || backend.last_error_code)}</p>` : ""}`;
  }

  async function refreshBackend() {
    try {
      backend = await api("/api/integration/backend");
    } catch (error) {
      backend = /403/.test(error.message) || /owner\/admin/.test(error.message) ? { forbidden: true } : { error: error.message };
    }
    const slot = root.querySelector("[data-backend]");
    if (slot) slot.innerHTML = backendTemplate();
  }

  return {
    mount() {
      render();
      refreshBackend();
      timer = window.setInterval(() => {
        refreshBackend();
        const perf = root.querySelector("[data-perf]");
        if (perf) perf.innerHTML = perfRows();
      }, 5000);
      unsubscribers.push(on("result", liveUpdate));
    },
    unmount() {
      window.clearInterval(timer);
      unsubscribers.splice(0).forEach((off) => off());
    },
  };
}
