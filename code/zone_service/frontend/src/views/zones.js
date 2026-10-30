// Man hinh Vung & luat: chup anh nen, ve da giac vung, sua luat canh bao cua tung vung.
import { api, withToken } from "../core/api.js";
import { OBJECT_LABELS, RULE_HINTS, ZONE_TYPES, escapeHtml, ruleLabel, zoneTypeInfo } from "../core/format.js";
import { drawHandle, drawPolygon } from "../core/overlay.js";
import { loadZones, store } from "../core/store.js";

const DRAFT_COLOR = "#5cc8ff";
const RULE_OBJECTS = ["person", "vehicle", "car", "motorcycle"];

export function createZonesView(root, { toast }) {
  const state = {
    cameraId: null,
    reference: null,
    image: null,
    draft: [],
    dragging: null,
    openZoneId: null,
  };

  function canEdit(cameraId) {
    const camera = store.cameras.find((c) => c.id === cameraId);
    const me = store.me;
    if (!camera || !me || me.unrestricted) return true;
    const loc = (me.locations || []).find((l) => l.id === camera.location_id);
    return loc?.level === "admin";
  }

  function render() {
    if (!state.cameraId && store.cameras.length) state.cameraId = store.cameras[0].id;
    const editable = canEdit(state.cameraId);
    root.innerHTML = `
      <div class="zones">
        <div class="toolbar">
          <h1 class="page-title">Vùng giám sát và luật cảnh báo</h1>
          <label class="field inline">
            <span>Camera</span>
            <select data-camera-select>
              ${store.cameras.map((c) => `<option value="${escapeHtml(c.id)}" ${c.id === state.cameraId ? "selected" : ""}>${escapeHtml(c.name)}</option>`).join("")}
            </select>
          </label>
        </div>
        ${editable ? "" : `<p class="notice">Bạn chỉ có quyền xem ở khu vực này. Muốn vẽ vùng hoặc sửa luật cần quyền Quản trị khu vực.</p>`}
        <div class="zones-layout">
          <section class="canvas-panel">
            <div class="canvas-tools">
              <button type="button" data-capture ${editable ? "" : "disabled"}>Chụp ảnh nền mới</button>
              <span class="tool-sep" aria-hidden="true"></span>
              <button type="button" data-undo ${editable ? "" : "disabled"}>Bỏ điểm cuối</button>
              <button type="button" data-clear ${editable ? "" : "disabled"}>Xoá hình đang vẽ</button>
              <span class="point-count" data-point-count>0 điểm</span>
            </div>
            <div class="canvas-wrap">
              <canvas data-canvas></canvas>
              <div class="stage-empty" data-empty>Chưa có ảnh nền. Bấm “Chụp ảnh nền mới” để lấy một khung hình từ camera rồi vẽ vùng lên đó.</div>
            </div>
            <form class="new-zone" data-new-zone>
              <p class="help">Bấm lên ảnh để thêm điểm, kéo điểm để chỉnh. Cần ít nhất 3 điểm.</p>
              <label class="field"><span>Tên vùng</span><input name="name" required maxlength="120" placeholder="Ví dụ: Cửa kho số 2"></label>
              <label class="field"><span>Loại vùng</span>
                <select name="zone_type">
                  ${Object.entries(ZONE_TYPES).map(([value, info]) => `<option value="${value}">${info.label}</option>`).join("")}
                </select>
              </label>
              <button type="submit" class="primary" ${editable ? "" : "disabled"}>Lưu vùng</button>
            </form>
          </section>
          <section class="zone-list" data-zone-list aria-label="Các vùng đã lưu"></section>
        </div>
      </div>`;

    const canvas = root.querySelector("[data-canvas]");
    root.querySelector("[data-camera-select]").addEventListener("change", (e) => selectCamera(e.target.value));
    root.querySelector("[data-capture]").addEventListener("click", capture);
    root.querySelector("[data-undo]").addEventListener("click", () => {
      state.draft.pop();
      draw();
    });
    root.querySelector("[data-clear]").addEventListener("click", () => {
      state.draft = [];
      draw();
    });
    root.querySelector("[data-new-zone]").addEventListener("submit", saveZone);
    if (editable) {
      canvas.addEventListener("pointerdown", onDown);
      canvas.addEventListener("pointermove", onMove);
      canvas.addEventListener("pointerup", onUp);
      canvas.addEventListener("pointerleave", onUp);
    }
    if (state.cameraId) selectCamera(state.cameraId);
  }

  async function selectCamera(cameraId) {
    state.cameraId = cameraId;
    state.reference = null;
    state.image = null;
    state.draft = [];
    state.openZoneId = null;
    await Promise.all([loadReference(), loadZones(cameraId).catch((e) => toast(`Không tải được vùng: ${e.message}`, "error"))]);
    renderZoneList();
    draw();
  }

  async function loadReference() {
    try {
      state.reference = await api(`/api/cameras/${encodeURIComponent(state.cameraId)}/reference-frame`);
      await loadImage(state.reference.image_url);
    } catch (error) {
      state.reference = null;
      state.image = null;
    }
  }

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => {
        state.image = image;
        resolve();
      };
      image.onerror = reject;
      image.src = withToken(`${url}?t=${Date.now()}`);
    });
  }

  async function capture() {
    try {
      state.reference = await api(`/api/cameras/${encodeURIComponent(state.cameraId)}/reference-frame`, { method: "POST" });
      await loadImage(state.reference.image_url);
      state.draft = [];
      draw();
      toast("Đã chụp ảnh nền mới");
    } catch (error) {
      toast(`Không chụp được ảnh nền: ${error.message}`, "error");
    }
  }

  async function saveZone(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!state.reference) return toast("Cần chụp ảnh nền trước khi lưu vùng.", "error");
    if (state.draft.length < 3) return toast("Vùng cần ít nhất 3 điểm.", "error");
    const name = form.name.value.trim();
    if (!name) return toast("Đặt tên cho vùng trước khi lưu.", "error");
    try {
      await api(`/api/cameras/${encodeURIComponent(state.cameraId)}/zones`, {
        method: "POST",
        body: JSON.stringify({
          name,
          zone_type: form.zone_type.value,
          polygon: { points: state.draft },
          frame_width: state.reference.frame_width,
          frame_height: state.reference.frame_height,
          enabled: true,
        }),
      });
      state.draft = [];
      form.reset();
      await loadZones(state.cameraId);
      renderZoneList();
      draw();
      toast(`Đã lưu vùng “${name}”. AI áp dụng sau tối đa 10 giây.`);
    } catch (error) {
      toast(`Không lưu được vùng: ${error.message}`, "error");
    }
  }

  async function toggleZone(zone) {
    try {
      await api(`/api/zones/${encodeURIComponent(zone.id)}`, { method: "PUT", body: JSON.stringify({ enabled: !zone.enabled }) });
      await loadZones(state.cameraId);
      renderZoneList();
      draw();
    } catch (error) {
      toast(`Không đổi được trạng thái vùng: ${error.message}`, "error");
    }
  }

  async function deleteZone(zone) {
    if (!window.confirm(`Xoá vùng “${zone.name}” và các luật của nó?`)) return;
    try {
      await api(`/api/zones/${encodeURIComponent(zone.id)}`, { method: "DELETE" });
      await loadZones(state.cameraId);
      renderZoneList();
      draw();
      toast(`Đã xoá vùng “${zone.name}”`);
    } catch (error) {
      toast(`Không xoá được vùng: ${error.message}`, "error");
    }
  }

  function renderZoneList() {
    const list = root.querySelector("[data-zone-list]");
    if (!list) return;
    const zones = store.zonesByCamera[state.cameraId] || [];
    const editable = canEdit(state.cameraId);
    if (!zones.length) {
      list.innerHTML = `<div class="empty-note">Camera này chưa có vùng nào. Vẽ vùng trên ảnh nền rồi bấm “Lưu vùng”.</div>`;
      return;
    }
    list.innerHTML = zones
      .map((zone) => {
        const info = zoneTypeInfo(zone.zone_type);
        const rules = store.rulesByZone[zone.id] || [];
        const open = state.openZoneId === zone.id;
        const activeRules = rules.filter((r) => r.enabled).length;
        return `
          <article class="zone-item ${open ? "open" : ""} ${zone.enabled ? "" : "disabled"}" style="--zone:${info.color}" data-zone="${escapeHtml(zone.id)}">
            <header>
              <button type="button" class="zone-toggle" data-open aria-expanded="${open}">
                <span class="zone-swatch" aria-hidden="true"></span>
                <span class="zone-name">${escapeHtml(zone.name)}</span>
                <span class="zone-meta">${escapeHtml(info.label)}, ${activeRules}/${rules.length} luật đang bật${zone.enabled ? "" : ", vùng đang tắt"}</span>
              </button>
            </header>
            ${
              open
                ? `<div class="zone-body">
                    ${rules.map((rule) => ruleForm(rule, editable)).join("") || `<p class="muted">Vùng này chưa có luật.</p>`}
                    <div class="zone-actions">
                      <button type="button" data-toggle-zone ${editable ? "" : "disabled"}>${zone.enabled ? "Tắt vùng" : "Bật vùng"}</button>
                      <button type="button" class="danger" data-delete ${editable ? "" : "disabled"}>Xoá vùng</button>
                    </div>
                  </div>`
                : ""
            }
          </article>`;
      })
      .join("");

    list.querySelectorAll("[data-zone]").forEach((item) => {
      const zone = zones.find((z) => z.id === item.dataset.zone);
      item.querySelector("[data-open]").addEventListener("click", () => {
        state.openZoneId = state.openZoneId === zone.id ? null : zone.id;
        renderZoneList();
        draw();
      });
      item.querySelector("[data-toggle-zone]")?.addEventListener("click", () => toggleZone(zone));
      item.querySelector("[data-delete]")?.addEventListener("click", () => deleteZone(zone));
      item.querySelectorAll("form[data-rule]").forEach((form) => form.addEventListener("submit", saveRule));
      item.querySelectorAll("input[name=use_active_time]").forEach((box) =>
        box.addEventListener("change", () => {
          box.closest("form").querySelectorAll("[data-time]").forEach((input) => (input.disabled = !box.checked));
        })
      );
    });
  }

  function ruleForm(rule, editable) {
    const disabled = editable ? "" : "disabled";
    const isCrowd = rule.rule_type === "crowd_limit";
    const value = (v) => (v === null || v === undefined ? "" : escapeHtml(v));
    const time = (v) => (v ? escapeHtml(String(v).slice(0, 5)) : "");
    return `
      <form class="rule" data-rule="${escapeHtml(rule.id)}">
        <div class="rule-head">
          <label class="switch">
            <input type="checkbox" name="enabled" ${rule.enabled ? "checked" : ""} ${disabled}>
            <span>${escapeHtml(ruleLabel(rule.rule_type))}</span>
          </label>
        </div>
        <p class="help">${escapeHtml(RULE_HINTS[rule.rule_type] || "")}</p>
        <div class="rule-fields">
          <label class="field"><span>Đối tượng</span>
            <select name="object_type" ${disabled}>
              ${RULE_OBJECTS.map((o) => `<option value="${o}" ${rule.object_type === o ? "selected" : ""}>${OBJECT_LABELS[o]}</option>`).join("")}
            </select>
          </label>
          <label class="field"><span>Ở trong vùng từ (giây)</span>
            <input type="number" name="duration_threshold" min="0" value="${value(rule.duration_threshold)}" ${disabled}>
          </label>
          ${
            isCrowd
              ? `<label class="field"><span>Số người từ</span>
                   <input type="number" name="people_threshold" min="1" value="${value(rule.people_threshold)}" ${disabled}>
                 </label>`
              : ""
          }
          <label class="field"><span>Độ tin cậy tối thiểu</span>
            <input type="number" name="confidence_threshold" min="0" max="1" step="0.05" value="${value(rule.confidence_threshold)}" ${disabled}>
          </label>
        </div>
        <fieldset class="rule-time">
          <legend class="sr-only">Khung giờ áp dụng</legend>
          <label class="check"><input type="checkbox" name="use_active_time" ${rule.use_active_time ? "checked" : ""} ${disabled}> Chỉ áp dụng trong khung giờ</label>
          <div class="time-range">
            <span>từ</span>
            <input type="time" name="active_start_time" data-time value="${time(rule.active_start_time)}" ${rule.use_active_time && editable ? "" : "disabled"} aria-label="Từ giờ">
            <span>đến</span>
            <input type="time" name="active_end_time" data-time value="${time(rule.active_end_time)}" ${rule.use_active_time && editable ? "" : "disabled"} aria-label="Đến giờ">
          </div>
        </fieldset>
        ${editable ? `<button type="submit" class="small">Lưu luật</button>` : ""}
      </form>`;
  }

  async function saveRule(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const num = (name) => (form[name] && form[name].value !== "" ? Number(form[name].value) : null);
    const payload = {
      enabled: form.enabled.checked,
      object_type: form.object_type.value || null,
      duration_threshold: num("duration_threshold"),
      confidence_threshold: num("confidence_threshold"),
      use_active_time: form.use_active_time.checked,
      active_start_time: form.active_start_time.value || null,
      active_end_time: form.active_end_time.value || null,
    };
    if (form.people_threshold) payload.people_threshold = num("people_threshold");
    if (payload.use_active_time && (!payload.active_start_time || !payload.active_end_time)) {
      return toast("Chọn đủ giờ bắt đầu và kết thúc, hoặc bỏ chọn khung giờ.", "error");
    }
    try {
      await api(`/api/rules/${encodeURIComponent(form.dataset.rule)}`, { method: "PUT", body: JSON.stringify(payload) });
      await loadZones(state.cameraId);
      renderZoneList();
      toast("Đã lưu luật. AI áp dụng sau tối đa 10 giây.");
    } catch (error) {
      toast(`Không lưu được luật: ${error.message}`, "error");
    }
  }

  // ------------------------------------------------------------- canvas
  function draw() {
    const canvas = root.querySelector("[data-canvas]");
    if (!canvas) return;
    const empty = root.querySelector("[data-empty]");
    root.querySelector("[data-point-count]").textContent = `${state.draft.length} điểm`;
    if (!state.image) {
      canvas.hidden = true;
      empty.hidden = false;
      return;
    }
    canvas.hidden = false;
    empty.hidden = true;
    canvas.width = state.image.naturalWidth;
    canvas.height = state.image.naturalHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(state.image, 0, 0);
    (store.zonesByCamera[state.cameraId] || []).forEach((zone) => {
      const sx = canvas.width / Math.max(1, zone.frame_width);
      const sy = canvas.height / Math.max(1, zone.frame_height);
      const points = (zone.polygon?.points || []).map((p) => ({ x: p.x * sx, y: p.y * sy }));
      const focus = state.openZoneId === zone.id;
      drawPolygon(ctx, points, zoneTypeInfo(zone.zone_type).color, focus ? 0.3 : 0.12, {
        dashed: !zone.enabled,
        width: focus ? 4 : 2,
      });
    });
    drawPolygon(ctx, state.draft, DRAFT_COLOR, 0.25, { width: 3 });
    state.draft.forEach((p) => drawHandle(ctx, p, DRAFT_COLOR));
  }

  function pointFromEvent(event) {
    const canvas = root.querySelector("[data-canvas]");
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.round((event.clientX - rect.left) * (canvas.width / rect.width)),
      y: Math.round((event.clientY - rect.top) * (canvas.height / rect.height)),
    };
  }

  function nearest(point) {
    const canvas = root.querySelector("[data-canvas]");
    const threshold = 12 * (canvas.width / Math.max(1, canvas.getBoundingClientRect().width));
    return state.draft.findIndex((p) => Math.hypot(p.x - point.x, p.y - point.y) <= threshold);
  }

  function onDown(event) {
    if (!state.image) return;
    const point = pointFromEvent(event);
    const index = nearest(point);
    if (index >= 0) {
      state.dragging = index;
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    state.draft.push(point);
    draw();
  }

  function onMove(event) {
    if (state.dragging === null) return;
    state.draft[state.dragging] = pointFromEvent(event);
    draw();
  }

  function onUp(event) {
    if (state.dragging === null) return;
    state.dragging = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  return {
    mount: render,
    unmount() {},
  };
}
