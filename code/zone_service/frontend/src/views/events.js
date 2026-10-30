// Man hinh Su kien & bang chung: loc su kien AI, xem anh/clip va chi tiet tung su kien.
import { api, withToken } from "../core/api.js";
import {
  RULE_LABELS,
  escapeHtml,
  formatDateTime,
  formatDuration,
  motionArrow,
  motionLabel,
  objectLabel,
  ruleLabel,
  toDate,
  trackLabel,
} from "../core/format.js";
import { cameraName, store } from "../core/store.js";

const PAGE_SIZE = 500;

export function createEventsView(root, { toast }) {
  const state = { events: [], selectedId: null, pollTimer: null, filters: { camera: "", type: "", from: "", to: "", alert: "" } };

  function render() {
    root.innerHTML = `
      <div class="events">
        <div class="toolbar">
          <h1 class="page-title">Sự kiện AI và bằng chứng</h1>
          <button type="button" data-reload>Tải lại</button>
        </div>
        <form class="filters" data-filters>
          <label class="field"><span>Camera</span>
            <select name="camera"><option value="">Tất cả camera</option>
              ${store.cameras.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join("")}
            </select>
          </label>
          <label class="field"><span>Loại sự kiện</span>
            <select name="type"><option value="">Tất cả</option>
              ${Object.entries(RULE_LABELS).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}
            </select>
          </label>
          <label class="field"><span>Từ</span><input type="datetime-local" name="from"></label>
          <label class="field"><span>Đến</span><input type="datetime-local" name="to"></label>
          <label class="field"><span>Cảnh báo Backend</span>
            <select name="alert"><option value="">Tất cả</option><option value="yes">Đã thành cảnh báo</option><option value="no">Chưa thành cảnh báo</option></select>
          </label>
        </form>
        <div class="events-layout">
          <section class="event-table-wrap">
            <p class="table-caption" data-caption></p>
            <table class="event-table">
              <thead><tr>
                <th scope="col">Thời điểm</th><th scope="col">Sự kiện</th><th scope="col">Camera, vùng</th>
                <th scope="col">Đối tượng</th><th scope="col">Ở lại</th><th scope="col">Cảnh báo</th>
              </tr></thead>
              <tbody data-rows></tbody>
            </table>
          </section>
          <aside class="event-detail" data-detail aria-live="polite"></aside>
        </div>
      </div>`;
    const form = root.querySelector("[data-filters]");
    Object.entries(state.filters).forEach(([key, value]) => {
      if (form[key]) form[key].value = value;
    });
    form.addEventListener("change", (changeEvent) => {
      Object.keys(state.filters).forEach((key) => (state.filters[key] = form[key].value));
      if (changeEvent.target.name === "camera") {
        load();
        return;
      }
      renderRows();
    });
    root.querySelector("[data-reload]").addEventListener("click", load);
    renderDetail();
    load();
  }

  async function load() {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (state.filters.camera) params.set("camera_id", state.filters.camera);
    try {
      state.events = await api(`/api/ai-events?${params}`);
      renderRows();
    } catch (error) {
      toast(`Không tải được sự kiện: ${error.message}`, "error");
    }
  }

  function filtered() {
    const from = state.filters.from ? toDate(state.filters.from) : null;
    const to = state.filters.to ? toDate(state.filters.to) : null;
    return state.events.filter((e) => {
      if (state.filters.camera && e.camera_id !== state.filters.camera) return false;
      if (state.filters.type && e.event_type !== state.filters.type) return false;
      if (state.filters.alert === "yes" && !e.alert_id) return false;
      if (state.filters.alert === "no" && e.alert_id) return false;
      const started = toDate(e.started_at);
      if (from && started && started < from) return false;
      if (to && started && started > to) return false;
      return true;
    });
  }

  function renderRows() {
    const rows = root.querySelector("[data-rows]");
    if (!rows) return;
    const list = filtered();
    root.querySelector("[data-caption]").textContent = list.length
      ? `${list.length} sự kiện${list.length >= PAGE_SIZE ? ` (chỉ tải ${PAGE_SIZE} sự kiện mới nhất)` : ""}`
      : "";
    if (!list.length) {
      rows.innerHTML = `<tr><td colspan="6" class="empty-cell">Không có sự kiện nào khớp bộ lọc. Thử bỏ bớt điều kiện lọc, hoặc vẽ vùng ở màn hình “Vùng và luật” để AI bắt đầu phát hiện.</td></tr>`;
      return;
    }
    rows.innerHTML = list
      .map((e) => {
        const p = e.payload || {};
        const direction = p.detection?.motion?.direction;
        return `
          <tr data-event="${escapeHtml(e.id)}" class="${e.id === state.selectedId ? "selected" : ""}" tabindex="0">
            <td class="nowrap">${escapeHtml(formatDateTime(e.started_at))}</td>
            <td><span class="rule-pill" data-rule="${escapeHtml(e.event_type)}">${escapeHtml(ruleLabel(e.event_type))}</span></td>
            <td>${escapeHtml(cameraName(e.camera_id))}<br><span class="muted">${escapeHtml(p.zone_name || "–")}</span></td>
            <td>${escapeHtml(subject(e))} ${escapeHtml(motionArrow(direction))}</td>
            <td>${escapeHtml(formatDuration(p.elapsed_seconds ?? secondsBetween(e.started_at, e.last_seen_at)))}</td>
            <td>${e.alert_id ? `<span class="ok">Có</span>` : `<span class="muted">Chưa</span>`}</td>
          </tr>`;
      })
      .join("");
    rows.querySelectorAll("[data-event]").forEach((row) => {
      const open = () => select(row.dataset.event);
      row.addEventListener("click", open);
      row.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
    });
  }

  function subject(e) {
    if (e.event_type === "crowd_limit") return `${e.payload?.object_count || ""} người`.trim();
    return `${objectLabel(e.object_type)} ${trackLabel(e.track_id)}`.trim();
  }

  function secondsBetween(a, b) {
    const start = toDate(a);
    const end = toDate(b);
    return start && end ? (end - start) / 1000 : 0;
  }

  const CLIP_WAIT_SECONDS = 90; // clip +-5s duoc Edge Gateway ghi va tai len sau vai giay
  const CLIP_POLL_MS = 5000;

  async function fetchEvidence(e) {
    const own = await api(`/api/ai-events/${encodeURIComponent(e.id)}/evidence`);
    if (!e.alert_id) return own;
    // Bang chung chi chup 1 lan cho moi canh bao -> lay ca bang chung cua cac su kien cung canh bao.
    const params = new URLSearchParams({ camera_id: e.camera_id, limit: "200" });
    const sameAlert = (await api(`/api/evidence?${params}`).catch(() => [])).filter((x) => x.alert_id === e.alert_id);
    const byId = new Map([...own, ...sameAlert].map((x) => [x.id, x]));
    return Array.from(byId.values()).sort((x, y) => String(y.captured_at).localeCompare(String(x.captured_at)));
  }

  async function select(eventId, attempt = 0) {
    window.clearTimeout(state.pollTimer);
    if (attempt === 0) {
      state.selectedId = eventId;
      root.querySelectorAll("[data-event]").forEach((row) => row.classList.toggle("selected", row.dataset.event === eventId));
      renderDetail(null, true);
    }
    const e = state.events.find((item) => item.id === eventId);
    if (!e) return;
    try {
      const evidence = await fetchEvidence(e);
      if (state.selectedId !== eventId) return;
      const hasClip = evidence.some(isClip);
      const lastSeen = toDate(e.last_seen_at || e.started_at);
      const recent = lastSeen && (Date.now() - lastSeen.getTime()) / 1000 < CLIP_WAIT_SECONDS;
      const waiting = !hasClip && recent && attempt < CLIP_WAIT_SECONDS / (CLIP_POLL_MS / 1000);
      renderDetail(evidence, false, waiting);
      if (waiting) state.pollTimer = window.setTimeout(() => select(eventId, attempt + 1), CLIP_POLL_MS);
    } catch (error) {
      renderDetail([]);
      toast(`Không tải được bằng chứng: ${error.message}`, "error");
    }
  }

  function isClip(item) {
    return item.evidence_type === "video_clip" || String(item.mime_type || "").startsWith("video/");
  }

  function mediaBlock(e, evidence, loading, waiting) {
    if (loading) return `<p class="muted">Đang tải bằng chứng…</p>`;
    const media = (item) => escapeHtml(withToken(item.media_url));
    const clips = (evidence || []).filter(isClip);
    const snapshots = (evidence || []).filter((x) => !isClip(x));
    const fromAlert = (item) => (item.ai_event_id !== e.id ? " (cùng cảnh báo)" : "");
    if (!clips.length && !snapshots.length) {
      return waiting
        ? `<div class="media-wait">Clip ±5 giây đang được ghi và tải lên, màn hình sẽ tự cập nhật.</div>`
        : `<p class="muted">Sự kiện này chưa có ảnh hoặc clip. Bằng chứng chỉ được chụp một lần cho mỗi cảnh báo trong mỗi 2 phút.</p>`;
    }
    const poster = snapshots[0] ? ` poster="${media(snapshots[0])}"` : "";
    const clipHtml = clips
      .map(
        (c, i) => `
        <figure class="evidence-media">
          <video controls muted playsinline preload="metadata"${i === 0 ? poster : ""} src="${media(c)}"></video>
          <figcaption>Clip ${c.duration_seconds ? `${Number(c.duration_seconds).toFixed(0)} giây` : "±5 giây"} quanh lúc vi phạm, ${escapeHtml(formatDateTime(c.captured_at))}${escapeHtml(fromAlert(c))}${c.status && c.status !== "completed" ? `, trạng thái ${escapeHtml(c.status)}` : ""}</figcaption>
        </figure>`
      )
      .join("");
    const snapshotHtml = clips.length
      ? `<div class="snapshot-strip">${snapshots
          .map((s) => `<a href="${media(s)}" target="_blank" rel="noopener" title="Ảnh chụp lúc ${escapeHtml(formatDateTime(s.captured_at))}${escapeHtml(fromAlert(s))}"><img src="${media(s)}" alt="Ảnh chụp lúc ${escapeHtml(formatDateTime(s.captured_at))}"></a>`)
          .join("")}</div>`
      : snapshots
          .map(
            (s) => `
        <figure class="evidence-media">
          <img src="${media(s)}" alt="Ảnh bằng chứng lúc ${escapeHtml(formatDateTime(s.captured_at))}">
          <figcaption>Ảnh chụp lúc vi phạm, ${escapeHtml(formatDateTime(s.captured_at))}${escapeHtml(fromAlert(s))}</figcaption>
        </figure>`
          )
          .join("");
    const wait = !clips.length
      ? waiting
        ? `<div class="media-wait">Clip ±5 giây đang được ghi và tải lên, màn hình sẽ tự cập nhật.</div>`
        : `<p class="muted">Chưa có clip cho sự kiện này (Edge Gateway chưa ghi được, hoặc tắt EVIDENCE_VIDEO_ENABLED).</p>`
      : "";
    return clipHtml + snapshotHtml + wait;
  }

  function renderDetail(evidence = null, loading = false, waiting = false) {
    const panel = root.querySelector("[data-detail]");
    if (!panel) return;
    const e = state.events.find((item) => item.id === state.selectedId);
    if (!e) {
      panel.innerHTML = `<p class="empty-note">Chọn một sự kiện trong bảng để xem clip, ảnh và chi tiết.</p>`;
      return;
    }
    const p = e.payload || {};
    const objects = p.contract?.objects || [];
    panel.innerHTML = `
      <h2>${escapeHtml(ruleLabel(e.event_type))}</h2>
      <p class="muted">${escapeHtml(cameraName(e.camera_id))}, vùng ${escapeHtml(p.zone_name || "–")}</p>
      ${mediaBlock(e, evidence, loading, waiting)}
      <dl class="facts">
        <dt>Bắt đầu</dt><dd>${escapeHtml(formatDateTime(e.started_at))}</dd>
        <dt>Thấy lần cuối</dt><dd>${escapeHtml(formatDateTime(e.last_seen_at))}</dd>
        <dt>Đối tượng</dt><dd>${escapeHtml(subject(e))}</dd>
        <dt>Hướng đi</dt><dd>${escapeHtml(motionLabel(p.detection?.motion?.direction) || "–")}</dd>
        <dt>Độ tin cậy</dt><dd>${e.confidence !== null && e.confidence !== undefined ? Number(e.confidence).toFixed(2) : "–"}</dd>
        <dt>Cảnh báo Backend</dt><dd>${e.alert_id ? escapeHtml(e.alert_id) : "Chưa thành cảnh báo"}</dd>
        <dt>Mã sự kiện</dt><dd class="wrap">${escapeHtml(e.id)}</dd>
      </dl>
      ${
        objects.length > 1
          ? `<h3>Các đối tượng</h3><ul class="object-list">${objects
              .map((o) => `<li>${escapeHtml(objectLabel(String(o.object_type || "").toLowerCase()))} #${escapeHtml(o.track_id ?? "–")} ${escapeHtml(motionArrow(o.direction))}</li>`)
              .join("")}</ul>`
          : ""
      }`;
  }

  return {
    mount: render,
    unmount() {
      window.clearTimeout(state.pollTimer);
    },
  };
}
