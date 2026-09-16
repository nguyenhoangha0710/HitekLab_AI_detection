function datetimeLocalToIso(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString();
}

function buildEvidenceQuery(els, cameraId) {
  const params = new URLSearchParams({ limit: "100", evidence_type: "video_clip" });
  if (cameraId) params.set("camera_id", cameraId);
  if (els.evidenceEventTypeFilter?.value) params.set("event_type", els.evidenceEventTypeFilter.value);
  if (els.evidenceStatusFilter?.value) params.set("status", els.evidenceStatusFilter.value);
  if (els.evidenceFromFilter?.value) params.set("from", datetimeLocalToIso(els.evidenceFromFilter.value));
  if (els.evidenceToFilter?.value) params.set("to", datetimeLocalToIso(els.evidenceToFilter.value));
  return params;
}

function buildLabelQuery(cameraId) {
  const params = new URLSearchParams({ limit: "500" });
  if (cameraId) params.set("camera_id", cameraId);
  return params;
}

export function createEvidenceTab({ els, state, api, cameraById, ruleLabel, escapeHtml, setStatus }) {
  async function load() {
    if (!els.evidenceGrid) return;
    const cameraId = els.evidenceCameraFilter?.value || "";
    const labelParams = buildLabelQuery(cameraId);
    const evidenceParams = buildEvidenceQuery(els, cameraId);

    const [events, alerts, evidence] = await Promise.all([
      api(`/api/ai-events?${labelParams.toString()}`),
      api(`/api/alerts?${labelParams.toString()}`),
      api(`/api/evidence?${evidenceParams.toString()}`),
    ]);
    state.aiEvents = events;
    state.alerts = alerts;
    state.evidence = evidence;
    render();
  }

  function renderCameraFilter() {
    if (!els.evidenceCameraFilter) return;
    const currentValue = els.evidenceCameraFilter.value;
    els.evidenceCameraFilter.innerHTML = `<option value="">All cameras</option>`;
    state.cameras.forEach((camera) => {
      const option = document.createElement("option");
      option.value = camera.id;
      option.textContent = camera.name;
      els.evidenceCameraFilter.appendChild(option);
    });
    els.evidenceCameraFilter.value = currentValue;
  }

  function render() {
    if (!els.evidenceGrid) return;
    const eventById = new Map(state.aiEvents.map((event) => [event.id, event]));
    const alertById = new Map(state.alerts.map((alert) => [alert.id, alert]));
    const videoEvidence = state.evidence.filter(
      (item) => item.evidence_type === "video_clip" || String(item.mime_type || "").startsWith("video/")
    );
    if (!videoEvidence.length) {
      els.evidenceGrid.innerHTML = `<div class="zone-card"><p>No video evidence clips found for these filters.</p></div>`;
      return;
    }

    els.evidenceGrid.innerHTML = videoEvidence
      .map((item) => evidenceCardTemplate(item, eventById, alertById))
      .join("");
  }

  function evidenceCardTemplate(item, eventById, alertById) {
    const event = eventById.get(item.ai_event_id);
    const alert = item.alert_id ? alertById.get(item.alert_id) : null;
    const camera = cameraById(item.camera_id);
    const eventType = alert ? ruleLabel(alert.rule_type) : event ? ruleLabel(event.event_type) : "AI Event";
    const objectType = alert?.object_type || event?.object_type;
    const objectLabel = objectType ? `${objectType} ${event?.track_id || ""}`.trim() : "object";
    const sequence = item.sequence_number !== null && item.sequence_number !== undefined ? item.sequence_number : "-";
    const sourceCount = alert ? ` | sources ${alert.active_source_count}` : "";
    const mediaUrl = `${escapeHtml(item.media_url)}?t=${Date.now()}`;
    const videoDuration = item.duration_seconds ? Number(item.duration_seconds).toFixed(1) : "-";

    return `
      <article class="evidence-card">
        <header>
          <h2>${escapeHtml(camera?.name || item.camera_id)}</h2>
          <p>${escapeHtml(eventType)} | ${escapeHtml(objectLabel)} | seq ${escapeHtml(sequence)}${escapeHtml(sourceCount)}</p>
        </header>
        <video controls muted preload="metadata" src="${mediaUrl}"></video>
        <div class="evidence-meta">
          <span>Captured: ${escapeHtml(item.captured_at)}</span>
          <span>Evidence: ${escapeHtml(item.evidence_type)} | ${escapeHtml(item.mime_type)}</span>
          <span>Video: ${escapeHtml(item.status || "-")} | ${escapeHtml(item.codec || "-")} | ${videoDuration}s</span>
          <span>Alert: ${escapeHtml(item.alert_id || "-")}</span>
          <span>Event: ${escapeHtml(item.ai_event_id)}</span>
        </div>
      </article>
    `;
  }

  function bind() {
    const reload = () => load().catch((error) => setStatus(`Load evidence failed: ${error.message}`));
    els.refreshEvidenceButton?.addEventListener("click", reload);
    els.evidenceCameraFilter?.addEventListener("change", reload);
    [els.evidenceEventTypeFilter, els.evidenceStatusFilter, els.evidenceFromFilter, els.evidenceToFilter].forEach(
      (filter) => {
        filter?.addEventListener("change", reload);
      }
    );
  }

  return {
    bind,
    load,
    render,
    renderCameraFilter,
  };
}
