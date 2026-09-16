import { api } from "./core/api.js";
import { createEvidenceTab } from "./evidence/evidence_tab.js";

const state = {
  cameras: [],
  selectedCameraId: null,
  referenceFrame: null,
  referenceImage: null,
  zones: [],
  zoneRules: {},
  liveZones: {},
  liveZoneRules: {},
  liveDetections: {},
  liveEventSources: {},
  yoloRenderedFrameIds: {},
  ruleTrackStates: {},
  crowdRuleStates: {},
  violationStates: {},
  aiEvents: [],
  alerts: [],
  evidence: [],
  activeAlerts: [],
  draftPoints: [],
  draggingPointIndex: null,
};

const RULE_REATTACH_GRACE_MS = 3000;
const RULE_STATE_EXPIRE_MS = 5000;
const RULE_REATTACH_DISTANCE_PX = 80;
const RULE_REATTACH_MIN_AREA_RATIO = 0.5;
const RULE_REATTACH_MAX_AREA_RATIO = 2.0;

const els = {
  cameraList: document.getElementById("cameraList"),
  cameraGrid: document.getElementById("cameraGrid"),
  yoloGrid: document.getElementById("yoloGrid"),
  statusText: document.getElementById("statusText"),
  alertBanner: document.getElementById("alertBanner"),
  selectedCameraName: document.getElementById("selectedCameraName"),
  selectedCameraMeta: document.getElementById("selectedCameraMeta"),
  captureButton: document.getElementById("captureButton"),
  zoneCanvas: document.getElementById("zoneCanvas"),
  evidenceCameraFilter: document.getElementById("evidenceCameraFilter"),
  evidenceEventTypeFilter: document.getElementById("evidenceEventTypeFilter"),
  evidenceStatusFilter: document.getElementById("evidenceStatusFilter"),
  evidenceFromFilter: document.getElementById("evidenceFromFilter"),
  evidenceToFilter: document.getElementById("evidenceToFilter"),
  evidenceGrid: document.getElementById("evidenceGrid"),
  refreshEvidenceButton: document.getElementById("refreshEvidenceButton"),
  emptyState: document.getElementById("emptyState"),
  zoneName: document.getElementById("zoneName"),
  zoneType: document.getElementById("zoneType"),
  undoButton: document.getElementById("undoButton"),
  clearButton: document.getElementById("clearButton"),
  saveZoneButton: document.getElementById("saveZoneButton"),
  zoneList: document.getElementById("zoneList"),
  pointCount: document.getElementById("pointCount"),
};

const evidenceTab = createEvidenceTab({
  els,
  state,
  api,
  cameraById,
  ruleLabel,
  escapeHtml,
  setStatus,
});

async function loadCameras() {
  state.cameras = await api("/api/cameras");
  els.statusText.textContent = `${state.cameras.length} cameras loaded`;
  renderCameraList();
  evidenceTab.renderCameraFilter();
  renderLiveGrid();
  renderYoloGrid();
  if (state.cameras.length && !state.selectedCameraId) {
    await selectCamera(state.cameras[0].id);
  }
}

function cameraById(cameraId) {
  return state.cameras.find((camera) => camera.id === cameraId);
}

function renderCameraList() {
  els.cameraList.innerHTML = "";
  state.cameras.forEach((camera) => {
    const button = document.createElement("button");
    button.className = `camera-item ${camera.id === state.selectedCameraId ? "active" : ""}`;
    button.innerHTML = `<strong>${escapeHtml(camera.name)}</strong><span>${escapeHtml(camera.id)}</span>`;
    button.addEventListener("click", () => selectCamera(camera.id));
    els.cameraList.appendChild(button);
  });
}

function renderLiveGrid() {
  els.cameraGrid.innerHTML = "";
  state.cameras.forEach((camera) => {
    const card = document.createElement("article");
    card.className = "live-card";
    card.innerHTML = `
      <header>
        <h2>${escapeHtml(camera.name)}</h2>
        <p>${escapeHtml(camera.id)} | live stream</p>
      </header>
      <div class="live-stage">
        <img src="${camera.live_stream_url}" alt="${escapeHtml(camera.name)}">
      </div>
    `;
    els.cameraGrid.appendChild(card);
  });
}

function renderYoloGrid() {
  els.yoloGrid.innerHTML = "";
  state.cameras.forEach((camera) => {
    const card = document.createElement("article");
    card.className = "live-card";
    card.innerHTML = `
      <header>
        <h2>${escapeHtml(camera.name)}</h2>
        <p id="yolo-meta-${camera.id}">${escapeHtml(camera.id)} | YOLO stream waiting</p>
      </header>
      <div class="live-stage">
        <img id="yolo-img-${camera.id}" alt="${escapeHtml(camera.name)}" data-mode="bbox-sync">
        <canvas id="yolo-canvas-${camera.id}"></canvas>
      </div>
    `;
    els.yoloGrid.appendChild(card);
    const image = document.getElementById(`yolo-img-${camera.id}`);
    image.removeAttribute("src");
    image.addEventListener("load", () => drawYoloOverlay(camera.id));
    loadLiveZones(camera.id);
    connectLiveDetections(camera);
  });
}

