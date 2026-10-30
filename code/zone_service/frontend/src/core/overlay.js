// Ve zone + bbox + diem chan + huong di chuyen len canvas phu tren anh/video.
import { OBJECT_COLORS, motionArrow, zoneTypeInfo } from "./format.js";

const FONT = '600 12px "Be Vietnam Pro", system-ui, sans-serif';

export function containViewport(canvasWidth, canvasHeight, frameWidth, frameHeight) {
  const scale = Math.min(canvasWidth / Math.max(1, frameWidth), canvasHeight / Math.max(1, frameHeight));
  const width = frameWidth * scale;
  const height = frameHeight * scale;
  return { x: (canvasWidth - width) / 2, y: (canvasHeight - height) / 2, width, height };
}

export function scalePoint(point, frameWidth, frameHeight, viewport) {
  return {
    x: viewport.x + (point.x / Math.max(1, frameWidth)) * viewport.width,
    y: viewport.y + (point.y / Math.max(1, frameHeight)) * viewport.height,
  };
}

export function pointInPolygon(point, polygon) {
  if (!polygon || polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i];
    const b = polygon[j];
    if (a.y > point.y !== b.y > point.y && point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x) {
      inside = !inside;
    }
  }
  return inside;
}

export function withAlpha(hex, alpha) {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function drawPolygon(ctx, points, color, fillAlpha, { dashed = false, width = 2 } = {}) {
  if (!points.length) return;
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  points.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
  if (points.length > 2) ctx.closePath();
  ctx.setLineDash(dashed ? [8, 6] : []);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.stroke();
  if (points.length > 2 && fillAlpha > 0) {
    ctx.fillStyle = withAlpha(color, fillAlpha);
    ctx.fill();
  }
  ctx.restore();
}

export function drawHandle(ctx, point, color) {
  ctx.beginPath();
  ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#121a24";
  ctx.stroke();
}

function tag(ctx, text, x, y, background, foreground = "#0e141c") {
  ctx.font = FONT;
  const width = ctx.measureText(text).width + 10;
  const top = Math.max(0, y - 18);
  ctx.fillStyle = background;
  ctx.fillRect(x, top, width, 18);
  ctx.fillStyle = foreground;
  ctx.fillText(text, x + 5, top + 13);
}

function zoneAnchor(points) {
  // Goc tren-trai nhat cua polygon: nhan khong de len giua vung.
  return points.reduce((best, p) => (p.y + p.x * 0.25 < best.y + best.x * 0.25 ? p : best), points[0]);
}

/**
 * Ve toan bo lop phu cho 1 camera.
 * @param {HTMLCanvasElement} canvas  canvas phu (kich thuoc theo phan tu hien thi)
 * @param {{width:number,height:number}} frame  kich thuoc goc cua khung hinh
 * @param {Array} zones   zone cua camera (polygon theo frame_width/frame_height cua zone)
 * @param {Object|null} result  ket qua AI (detections, frame_width, frame_height)
 * @param {Set<string>} violatingZoneIds  zone dang co vi pham (ve dam hon)
 */
export function drawOverlay(canvas, frame, zones, result, violatingZoneIds = new Set()) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  const frameWidth = frame.width || result?.frame_width || width;
  const frameHeight = frame.height || result?.frame_height || height;
  const viewport = containViewport(width, height, frameWidth, frameHeight);

  const scaledZones = (zones || [])
    .filter((zone) => zone.enabled !== false)
    .map((zone) => ({
      ...zone,
      scaled: (zone.polygon?.points || []).map((p) => scalePoint(p, zone.frame_width, zone.frame_height, viewport)),
    }));

  scaledZones.forEach((zone) => {
    const { color } = zoneTypeInfo(zone.zone_type);
    const hot = violatingZoneIds.has(zone.id);
    drawPolygon(ctx, zone.scaled, color, hot ? 0.28 : 0.1, { dashed: !hot, width: hot ? 3 : 2 });
    if (zone.scaled.length) {
      const anchor = zoneAnchor(zone.scaled);
      tag(ctx, zone.name, anchor.x + 2, anchor.y + 20, withAlpha(color, 0.92));
    }
  });

  if (!result?.detections) return;
  const rw = result.frame_width || frameWidth;
  const rh = result.frame_height || frameHeight;
  result.detections.forEach((det) => {
    const box = det.bbox_xyxy || [0, 0, 0, 0];
    const p1 = scalePoint({ x: box[0], y: box[1] }, rw, rh, viewport);
    const p2 = scalePoint({ x: box[2], y: box[3] }, rw, rh, viewport);
    const foot = scalePoint({ x: (box[0] + box[2]) / 2, y: box[3] }, rw, rh, viewport);
    const inZone = scaledZones.some((zone) => pointInPolygon(foot, zone.scaled));
    const color = OBJECT_COLORS[det.class_name] || "#5cc8ff";

    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = inZone ? 3 : 2;
    ctx.strokeRect(p1.x, p1.y, Math.max(1, p2.x - p1.x), Math.max(1, p2.y - p1.y));
    ctx.restore();

    const track = det.track_id !== undefined && det.track_id !== null ? ` #${det.track_id}` : "";
    const arrow = motionArrow(det.motion?.direction);
    tag(ctx, `${det.class_name}${track}${arrow ? ` ${arrow}` : ""}`, p1.x, p1.y, color);

    ctx.beginPath();
    ctx.arc(foot.x, foot.y, inZone ? 5 : 3.5, 0, Math.PI * 2);
    ctx.fillStyle = inZone ? "#f0533a" : "#e6edf5";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#121a24";
    ctx.stroke();
  });
}
