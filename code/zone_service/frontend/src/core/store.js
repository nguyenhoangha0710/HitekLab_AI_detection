// Trang thai dung chung + ket noi luong ket qua AI (SSE) cho moi camera.
import { api, withToken } from "./api.js";

const listeners = new Map();

export const store = {
  me: null,
  authConfig: { auth_mode: "off" },
  cameras: [],
  zonesByCamera: {}, // cameraId -> [zone]
  rulesByZone: {}, // zoneId -> [rule]
  results: {}, // cameraId -> ket qua AI moi nhat
  resultStats: {}, // cameraId -> { count, firstAt, lastAt, inferenceMs[] }
  violations: new Map(), // key -> { ...violation, cameraId, lastSeenAt }
  streams: {},
};

export function on(event, handler) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(handler);
  return () => listeners.get(event)?.delete(handler);
}

export function emit(event, payload) {
  listeners.get(event)?.forEach((handler) => {
    try {
      handler(payload);
    } catch (error) {
      console.error(error);
    }
  });
}

export function cameraById(id) {
  return store.cameras.find((camera) => camera.id === id);
}

export function cameraName(id) {
  return cameraById(id)?.name || id;
}

export async function loadCameras() {
  store.cameras = await api("/api/cameras");
  emit("cameras", store.cameras);
  return store.cameras;
}

export async function loadZones(cameraId) {
  const zones = await api(`/api/cameras/${encodeURIComponent(cameraId)}/zones`);
  const entries = await Promise.all(
    zones.map(async (zone) => [zone.id, await api(`/api/zones/${encodeURIComponent(zone.id)}/rules`).catch(() => [])])
  );
  store.zonesByCamera[cameraId] = zones;
  entries.forEach(([zoneId, rules]) => {
    store.rulesByZone[zoneId] = rules;
  });
  emit("zones", { cameraId, zones });
  return zones;
}

const VIOLATION_TTL_MS = 4000;

export function connectResults() {
  store.cameras.forEach((camera) => {
    if (store.streams[camera.id]) return;
    const source = new EventSource(withToken(camera.detection_stream_url));
    store.streams[camera.id] = source;
    source.onmessage = (message) => {
      let result;
      try {
        result = JSON.parse(message.data);
      } catch (error) {
        return;
      }
      ingestResult(camera.id, result);
    };
    source.onerror = () => emit("stream-error", camera.id);
  });
  window.setInterval(expireViolations, 1000);
}

function ingestResult(cameraId, result) {
  store.results[cameraId] = result;
  const now = Date.now();
  const stats = store.resultStats[cameraId] || { count: 0, firstAt: now, lastAt: now, inferenceMs: [], latencyMs: [] };
  stats.count += 1;
  stats.lastAt = now;
  if (typeof result.inference_ms === "number") {
    stats.inferenceMs.push(result.inference_ms);
    if (stats.inferenceMs.length > 30) stats.inferenceMs.shift();
  }
  const captured = result.captured_at ? Date.parse(result.captured_at) : NaN;
  if (!Number.isNaN(captured)) {
    stats.latencyMs.push(now - captured);
    if (stats.latencyMs.length > 30) stats.latencyMs.shift();
  }
  store.resultStats[cameraId] = stats;

  (result.rule_engine?.violations || []).forEach((violation) => {
    const key = violation.key || `${cameraId}|${violation.zone_id}|${violation.rule_type}|${violation.track_id}`;
    const existing = store.violations.get(key);
    store.violations.set(key, { ...violation, cameraId, key, lastSeenAt: now, firstSeenAt: existing?.firstSeenAt || now });
  });
  emit("result", { cameraId, result });
  emit("violations", activeViolations());
}

function expireViolations() {
  const now = Date.now();
  let changed = false;
  store.violations.forEach((value, key) => {
    if (now - value.lastSeenAt > VIOLATION_TTL_MS) {
      store.violations.delete(key);
      changed = true;
    }
  });
  if (changed) emit("violations", activeViolations());
}

export function activeViolations() {
  return Array.from(store.violations.values()).sort((a, b) => b.firstSeenAt - a.firstSeenAt);
}

export function average(values) {
  if (!values?.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function latestRuntime() {
  const results = Object.values(store.results).filter((result) => result?.ai_runtime);
  return results.length ? results[results.length - 1].ai_runtime : null;
}