async function selectCamera(cameraId) {
  state.selectedCameraId = cameraId;
  state.referenceFrame = null;
  state.referenceImage = null;
  state.draftPoints = [];
  const camera = cameraById(cameraId);
  els.selectedCameraName.textContent = camera ? camera.name : "Unknown camera";
  els.selectedCameraMeta.textContent = camera ? `${camera.id} | ${camera.source_type}` : "";
  renderCameraList();
  await Promise.all([loadReferenceFrame(), loadZones()]);
}

async function loadReferenceFrame() {
  if (!state.selectedCameraId) return;
  try {
    state.referenceFrame = await api(`/api/cameras/${encodeURIComponent(state.selectedCameraId)}/reference-frame`);
    await loadReferenceImage(state.referenceFrame.image_url);
  } catch (error) {
    state.referenceFrame = null;
    state.referenceImage = null;
    els.zoneCanvas.style.display = "none";
    els.emptyState.style.display = "grid";
    els.emptyState.textContent = "Capture a reference frame to edit zones.";
    draw();
  }
}

async function loadZones() {
  if (!state.selectedCameraId) return;
  state.zones = await api(`/api/cameras/${encodeURIComponent(state.selectedCameraId)}/zones`);
  state.liveZones[state.selectedCameraId] = state.zones;
  state.zoneRules = {};
  const ruleEntries = await Promise.all(
    state.zones.map(async (zone) => {
      try {
        return [zone.id, await api(`/api/zones/${encodeURIComponent(zone.id)}/rules`)];
      } catch (error) {
        return [zone.id, []];
      }
    })
  );
  ruleEntries.forEach(([zoneId, rules]) => {
    state.zoneRules[zoneId] = rules;
  });
  renderZoneList();
  draw();
  drawYoloOverlay(state.selectedCameraId);
}

async function captureReferenceFrame() {
  if (!state.selectedCameraId) return;
  setStatus("Capturing reference frame...");
  state.referenceFrame = await api(`/api/cameras/${encodeURIComponent(state.selectedCameraId)}/reference-frame`, {
    method: "POST",
  });
  state.draftPoints = [];
  await loadReferenceImage(state.referenceFrame.image_url);
  setStatus("Reference frame captured");
}

function loadReferenceImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      state.referenceImage = image;
      els.zoneCanvas.width = image.naturalWidth;
      els.zoneCanvas.height = image.naturalHeight;
      els.zoneCanvas.style.display = "block";
      els.emptyState.style.display = "none";
      draw();
      resolve();
    };
    image.onerror = reject;
    image.src = `${url}?t=${Date.now()}`;
  });
}

