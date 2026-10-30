// Dang nhap / hien thi user hien tai va cac location duoc phep.
import { api, getToken, setToken } from "./api.js";

export async function ensureSignedIn(authBar) {
  const config = await api("/api/auth/config").catch(() => ({ auth_mode: "off" }));
  if (config.auth_mode !== "jwt") {
    authBar.innerHTML = `<span class="auth-user">Auth off (dev)</span>`;
    return null;
  }
  if (getToken()) {
    try {
      const me = await api("/api/me");
      renderUser(authBar, me);
      return me;
    } catch (error) {
      setToken(null);
    }
  }
  await showLogin(authBar, config);
  return null; // trang se reload sau khi dang nhap
}

function renderUser(authBar, me) {
  const locations = (me.locations || []).map((loc) => `${loc.name} (${loc.level})`).join(", ") || "khong co location";
  authBar.innerHTML = `
    <span class="auth-user" title="${escapeAttr(locations)}">
      ${escapeHtml(me.full_name || me.email || me.user_id)} · ${escapeHtml(me.role || me.kind)} · ${escapeHtml(locations)}
    </span>
    <button type="button" id="logoutButton">Dang xuat</button>`;
  authBar.querySelector("#logoutButton").addEventListener("click", () => {
    setToken(null);
    window.location.reload();
  });
}

async function showLogin(authBar, config) {
  let users = [];
  if (config.dev_login) {
    users = await api("/api/auth/dev-users").catch(() => []);
  }
  const devForm = users.length
    ? `<select id="devUserSelect">${users
        .map((u) => `<option value="${escapeAttr(u.email)}">${escapeHtml(u.email)} (${escapeHtml(u.role)})</option>`)
        .join("")}</select>
       <button type="button" id="devLoginButton">Dang nhap demo</button>`
    : "";
  authBar.innerHTML = `
    <div class="auth-login">
      ${devForm}
      <input id="tokenInput" type="password" placeholder="hoac dan JWT tu Backend">
      <button type="button" id="tokenLoginButton">Dung token</button>
    </div>`;
  const devButton = authBar.querySelector("#devLoginButton");
  if (devButton) {
    devButton.addEventListener("click", async () => {
      const email = authBar.querySelector("#devUserSelect").value;
      const result = await api("/api/auth/dev-login", { method: "POST", body: JSON.stringify({ email }) });
      setToken(result.access_token);
      window.location.reload();
    });
  }
  authBar.querySelector("#tokenLoginButton").addEventListener("click", () => {
    const token = authBar.querySelector("#tokenInput").value.trim();
    if (!token) return;
    setToken(token);
    window.location.reload();
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

function escapeAttr(value) {
  return escapeHtml(value);
}
