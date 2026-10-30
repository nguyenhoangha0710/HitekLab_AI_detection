// Nhan tieng Viet, dinh dang thoi gian, escape HTML dung chung cho moi man hinh.

export const RULE_LABELS = {
  person_intrusion: "Xâm nhập vùng cấm",
  vehicle_intrusion: "Xe vào vùng cấm",
  loitering: "Lảng vảng",
  crowd_limit: "Tụ tập đông người",
  vehicle_stopping: "Xe dừng quá lâu",
};

export const RULE_HINTS = {
  person_intrusion: "Báo khi có người ở trong vùng lâu hơn số giây đặt ra (0 = báo ngay).",
  vehicle_intrusion: "Báo khi có xe ở trong vùng lâu hơn số giây đặt ra (0 = báo ngay).",
  loitering: "Báo khi một người đi tới đi lui trong vùng quá lâu.",
  crowd_limit: "Báo khi số người trong vùng đạt ngưỡng và giữ liên tục đủ số giây.",
  vehicle_stopping: "Báo khi một xe dừng trong vùng quá lâu.",
};

export const ZONE_TYPES = {
  restricted_area: { label: "Vùng cấm", color: "#f0533a" },
  controlled_area: { label: "Vùng hạn chế", color: "#f2b134" },
};

export const OBJECT_LABELS = {
  person: "Người",
  vehicle: "Xe (mọi loại)",
  car: "Ô tô",
  motorcycle: "Xe máy",
  bus: "Xe buýt",
  truck: "Xe tải",
  bicycle: "Xe đạp",
};

export const OBJECT_COLORS = {
  person: "#5cc8ff",
  car: "#b892ff",
  motorcycle: "#ff8fd0",
  bus: "#b892ff",
  truck: "#b892ff",
};

export const MOTION = {
  right: { arrow: "→", label: "sang phải" },
  "up-right": { arrow: "↗", label: "lên, sang phải" },
  up: { arrow: "↑", label: "đi lên (ra xa)" },
  "up-left": { arrow: "↖", label: "lên, sang trái" },
  left: { arrow: "←", label: "sang trái" },
  "down-left": { arrow: "↙", label: "xuống, sang trái" },
  down: { arrow: "↓", label: "đi xuống (lại gần)" },
  "down-right": { arrow: "↘", label: "xuống, sang phải" },
  stationary: { arrow: "•", label: "đứng yên" },
};

export const LEVEL_LABELS = { admin: "Quản trị", operator: "Vận hành", viewer: "Chỉ xem" };
export const ROLE_LABELS = { owner: "Chủ tenant", admin: "Quản trị tenant", operator: "Vận hành", viewer: "Chỉ xem" };

export function ruleLabel(type) {
  return RULE_LABELS[type] || humanize(type);
}

export function objectLabel(type) {
  return OBJECT_LABELS[type] || humanize(type);
}

export function zoneTypeInfo(type) {
  return ZONE_TYPES[type] || { label: humanize(type) || "Vùng", color: "#8c9aad" };
}

export function motionArrow(direction) {
  return MOTION[direction]?.arrow || "";
}

export function motionLabel(direction) {
  return MOTION[direction]?.label || "";
}

export function humanize(value) {
  return String(value || "")
    .split("_")
    .filter(Boolean)
    .map((part, index) => (index === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(" ");
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const timeFormat = new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function trackLabel(trackId) {
  // "person-12" -> "#12"; giu nguyen cac dang khac (vd "5 objects")
  const match = String(trackId ?? "").match(/-(\d+)$/);
  return match ? `#${match[1]}` : String(trackId ?? "");
}

export function formatTime(value) {
  const date = toDate(value);
  return date ? timeFormat.format(date) : "–";
}

export function formatDateTime(value) {
  const date = toDate(value);
  if (!date) return "–";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)} ${timeFormat.format(date)}`;
}

export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) return `${total} giây`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${minutes} phút ${rest} giây` : `${minutes} phút`;
}

export function formatAgo(value) {
  const date = toDate(value);
  if (!date) return "–";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 5) return "vừa xong";
  if (seconds < 60) return `${seconds} giây trước`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} phút trước`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} giờ trước`;
  return formatDateTime(date);
}

export function toDate(value) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function countBy(items, keyFn) {
  const counts = {};
  items.forEach((item) => {
    const key = keyFn(item);
    counts[key] = (counts[key] || 0) + 1;
  });
  return counts;
}