async function saveZone() {
  if (!state.selectedCameraId || !state.referenceFrame) {
    setStatus("Capture a reference frame before saving zone.");
    return;
  }
  if (state.draftPoints.length < 3) {
    setStatus("Zone needs at least 3 points.");
    return;
  }

  const zoneName = uniqueZoneName(els.zoneName.value.trim() || defaultZoneName());
  const payload = {
    name: zoneName,
    zone_type: els.zoneType.value,
    polygon: { points: state.draftPoints },
    frame_width: state.referenceFrame.frame_width,
    frame_height: state.referenceFrame.frame_height,
    enabled: true,
  };
  els.saveZoneButton.disabled = true;
  try {
    await api(`/api/cameras/${encodeURIComponent(state.selectedCameraId)}/zones`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.draftPoints = [];
    await loadZones();
    els.zoneName.value = uniqueZoneName(defaultZoneName());
    setStatus(`Zone saved: ${zoneName}`);
  } catch (error) {
    setStatus(`Save zone failed: ${error.message}`);
  } finally {
    els.saveZoneButton.disabled = false;
  }
}

function defaultZoneName() {
  if (els.zoneType.value === "controlled_area") return "Controlled Zone";
  return "Restricted Zone";
}

function uniqueZoneName(baseName) {
  const existingNames = new Set(state.zones.map((zone) => String(zone.name || "").toLowerCase()));
  if (!existingNames.has(baseName.toLowerCase())) return baseName;

  let index = 2;
  let candidate = `${baseName} ${index}`;
  while (existingNames.has(candidate.toLowerCase())) {
    index += 1;
    candidate = `${baseName} ${index}`;
  }
  return candidate;
}

async function deleteZone(zoneId) {
  await api(`/api/zones/${encodeURIComponent(zoneId)}`, { method: "DELETE" });
  await loadZones();
  setStatus("Zone deleted");
}

async function loadLiveZones(cameraId) {
  try {
    const zones = await api(`/api/cameras/${encodeURIComponent(cameraId)}/zones`);
    state.liveZones[cameraId] = zones;
    state.liveZoneRules[cameraId] = {};
    const ruleEntries = await Promise.all(
      zones.map(async (zone) => {
        try {
          return [zone.id, await api(`/api/zones/${encodeURIComponent(zone.id)}/rules`)];
        } catch (error) {
          return [zone.id, []];
        }
      })
    );
    ruleEntries.forEach(([zoneId, rules]) => {
      state.liveZoneRules[cameraId][zoneId] = rules;
    });
    drawYoloOverlay(cameraId);
  } catch (error) {
    state.liveZones[cameraId] = [];
    state.liveZoneRules[cameraId] = {};
  }
}

function connectLiveDetections(camera) {
  if (state.liveEventSources[camera.id]) {
    state.liveEventSources[camera.id].close();
  }
  const events = new EventSource(camera.detection_stream_url);
  state.liveEventSources[camera.id] = events;
  events.onmessage = (event) => {
    const result = JSON.parse(event.data);
    state.liveDetections[camera.id] = result;
    evaluateRules(camera.id, result);
    updateLiveMeta(camera.id, result);
    renderSyncedYoloFrame(camera.id, result);
  };
  events.onerror = () => {
    const meta = document.getElementById(`yolo-meta-${camera.id}`);
    if (meta && !state.liveDetections[camera.id]) {
      meta.textContent = `${camera.id} | YOLO stream waiting`;
    }
  };
}

function updateLiveMeta(cameraId, result) {
  const meta = document.getElementById(`yolo-meta-${cameraId}`);
  if (!meta || !result) return;
  const detections = result.detection_count ?? (result.detections || []).length;
  const inference = result.inference_ms !== undefined ? ` | ai ${result.inference_ms}ms` : "";
  const tracking = result.tracking?.enabled ? " | tracking on" : "";
  meta.textContent = `${cameraId} | bbox seq ${result.sequence_number} | detections ${detections}${inference}${tracking}`;
}

function renderSyncedYoloFrame(cameraId, result) {
  if (!result || !result.frame_id) {
    const meta = document.getElementById(`yolo-meta-${cameraId}`);
    if (meta) {
      meta.textContent = `${cameraId} | waiting for bbox frame_id`;
    }
    return;
  }
  if (state.yoloRenderedFrameIds[cameraId] === result.frame_id) return;

  const image = document.getElementById(`yolo-img-${cameraId}`);
  if (!image) return;

  image.dataset.expectedFrameId = result.frame_id;
  image.onload = () => {
    if (image.dataset.expectedFrameId !== result.frame_id) return;
    state.yoloRenderedFrameIds[cameraId] = result.frame_id;
    drawYoloOverlay(cameraId);
  };
  image.onerror = () => {
    const meta = document.getElementById(`yolo-meta-${cameraId}`);
    if (meta) {
      meta.textContent = `${cameraId} | bbox seq ${result.sequence_number} | matched frame expired`;
    }
  };
  // YOLO tab khong doc MJPEG live. Moi bbox event bat buoc fetch dung frame_id
  // da duoc AI xu ly, giong sync viewer ben Edge Gateway.
  image.src = `/api/cameras/${encodeURIComponent(cameraId)}/frames/${encodeURIComponent(result.frame_id)}.jpg?t=${Date.now()}`;
}

function renderZoneList() {
  els.zoneList.innerHTML = "";
  if (!state.zones.length) {
    els.zoneList.innerHTML = `<div class="zone-card"><p>No zones saved for this camera.</p></div>`;
    return;
  }
  state.zones.forEach((zone) => {
    const card = document.createElement("article");
    card.className = "zone-card";
    card.innerHTML = `
      <strong>${escapeHtml(zone.name)}</strong>
      <p>${escapeHtml(zone.zone_type)} | ${zone.polygon.points.length} points | ${zone.enabled ? "enabled" : "disabled"}</p>
      <div class="rule-list">
        ${ruleSelectorTemplate(zone.id, state.zoneRules[zone.id] || [])}
        <div class="rule-editor" data-rule-editor="${escapeHtml(zone.id)}"></div>
      </div>
      <button data-delete="${zone.id}">Delete Zone</button>
    `;
    card.querySelector("[data-delete]").addEventListener("click", () => deleteZone(zone.id));
    const ruleSelect = card.querySelector("[data-rule-select]");
    ruleSelect?.addEventListener("change", () => renderSelectedRuleEditor(zone.id, ruleSelect.value));
    card.querySelector("[data-rule-editor]")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-save-rule]");
      if (button) saveRule(button.dataset.saveRule);
    });
    els.zoneList.appendChild(card);
  });
}

function ruleSelectorTemplate(zoneId, rules) {
  if (!rules.length) {
    return `<p>No rules configured.</p>`;
  }
  return `
    <label class="rule-select-label">
      Rule
      <select data-rule-select="${escapeHtml(zoneId)}">
        <option value="">Select rule to edit</option>
        ${rules
          .map(
            (rule) =>
              `<option value="${escapeHtml(rule.id)}">${escapeHtml(ruleLabel(rule.rule_type))} ${
                rule.enabled ? "(active)" : "(off)"
              }</option>`
          )
          .join("")}
      </select>
    </label>
  `;
}

function renderSelectedRuleEditor(zoneId, ruleId) {
  const editor = els.zoneList.querySelector(`[data-rule-editor="${CSS.escape(zoneId)}"]`);
  if (!editor) return;
  if (!ruleId) {
    editor.innerHTML = "";
    return;
  }
  const rule = (state.zoneRules[zoneId] || []).find((item) => item.id === ruleId);
  editor.innerHTML = rule ? ruleTemplate(rule) : "";
}

function ruleTemplate(rule) {
  return `
    <section class="rule-card" data-rule="${escapeHtml(rule.id)}">
      <div class="rule-head">
        <strong>${escapeHtml(ruleLabel(rule.rule_type))}</strong>
        <label class="rule-toggle">
          <input type="checkbox" data-rule-input="enabled" ${rule.enabled ? "checked" : ""}>
          Active
        </label>
      </div>
      <div class="rule-grid">
        <label>
          Object
          <select data-rule-input="object_type">
            ${ruleObjectOption(rule.object_type, "person")}
            ${ruleObjectOption(rule.object_type, "car")}
          </select>
        </label>
        <label>
          Duration
          <input type="number" min="0" data-rule-input="duration_threshold" value="${nullableValue(rule.duration_threshold)}" placeholder="None">
        </label>
        <label>
          People
          <input type="number" min="0" data-rule-input="people_threshold" value="${nullableValue(rule.people_threshold)}" placeholder="None">
        </label>
        <label>
          Conf
          <input type="number" min="0" max="1" step="0.05" data-rule-input="confidence_threshold" value="${nullableValue(rule.confidence_threshold)}" placeholder="None">
        </label>
      </div>
      <div class="rule-time">
        <label class="rule-toggle">
          <input type="checkbox" data-rule-input="use_active_time" ${rule.use_active_time ? "checked" : ""}>
          Use active time
        </label>
        <input type="time" data-rule-input="active_start_time" value="${rule.active_start_time || ""}">
        <span>to</span>
        <input type="time" data-rule-input="active_end_time" value="${rule.active_end_time || ""}">
      </div>
      <button type="button" data-save-rule="${escapeHtml(rule.id)}">Save Rule</button>
    </section>
  `;
}

function ruleObjectOption(current, value) {
  return `<option value="${value}" ${current === value ? "selected" : ""}>${value}</option>`;
}

function nullableValue(value) {
  return value === null || value === undefined ? "" : String(value);
}

function ruleLabel(ruleType) {
  return String(ruleType || "")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

async function saveRule(ruleId) {
  const container = els.zoneList.querySelector(`[data-rule="${CSS.escape(ruleId)}"]`);
  if (!container) return;
  const payload = {
    enabled: ruleInput(container, "enabled").checked,
    object_type: emptyToNull(ruleInput(container, "object_type").value),
    duration_threshold: numberOrNull(ruleInput(container, "duration_threshold").value),
    people_threshold: numberOrNull(ruleInput(container, "people_threshold").value),
    confidence_threshold: numberOrNull(ruleInput(container, "confidence_threshold").value),
    use_active_time: ruleInput(container, "use_active_time").checked,
    active_start_time: emptyToNull(ruleInput(container, "active_start_time").value),
    active_end_time: emptyToNull(ruleInput(container, "active_end_time").value),
  };

  try {
    await api(`/api/rules/${encodeURIComponent(ruleId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadZones();
    setStatus("Rule saved");
  } catch (error) {
    setStatus(`Save rule failed: ${error.message}`);
  }
}

function ruleInput(container, field) {
  return container.querySelector(`[data-rule-input="${field}"]`);
}

function emptyToNull(value) {
  return value === "" ? null : value;
}

function numberOrNull(value) {
  return value === "" ? null : Number(value);
}

function canvasPointFromEvent(event) {
  const rect = els.zoneCanvas.getBoundingClientRect();
  return {
    x: Math.round((event.clientX - rect.left) * (els.zoneCanvas.width / rect.width)),
    y: Math.round((event.clientY - rect.top) * (els.zoneCanvas.height / rect.height)),
  };
}

function findNearestPoint(point) {
  const threshold = 12 * (els.zoneCanvas.width / Math.max(1, els.zoneCanvas.getBoundingClientRect().width));
  return state.draftPoints.findIndex((candidate) => {
    const dx = candidate.x - point.x;
    const dy = candidate.y - point.y;
    return Math.sqrt(dx * dx + dy * dy) <= threshold;
  });
}

function onCanvasPointerDown(event) {
  if (!state.referenceImage) return;
  const point = canvasPointFromEvent(event);
  const index = findNearestPoint(point);
  if (index >= 0) {
    state.draggingPointIndex = index;
    els.zoneCanvas.setPointerCapture(event.pointerId);
    return;
  }
  state.draftPoints.push(point);
  draw();
}

function onCanvasPointerMove(event) {
  if (state.draggingPointIndex === null) return;
  state.draftPoints[state.draggingPointIndex] = canvasPointFromEvent(event);
  draw();
}

function onCanvasPointerUp(event) {
  if (state.draggingPointIndex !== null) {
    state.draggingPointIndex = null;
    els.zoneCanvas.releasePointerCapture(event.pointerId);
  }
}

function draw() {
  const canvas = els.zoneCanvas;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  els.pointCount.textContent = `${state.draftPoints.length} points`;
  if (!state.referenceImage) return;

  ctx.drawImage(state.referenceImage, 0, 0, canvas.width, canvas.height);
  state.zones.forEach((zone) => drawPolygon(ctx, zone.polygon.points, zoneColor(zone), 0.18));
  drawPolygon(ctx, state.draftPoints, "#2dd4bf", 0.28);
  state.draftPoints.forEach((point) => drawHandle(ctx, point, "#2dd4bf"));
}

function drawYoloOverlay(cameraId) {
  const image = document.getElementById(`yolo-img-${cameraId}`);
  const canvas = document.getElementById(`yolo-canvas-${cameraId}`);
  if (!image || !canvas) return;

  const rect = image.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const frameWidth = image.naturalWidth || state.liveDetections[cameraId]?.frame_width || canvas.width;
  const frameHeight = image.naturalHeight || state.liveDetections[cameraId]?.frame_height || canvas.height;
  const viewport = containViewport(canvas.width, canvas.height, frameWidth, frameHeight);

  const scaledZones = (state.liveZones[cameraId] || [])
    .filter((zone) => zone.enabled !== false)
    .map((zone) => ({
      ...zone,
      scaledPoints: (zone.polygon.points || []).map((point) =>
        scalePoint(point, zone.frame_width, zone.frame_height, viewport)
      ),
    }));

  scaledZones.forEach((zone) => {
    const color = zoneColor(zone);
    drawPolygon(ctx, zone.scaledPoints, color, 0.16);
    drawZoneLabel(ctx, zone.scaledPoints, zone.name, color);
  });

  const result = state.liveDetections[cameraId];
  if (!result || !result.detections) return;
  result.detections.forEach((detection) => {
    const bottomCenter = detectionBottomCenter(detection, result.frame_width, result.frame_height, viewport);
    const matchedZones = scaledZones.filter((zone) => pointInPolygon(bottomCenter, zone.scaledPoints));
    drawDetection(ctx, detection, result.frame_width, result.frame_height, viewport, {
      bottomCenter,
      matchedZones,
    });
  });
}

function evaluateRules(cameraId, result) {
  if (!result || !Array.isArray(result.detections)) return;
  const now = Date.now();
  const zones = (state.liveZones[cameraId] || []).filter((zone) => zone.enabled !== false);
  const ruleMap = state.liveZoneRules[cameraId] || {};
  const seenTrackKeys = new Set();
  const crowdCounts = {};
  const alerts = [];

  result.detections.forEach((detection, index) => {
    const originalPoint = detectionBottomCenterOriginal(detection);
    const matchedZones = zones.filter((zone) => pointInPolygon(originalPoint, zone.polygon.points || []));
    matchedZones.forEach((zone) => {
      const rules = ruleMap[zone.id] || [];
      rules.forEach((rule) => {
        if (!ruleAppliesNow(rule, detection)) return;
        if (rule.rule_type === "crowd_limit") {
          const key = `${cameraId}|${zone.id}|${rule.id}`;
          crowdCounts[key] = crowdCounts[key] || { zone, rule, tracks: new Set() };
          crowdCounts[key].tracks.add(trackKey(detection, result, index));
          return;
        }

        const threshold = rule.duration_threshold;
        if (threshold === null || threshold === undefined) return;
        const currentTrackKey = trackKey(detection, result, index);
        const key = `${cameraId}|${zone.id}|${rule.id}|${currentTrackKey}`;
        seenTrackKeys.add(key);
        const existing =
          state.ruleTrackStates[key] ||
          reattachRuleState(cameraId, zone, rule, detection, result, index, currentTrackKey, seenTrackKeys, now) ||
          {
            firstSeenAt: now,
            cameraId,
            zoneId: zone.id,
            ruleId: rule.id,
            zoneName: zone.name,
            ruleType: rule.rule_type,
            objectType: detection.class_name,
            trackId: currentTrackKey,
            reattached: false,
            firstSequenceNumber: result.sequence_number,
            startedAt: new Date(now).toISOString(),
          };
        existing.cameraId = cameraId;
        existing.zoneId = zone.id;
        existing.ruleId = rule.id;
        existing.zoneName = zone.name;
        existing.ruleType = rule.rule_type;
        existing.objectType = detection.class_name;
        existing.trackId = currentTrackKey;
        existing.lastFootpoint = originalPoint;
        existing.lastBbox = detection.bbox_xyxy || null;
        existing.lastSeenAt = now;
        existing.lastSequenceNumber = result.sequence_number;
        state.ruleTrackStates[key] = existing;

        const elapsedSeconds = (now - existing.firstSeenAt) / 1000;
        if (elapsedSeconds >= Number(threshold)) {
          publishRuleViolationEvent(existing, zone, rule, detection, result, now);
          alerts.push({
            key,
            cameraId,
            zoneName: zone.name,
            ruleType: rule.rule_type,
            objectType: detection.class_name,
            trackId: existing.trackId,
            elapsedSeconds,
            sequenceNumber: result.sequence_number,
          });
        }
      });
    });
  });

  Object.values(crowdCounts).forEach(({ zone, rule, tracks }) => {
    const peopleThreshold = rule.people_threshold;
    const durationThreshold = rule.duration_threshold;
    if (peopleThreshold === null || peopleThreshold === undefined) return;
    if (durationThreshold === null || durationThreshold === undefined) return;

    const key = `${cameraId}|${zone.id}|${rule.id}`;
    if (tracks.size >= Number(peopleThreshold)) {
      const existing = state.crowdRuleStates[key] || { firstSeenAt: now };
      existing.lastSeenAt = now;
      existing.count = tracks.size;
      existing.cameraId = cameraId;
      existing.zoneId = zone.id;
      existing.ruleId = rule.id;
      existing.zoneName = zone.name;
      existing.ruleType = rule.rule_type;
      existing.objectType = "person";
      existing.trackId = `${tracks.size} objects`;
      existing.firstSequenceNumber = existing.firstSequenceNumber ?? result.sequence_number;
      existing.startedAt = existing.startedAt || new Date(now).toISOString();
      state.crowdRuleStates[key] = existing;
      const elapsedSeconds = (now - existing.firstSeenAt) / 1000;
      if (elapsedSeconds >= Number(durationThreshold)) {
        publishRuleViolationEvent(existing, zone, rule, null, result, now);
        alerts.push({
          key,
          cameraId,
          zoneName: zone.name,
          ruleType: rule.rule_type,
          objectType: "person",
          trackId: `${tracks.size} objects`,
          elapsedSeconds,
          sequenceNumber: result.sequence_number,
        });
      }
    } else {
      delete state.crowdRuleStates[key];
    }
  });

  expireRuleStates(cameraId, seenTrackKeys, now);
  updateAlerts(alerts, now);
}

function publishRuleViolationEvent(ruleState, zone, rule, detection, result, now) {
  if (ruleState.aiEventStatus === "pending" || ruleState.aiEventStatus === "created") return;

  const sourceEventId = ruleState.sourceEventId || buildSourceEventId(ruleState, rule, result);
  ruleState.sourceEventId = sourceEventId;
  ruleState.aiEventStatus = "pending";

  const payload = {
    source_event_id: sourceEventId,
    camera_id: ruleState.cameraId,
    zone_id: zone.id,
    rule_config_id: rule.id,
    event_type: rule.rule_type,
    object_type: ruleState.objectType || detection?.class_name || rule.object_type,
    track_id: ruleState.trackId,
    confidence: detection ? Number(detection.confidence || 0) : null,
    lifecycle_status: "active",
    first_sequence_number: ruleState.firstSequenceNumber,
    last_sequence_number: result.sequence_number,
    started_at: ruleState.startedAt || new Date(ruleState.firstSeenAt).toISOString(),
    last_seen_at: new Date(now).toISOString(),
    payload: {
      camera_id: ruleState.cameraId,
      frame_id: result.frame_id,
      sequence_number: result.sequence_number,
      zone_name: zone.name,
      zone_type: zone.zone_type,
      rule_type: rule.rule_type,
      elapsed_seconds: Math.round((now - ruleState.firstSeenAt) / 1000),
      detection: detection
        ? {
            class_name: detection.class_name,
            confidence: detection.confidence,
            bbox_xyxy: detection.bbox_xyxy,
            track_id: detection.track_id,
          }
        : null,
    },
  };

  api("/api/ai-events", {
    method: "POST",
    body: JSON.stringify(payload),
  })
    .then((event) => {
      ruleState.aiEventId = event.id;
      ruleState.aiEventStatus = "created";
      if (document.getElementById("evidencePanel")?.classList.contains("active")) {
        evidenceTab.load().catch((error) => setStatus(`Load evidence failed: ${error.message}`));
      }
    })
    .catch((error) => {
      ruleState.aiEventStatus = "failed";
      ruleState.aiEventError = error.message;
      setStatus(`AI event save failed: ${error.message}`);
    });
}

function buildSourceEventId(ruleState, rule, result) {
  const firstSequence = ruleState.firstSequenceNumber ?? result.sequence_number ?? "unknown";
  return [ruleState.cameraId, ruleState.zoneId, rule.id, ruleState.trackId, firstSequence].join("|");
}

function detectionBottomCenterOriginal(detection) {
  const box = detection.bbox_xyxy || [0, 0, 0, 0];
  return {
    x: (Number(box[0] || 0) + Number(box[2] || 0)) / 2,
    y: Number(box[3] || 0),
  };
}

function trackKey(detection, result, index) {
  if (detection.track_id !== undefined && detection.track_id !== null) {
    return `${detection.class_name || "object"}-${detection.track_id}`;
  }
  return `${detection.class_name || "object"}-${result.sequence_number}-${index}`;
}

function reattachRuleState(cameraId, zone, rule, detection, result, index, currentTrackKey, seenTrackKeys, now) {
  const footpoint = detectionBottomCenterOriginal(detection);
  const bbox = detection.bbox_xyxy || null;
  let bestKey = null;
  let bestState = null;
  let bestDistance = Number.POSITIVE_INFINITY;

  Object.entries(state.ruleTrackStates).forEach(([key, candidate]) => {
    if (seenTrackKeys.has(key)) return;
    if (candidate.cameraId !== cameraId) return;
    if (candidate.zoneId !== zone.id) return;
    if (candidate.ruleId !== rule.id) return;
    if (candidate.objectType !== detection.class_name) return;
    if (candidate.trackId === currentTrackKey) return;
    if (!candidate.lastSeenAt || now - candidate.lastSeenAt > RULE_REATTACH_GRACE_MS) return;
    if (!candidate.lastFootpoint || !candidate.lastBbox || !bbox) return;
    if (!isAreaRatioCompatible(candidate.lastBbox, bbox)) return;

    const distance = pointDistance(candidate.lastFootpoint, footpoint);
    if (distance <= RULE_REATTACH_DISTANCE_PX && distance < bestDistance) {
      bestKey = key;
      bestState = candidate;
      bestDistance = distance;
    }
  });

  if (!bestState || !bestKey) return null;
  delete state.ruleTrackStates[bestKey];
  bestState.reattached = true;
  bestState.reattachedFrom = bestState.trackId;
  bestState.reattachedTo = currentTrackKey;
  bestState.reattachedAtSequenceNumber = result.sequence_number;
  return bestState;
}

function pointDistance(a, b) {
  const dx = Number(a.x || 0) - Number(b.x || 0);
  const dy = Number(a.y || 0) - Number(b.y || 0);
  return Math.sqrt(dx * dx + dy * dy);
}

function isAreaRatioCompatible(previousBbox, currentBbox) {
  const previousArea = bboxArea(previousBbox);
  const currentArea = bboxArea(currentBbox);
  if (previousArea <= 0 || currentArea <= 0) return false;
  const ratio = currentArea / previousArea;
  return ratio >= RULE_REATTACH_MIN_AREA_RATIO && ratio <= RULE_REATTACH_MAX_AREA_RATIO;
}

function bboxArea(bbox) {
  return Math.max(0, Number(bbox[2] || 0) - Number(bbox[0] || 0)) * Math.max(0, Number(bbox[3] || 0) - Number(bbox[1] || 0));
}

function ruleAppliesNow(rule, detection) {
  if (!rule || rule.enabled === false) return false;
  if (rule.object_type && detection.class_name !== rule.object_type) return false;
  if (rule.confidence_threshold !== null && rule.confidence_threshold !== undefined) {
    if (Number(detection.confidence || 0) < Number(rule.confidence_threshold)) return false;
  }
  if (rule.use_active_time && !isInActiveWindow(rule.active_start_time, rule.active_end_time)) return false;
  return true;
}

function isInActiveWindow(start, end) {
  if (!start || !end) return false;
  const now = new Date();
  const current = now.getHours() * 60 + now.getMinutes();
  const startMinutes = timeToMinutes(start);
  const endMinutes = timeToMinutes(end);
  if (startMinutes === endMinutes) return true;
  if (startMinutes < endMinutes) return current >= startMinutes && current <= endMinutes;
  return current >= startMinutes || current <= endMinutes;
}

function timeToMinutes(value) {
  const [hour, minute] = String(value).split(":").map((part) => Number(part));
  return hour * 60 + minute;
}

function expireRuleStates(cameraId, seenTrackKeys, now) {
  Object.entries(state.ruleTrackStates).forEach(([key, value]) => {
    if (value.cameraId !== cameraId) return;
    if (seenTrackKeys.has(key)) return;
    if (now - value.lastSeenAt > RULE_STATE_EXPIRE_MS) {
      delete state.ruleTrackStates[key];
    }
  });
  Object.entries(state.crowdRuleStates).forEach(([key, value]) => {
    if (!key.startsWith(`${cameraId}|`)) return;
    if (now - value.lastSeenAt > RULE_STATE_EXPIRE_MS) {
      delete state.crowdRuleStates[key];
    }
  });
}

function updateAlerts(alerts, now) {
  const alertMap = new Map(state.activeAlerts.map((alert) => [alert.key, alert]));
  alerts.forEach((alert) => {
    alert.lastSeenAt = now;
    alertMap.set(alert.key, alert);
  });
  state.activeAlerts = Array.from(alertMap.values()).filter((alert) => now - alert.lastSeenAt <= 4000);
  renderAlertBanner();
}

function renderAlertBanner() {
  if (!els.alertBanner) return;
  if (!state.activeAlerts.length) {
    els.alertBanner.hidden = true;
    els.alertBanner.innerHTML = "";
    return;
  }
  const latest = state.activeAlerts.slice(-3).reverse();
  els.alertBanner.hidden = false;
  els.alertBanner.innerHTML = latest
    .map(
      (alert) => {
        const camera = cameraById(alert.cameraId);
        const cameraName = camera ? camera.name : alert.cameraId;
        return `<div><strong>${escapeHtml(cameraName)}</strong> | ${escapeHtml(
          ruleLabel(alert.ruleType)
        )} | ${escapeHtml(alert.objectType)} ${escapeHtml(alert.trackId)} in ${escapeHtml(
          alert.zoneName
        )} - ${Math.round(alert.elapsedSeconds)}s</div>`;
      }
    )
    .join("");
}

function detectionBottomCenter(detection, frameWidth, frameHeight, viewport) {
  const box = detection.bbox_xyxy || [0, 0, 0, 0];
  return scalePoint(
    {
      x: (Number(box[0] || 0) + Number(box[2] || 0)) / 2,
      y: Number(box[3] || 0),
    },
    frameWidth,
    frameHeight,
    viewport
  );
}

function pointInPolygon(point, polygon) {
  if (!polygon || polygon.length < 3) return false;
  let inside = false;
  for (let current = 0, previous = polygon.length - 1; current < polygon.length; previous = current++) {
    const currentPoint = polygon[current];
    const previousPoint = polygon[previous];
    const intersects =
      currentPoint.y > point.y !== previousPoint.y > point.y &&
      point.x <
        ((previousPoint.x - currentPoint.x) * (point.y - currentPoint.y)) /
          (previousPoint.y - currentPoint.y) +
          currentPoint.x;
    if (intersects) inside = !inside;
  }
  return inside;
}

function zoneColor(zone) {
  if (!zone) return "#60a5fa";
  if (zone.zone_type === "restricted_area") return "#ef4444";
  if (zone.zone_type === "controlled_area") return "#3b82f6";
  return "#60a5fa";
}

function zoneTypeLabel(zoneType) {
  if (zoneType === "restricted_area") return "Restricted";
  if (zoneType === "controlled_area") return "Controlled";
  return zoneType || "Zone";
}

function matchedZoneLabel(matchedZones) {
  if (!matchedZones.length) return "";
  return matchedZones.map((zone) => zoneTypeLabel(zone.zone_type)).join(", ");
}

function drawBottomCenter(ctx, point, matched) {
  ctx.beginPath();
  ctx.arc(point.x, point.y, matched ? 5 : 4, 0, Math.PI * 2);
  ctx.fillStyle = matched ? "#ef4444" : "#f8fafc";
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = matched ? "#fee2e2" : "#0f172a";
  ctx.stroke();
}

function drawMatchLabel(ctx, point, label) {
  if (!label) return;
  ctx.font = "11px Arial";
  const text = `in ${label}`;
  const textWidth = ctx.measureText(text).width + 8;
  const x = point.x + 7;
  const y = Math.max(18, point.y - 8);
  ctx.fillStyle = "rgba(239, 68, 68, 0.9)";
  ctx.fillRect(x, y - 14, textWidth, 16);
  ctx.fillStyle = "#fff7ed";
  ctx.fillText(text, x + 4, y - 2);
}

function containViewport(canvasWidth, canvasHeight, frameWidth, frameHeight) {
  const scale = Math.min(canvasWidth / Math.max(1, frameWidth), canvasHeight / Math.max(1, frameHeight));
  const width = frameWidth * scale;
  const height = frameHeight * scale;
  return {
    x: (canvasWidth - width) / 2,
    y: (canvasHeight - height) / 2,
    width,
    height,
  };
}

function scalePoint(point, frameWidth, frameHeight, viewport) {
  return {
    x: viewport.x + (point.x / Math.max(1, frameWidth)) * viewport.width,
    y: viewport.y + (point.y / Math.max(1, frameHeight)) * viewport.height,
  };
}

function drawDetection(ctx, detection, frameWidth, frameHeight, viewport, match = {}) {
  const box = detection.bbox_xyxy || [0, 0, 0, 0];
  const p1 = scalePoint({ x: box[0], y: box[1] }, frameWidth, frameHeight, viewport);
  const p2 = scalePoint({ x: box[2], y: box[3] }, frameWidth, frameHeight, viewport);
  const color = detection.class_name === "car" ? "#38bdf8" : "#39ff14";
  const track = detection.track_id !== undefined && detection.track_id !== null ? ` #${detection.track_id}` : "";
  const label = `${detection.class_name}${track} ${Number(detection.confidence || 0).toFixed(2)}`;
  const matched = Boolean(match.matchedZones && match.matchedZones.length);
  const matchLabel = matchedZoneLabel(match.matchedZones || []);

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(p1.x, p1.y, Math.max(1, p2.x - p1.x), Math.max(1, p2.y - p1.y));

  ctx.font = "12px Arial";
  const textWidth = ctx.measureText(label).width + 8;
  ctx.fillStyle = color;
  ctx.fillRect(p1.x, Math.max(0, p1.y - 18), textWidth, 18);
  ctx.fillStyle = "#06110f";
  ctx.fillText(label, p1.x + 4, Math.max(12, p1.y - 5));
  if (match.bottomCenter) {
    drawBottomCenter(ctx, match.bottomCenter, matched);
    drawMatchLabel(ctx, match.bottomCenter, matchLabel);
  }
}

function drawZoneLabel(ctx, points, label, color) {
  if (!points.length) return;
  const anchor = points.reduce(
    (sum, point) => ({ x: sum.x + point.x / points.length, y: sum.y + point.y / points.length }),
    { x: 0, y: 0 }
  );
  ctx.font = "12px Arial";
  const textWidth = ctx.measureText(label).width + 8;
  ctx.fillStyle = withAlpha(color, 0.85);
  ctx.fillRect(anchor.x, anchor.y - 16, textWidth, 18);
  ctx.fillStyle = "#06110f";
  ctx.fillText(label, anchor.x + 4, anchor.y - 3);
}

function drawPolygon(ctx, points, color, alpha) {
  if (!points.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  points.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
  if (points.length > 2) ctx.closePath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.stroke();
  if (points.length > 2) {
    ctx.fillStyle = withAlpha(color, alpha);
    ctx.fill();
  }
}

function drawHandle(ctx, point, color) {
  ctx.beginPath();
  ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#071110";
  ctx.stroke();
}

function withAlpha(hex, alpha) {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function clearDraft() {
  state.draftPoints = [];
  draw();
}

function undoPoint() {
  state.draftPoints.pop();
  draw();
}

function setStatus(message) {
  els.statusText.textContent = message;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    activateTab(tab.dataset.tab);
  });
});

function activateTab(tabName) {
  document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".panel").forEach((item) => item.classList.remove("active"));
  const tab = document.querySelector(`.tab[data-tab="${tabName}"]`);
  const panel = document.getElementById(`${tabName}Panel`);
  if (!tab || !panel) return;
  tab.classList.add("active");
  panel.classList.add("active");
  if (tabName === "evidence") {
    evidenceTab.load().catch((error) => setStatus(`Load evidence failed: ${error.message}`));
  }
}

function initialTabFromPath() {
  if (window.location.pathname === "/detect") return "yolo";
  return "live";
}

window.addEventListener("resize", () => {
  state.cameras.forEach((camera) => drawYoloOverlay(camera.id));
});

els.captureButton.addEventListener("click", captureReferenceFrame);
evidenceTab.bind();
els.saveZoneButton.addEventListener("click", saveZone);
els.clearButton.addEventListener("click", clearDraft);
els.undoButton.addEventListener("click", undoPoint);
els.zoneCanvas.addEventListener("pointerdown", onCanvasPointerDown);
els.zoneCanvas.addEventListener("pointermove", onCanvasPointerMove);
els.zoneCanvas.addEventListener("pointerup", onCanvasPointerUp);
els.zoneCanvas.addEventListener("pointerleave", onCanvasPointerUp);

loadCameras().catch((error) => {
  setStatus(error.message);
});
activateTab(initialTabFromPath());
